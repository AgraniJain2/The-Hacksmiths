"""HTTP surface for the scheduling engine - workflow stages 2, 2B, 3, 4, 5, 6, 8.

Thin glue only: every scheduling decision (feasibility, ranking, cascade,
cancel/reschedule) is made by the pure engine in this package; this file's
job is auth/RBAC, translating HTTP bodies to/from the engine's Pydantic
models, and the one place this demo touches the real DB - creating an
``Interview`` stub row + ``InviteToken`` so a candidate can authenticate
against their request through the *existing* invite-link mechanism (see
AUTH_MODULE.md) rather than a second, parallel one.

State itself (requests, interviews, the interviewer directory) lives in
``store.py``'s in-memory ``SchedulingStore`` - see that module's docstring
for why: there's no DB table for any of this yet (Module 2/2B/3's own
schema from DATA_MODEL.md isn't built), and the engine's own design only
ever talks to provider ABCs, never a URL or a DB row directly.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.security import hash_invite_token
from app.db.models import Interview as InterviewRow
from app.db.models import InviteToken, User
from app.db.session import get_db

from . import schemas
from .models import AvailabilityWindow
from .store import ForbiddenError, NotFoundError, SchedulingStore, get_store

router = APIRouter(prefix="/scheduling", tags=["scheduling"])

STAFF_ROLES = ("recruiter", "hiring_manager")


def _store() -> SchedulingStore:
    return get_store()


def _wrap(fn, *args, **kwargs):
    """Translate the store's plain exceptions into the right HTTP status."""
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


def _detail(store: SchedulingStore, request_id: str) -> schemas.RequestDetail:
    request = _wrap(store.get_request, request_id)
    round_ = store.get_round(request_id)
    return schemas.RequestDetail(
        request=request,
        round=round_,
        feasibility=store.feasibility.get(request_id),
        interview=store.get_interview_for_request(request_id),
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
    store = _store()

    request, round_ = store.create_request(
        owner_user_id=user.id,
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
    # instead of building a second one: the SQLAlchemy Interview row shares
    # its id with the engine's request_id, so a candidate's session (once
    # they use this link) always resolves back to the right in-memory request.
    db.add(
        InterviewRow(
            id=request.request_id,
            title=f"{body.interview_type} - {body.candidate_name}",
            status="collecting_availability",
            created_by=user.id,
        )
    )
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
    return schemas.CreateRequestResponse(request=request, round=round_, invite_link=invite_link)


@router.get("/requests", response_model=list[schemas.RequestDetail])
def list_requests(user: User = Depends(get_current_user)):
    _require_staff(user)
    store = _store()
    return [_detail(store, r.request_id) for r in store.list_requests()]


@router.get("/requests/{request_id}", response_model=schemas.RequestDetail)
def get_request_detail(request_id: str, user: User = Depends(get_current_user)):
    store = _store()
    detail = _detail(store, request_id)
    is_owner_candidate = user.role == "candidate" and user.email.lower() == detail.request.candidate_id.lower()
    if user.role not in STAFF_ROLES and not is_owner_candidate:
        raise HTTPException(status_code=403, detail="insufficient_role")
    return detail


# --------------------------------------------------------------------------- #
# Candidate side - stages 3 & 5
# --------------------------------------------------------------------------- #


def _require_candidate_owns(user: User, store: SchedulingStore, request_id: str):
    request = _wrap(store.get_request, request_id)
    if user.role != "candidate" or user.email.lower() != request.candidate_id.lower():
        raise HTTPException(status_code=403, detail="not_your_interview")
    return request


@router.get("/my-request", response_model=schemas.RequestDetail | None)
def my_request(user: User = Depends(get_current_user)):
    if user.role != "candidate":
        raise HTTPException(status_code=403, detail="insufficient_role")
    store = _store()
    request = store.find_request_by_candidate_email(user.email)
    if request is None:
        return None
    return _detail(store, request.request_id)


@router.post("/requests/{request_id}/availability", response_model=schemas.RequestDetail)
def submit_availability(
    request_id: str, body: schemas.SubmitAvailabilityBody, user: User = Depends(get_current_user)
):
    store = _store()
    _require_candidate_owns(user, store, request_id)
    windows = [
        AvailabilityWindow(start=w.start, end=w.end, source_timezone=w.source_timezone)
        for w in body.windows
    ]
    _wrap(store.submit_availability, request_id, windows)
    return _detail(store, request_id)


@router.post("/requests/{request_id}/select-slot", response_model=schemas.RequestDetail)
def select_slot(request_id: str, body: schemas.SelectSlotBody, user: User = Depends(get_current_user)):
    store = _store()
    _require_candidate_owns(user, store, request_id)
    _wrap(store.select_slot, request_id, body.slot_id)
    return _detail(store, request_id)


@router.post("/requests/{request_id}/cancel", response_model=schemas.RequestDetail)
def cancel_request(request_id: str, user: User = Depends(get_current_user)):
    store = _store()
    _require_candidate_owns(user, store, request_id)
    _wrap(store.candidate_cancel, request_id)
    return _detail(store, request_id)


# --------------------------------------------------------------------------- #
# Interviewer side - Module 2B (in-memory) + stages 6 & 8
# --------------------------------------------------------------------------- #


def _require_interviewer(user: User) -> None:
    if user.role != "interviewer":
        raise HTTPException(status_code=403, detail="insufficient_role")


@router.get("/interviewer/profile")
def get_my_profile(user: User = Depends(get_current_user)):
    _require_interviewer(user)
    store = _store()
    profile = store.get_interviewer_profile(user.id)
    return profile.model_dump() if profile else None


@router.put("/interviewer/profile")
def upsert_my_profile(body: schemas.InterviewerProfileBody, user: User = Depends(get_current_user)):
    _require_interviewer(user)
    store = _store()
    profile = store.upsert_interviewer_profile(
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
def my_offers(user: User = Depends(get_current_user)):
    _require_interviewer(user)
    store = _store()
    return [
        schemas.OfferOut(interview=interview, seat_index=seat.seat_index)
        for interview, seat in store.list_offers_for_interviewer(user.id)
    ]


@router.post("/interviews/{interview_id}/seats/{seat_index}/respond", response_model=schemas.OfferOut)
def respond_to_seat(
    interview_id: str,
    seat_index: int,
    body: schemas.SeatResponseBody,
    user: User = Depends(get_current_user),
):
    _require_interviewer(user)
    store = _store()
    interview, _request = _wrap(
        store.respond_to_seat,
        interview_id,
        seat_index,
        accept=body.accept,
        actor_interviewer_id=user.id,
    )
    return schemas.OfferOut(interview=interview, seat_index=seat_index)


@router.post("/interviews/{interview_id}/interviewer-cancel")
def interviewer_cancel(interview_id: str, user: User = Depends(get_current_user)):
    _require_interviewer(user)
    store = _store()
    interview, _request = _wrap(store.interviewer_cancel, interview_id, user.id)
    return {"interview": interview.model_dump()}


@router.get("/interviewers")
def list_interviewers(user: User = Depends(get_current_user)):
    _require_staff(user)
    return [i.model_dump() for i in _store().list_interviewers()]


# --------------------------------------------------------------------------- #
# Shared - notifications inbox
# --------------------------------------------------------------------------- #


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def my_notifications(user: User = Depends(get_current_user)):
    store = _store()
    records = store.notifier.for_recipient(user.id, user.email)
    return [
        schemas.NotificationOut(
            id=n.id, kind=n.kind, message=n.message, interview_id=n.interview_id,
            created_at=n.created_at, read=n.read,
        )
        for n in records
    ]
