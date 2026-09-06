"""HTTP surface for the scheduling engine - workflow stages 2, 2B, 3, 4, 5, 6, 8.

Thin glue only: every scheduling decision (feasibility, ranking, cascade,
cancel/reschedule) is made by the pure engine in this package; this file's
job is auth/RBAC, translating HTTP bodies to/from the engine's Pydantic
models, and issuing the ``InviteToken`` so a candidate can authenticate
against their request through the *existing* invite-link mechanism (see
AUTH_MODULE.md) rather than a second, parallel one.

State itself (requests, interviews, the interviewer directory) is real DB
persistence now - ``service.py``'s ``SchedulingService``, backed by the
tables in ``app/db/models.py`` (Documentation/IMPLEMENTATION_PLAN.md Phase 2).
One service instance per request, built fresh from the same ``db`` session
every other endpoint here already uses - no more in-memory singleton.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.security import hash_invite_token
from app.db.models import InviteToken, User
from app.db.session import get_db
from app.notifications.service import EmailSendError, send_email

from . import schemas
from .models import AvailabilityWindow
from .service import ForbiddenError, NotFoundError, SchedulingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduling", tags=["scheduling"])

STAFF_ROLES = ("recruiter", "hiring_manager")


def _wrap(fn, *args, **kwargs):
    """Translate the service's plain exceptions into the right HTTP status."""
    try:
        return fn(*args, **kwargs)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_staff(user: User) -> None:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="insufficient_role")


def _detail(svc: SchedulingService, request_id: str) -> schemas.RequestDetail:
    request = _wrap(svc.get_request, request_id)
    round_ = svc.get_round(request_id)
    return schemas.RequestDetail(
        request=request,
        round=round_,
        feasibility=svc.get_feasibility(request_id),
        interview=svc.get_interview_for_request(request_id),
    )


# --------------------------------------------------------------------------- #
# Module 2 - Create Interview Request (recruiter/hiring_manager)
# --------------------------------------------------------------------------- #


@router.post("/requests", response_model=schemas.CreateRequestResponse)
def create_request(
    body: schemas.CreateRequestBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_staff(user)
    svc = SchedulingService(db)

    request, round_ = svc.create_request(
        owner_user_id=user.id,
        owner_email=user.email,
        interview_type=body.interview_type,
        required_skills=body.required_skills,
        seniority=body.seniority,
        panelists_required=body.panelists_required,
        duration_minutes=body.duration_minutes,
        buffer_minutes_before=body.buffer_minutes_before,
        buffer_minutes_after=body.buffer_minutes_after,
        hiring_manager_email=body.hiring_manager_email,
        candidate_name=body.candidate_name,
        candidate_email=body.candidate_email,
        candidate_timezone=body.candidate_timezone,
    )

    # Bridge into the real auth module's invite-link mechanism (AUTH_MODULE.md)
    # instead of building a second one: `svc.create_request` already wrote
    # the real `Interview` row sharing its id with `request.request_id`, so a
    # candidate's session (once they use this link) resolves straight back to
    # it - only the invite token itself is this endpoint's own concern.
    raw_token = secrets.token_urlsafe(32)
    db.add(
        InviteToken(
            interview_id=request.request_id,
            candidate_email=body.candidate_email,
            token_hash=hash_invite_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(days=14),
        )
    )
    db.commit()

    invite_link = f"{settings.FRONTEND_URL}/login?invite_token={raw_token}"

    # Priority #1 email per Documentation/IMPLEMENTATION_PLAN.md Phase 1: this
    # used to only return invite_link for the recruiter to copy by hand.
    # Best-effort — a Resend outage must not fail request creation; invite_link
    # is still in the response either way as the fallback the frontend already
    # offers (RequestNew.jsx's copy-link button).
    try:
        send_email(
            body.candidate_email,
            f"You're invited to interview — {body.interview_type.replace('_', ' ')}",
            f"<p>Hi {body.candidate_name},</p>"
            f"<p>You've been invited to schedule a {body.interview_type.replace('_', ' ')} "
            f"interview. Use the link below to submit your availability:</p>"
            f'<p><a href="{invite_link}">{invite_link}</a></p>',
        )
    except EmailSendError:
        logger.warning("Invite email failed for request_id=%s", request.request_id, exc_info=True)

    return schemas.CreateRequestResponse(request=request, round=round_, invite_link=invite_link)


@router.get("/requests", response_model=list[schemas.RequestDetail])
def list_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_staff(user)
    svc = SchedulingService(db)
    return [_detail(svc, r.request_id) for r in svc.list_requests()]


@router.get("/requests/{request_id}", response_model=schemas.RequestDetail)
def get_request_detail(
    request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    svc = SchedulingService(db)
    detail = _detail(svc, request_id)
    is_owner_candidate = user.role == "candidate" and user.email.lower() == detail.request.candidate_id.lower()
    if user.role not in STAFF_ROLES and not is_owner_candidate:
        raise HTTPException(status_code=403, detail="insufficient_role")
    return detail


# --------------------------------------------------------------------------- #
# Candidate side - stages 3 & 5
# --------------------------------------------------------------------------- #


def _require_candidate_owns(user: User, svc: SchedulingService, request_id: str):
    request = _wrap(svc.get_request, request_id)
    if user.role != "candidate" or user.email.lower() != request.candidate_id.lower():
        raise HTTPException(status_code=403, detail="not_your_interview")
    return request


def _require_candidate_or_staff(user: User, svc: SchedulingService, request_id: str):
    """Cancelling is one action both sides legitimately need: the candidate
    (their own interview) and staff (any recruiter/hiring_manager - matches
    the existing list/get_request_detail permission model, which already
    lets any staff member see any request, not just the one they created)."""
    request = _wrap(svc.get_request, request_id)
    is_owner_candidate = user.role == "candidate" and user.email.lower() == request.candidate_id.lower()
    if user.role not in STAFF_ROLES and not is_owner_candidate:
        raise HTTPException(status_code=403, detail="not_your_interview")
    return request


@router.get("/my-request", response_model=schemas.RequestDetail | None)
def my_request(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "candidate":
        raise HTTPException(status_code=403, detail="insufficient_role")
    svc = SchedulingService(db)
    request = svc.find_request_by_candidate_email(user.email)
    if request is None:
        return None
    return _detail(svc, request.request_id)


@router.post("/requests/{request_id}/availability", response_model=schemas.RequestDetail)
def submit_availability(
    request_id: str,
    body: schemas.SubmitAvailabilityBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = SchedulingService(db)
    _require_candidate_owns(user, svc, request_id)
    windows = [
        AvailabilityWindow(start=w.start, end=w.end, source_timezone=w.source_timezone)
        for w in body.windows
    ]
    _wrap(svc.submit_availability, request_id, windows)
    return _detail(svc, request_id)


@router.post("/requests/{request_id}/select-slot", response_model=schemas.RequestDetail)
def select_slot(
    request_id: str,
    body: schemas.SelectSlotBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = SchedulingService(db)
    _require_candidate_owns(user, svc, request_id)
    _wrap(svc.select_slot, request_id, body.slot_id)
    return _detail(svc, request_id)


@router.post("/requests/{request_id}/cancel", response_model=schemas.RequestDetail)
def cancel_request(
    request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    svc = SchedulingService(db)
    _require_candidate_or_staff(user, svc, request_id)
    reason = "the candidate cancelled" if user.role == "candidate" else f"cancelled by {user.name} ({user.role})"
    _wrap(svc.candidate_cancel, request_id, reason)
    return _detail(svc, request_id)


@router.post("/requests/{request_id}/reschedule", response_model=schemas.RequestDetail)
def reschedule_request(
    request_id: str,
    body: schemas.SubmitAvailabilityBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stage 8: the candidate's booked time no longer works - releases every
    seat, deletes the real Calendar event if one exists, and immediately
    accepts the new windows in the body (MODULE_GUIDE.md's Module 8: "expects
    new/updated availability windows, loops back to Module 3")."""
    svc = SchedulingService(db)
    _require_candidate_owns(user, svc, request_id)
    windows = [
        AvailabilityWindow(start=w.start, end=w.end, source_timezone=w.source_timezone)
        for w in body.windows
    ]
    _wrap(svc.candidate_reschedule, request_id, windows)
    return _detail(svc, request_id)


# --------------------------------------------------------------------------- #
# Interviewer side - Module 2B + stages 6 & 8
# --------------------------------------------------------------------------- #


def _require_interviewer(user: User) -> None:
    if user.role != "interviewer":
        raise HTTPException(status_code=403, detail="insufficient_role")


@router.get("/interviewer/profile")
def get_my_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_interviewer(user)
    svc = SchedulingService(db)
    profile = svc.get_interviewer_profile(user.id)
    return profile.model_dump() if profile else None


@router.put("/interviewer/profile")
def upsert_my_profile(
    body: schemas.InterviewerProfileBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_interviewer(user)
    svc = SchedulingService(db)
    profile = svc.upsert_interviewer_profile(
        interviewer_id=user.id,
        name=user.name,
        email=user.email,
        skills=body.skills,
        seniority=body.seniority,
        interview_types=body.interview_types,
        timezone_name=body.timezone,
        working_hours_start=body.working_hours_start,
        working_hours_end=body.working_hours_end,
        active=body.active,
    )
    return profile.model_dump()


@router.get("/interviewer/offers", response_model=list[schemas.OfferOut])
def my_offers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_interviewer(user)
    svc = SchedulingService(db)
    return [
        schemas.OfferOut(interview=interview, seat_index=seat.seat_index)
        for interview, seat in svc.list_offers_for_interviewer(user.id)
    ]


@router.post("/interviews/{interview_id}/seats/{seat_index}/respond", response_model=schemas.OfferOut)
def respond_to_seat(
    interview_id: str,
    seat_index: int,
    body: schemas.SeatResponseBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_interviewer(user)
    svc = SchedulingService(db)
    interview, _request = _wrap(
        svc.respond_to_seat,
        interview_id,
        seat_index,
        accept=body.accept,
        actor_interviewer_id=user.id,
    )
    return schemas.OfferOut(interview=interview, seat_index=seat_index)


@router.post("/interviews/{interview_id}/interviewer-cancel")
def interviewer_cancel(
    interview_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _require_interviewer(user)
    svc = SchedulingService(db)
    interview, _request = _wrap(svc.interviewer_cancel, interview_id, user.id)
    return {"interview": interview.model_dump()}


@router.get("/interviewers")
def list_interviewers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_staff(user)
    return [i.model_dump() for i in SchedulingService(db).list_interviewers()]


# --------------------------------------------------------------------------- #
# Shared - notifications inbox
# --------------------------------------------------------------------------- #


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def my_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc = SchedulingService(db)
    records = svc.notifier.for_recipient(user.id, user.email)
    return [
        schemas.NotificationOut(
            id=n.id, kind=n.kind, message=n.message, interview_id=n.interview_id,
            created_at=n.created_at, read=n.read,
        )
        for n in records
    ]
