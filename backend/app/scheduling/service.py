"""DB-backed scheduling service - Phase 2 (Documentation/IMPLEMENTATION_PLAN.md).

Replaces ``store.py``'s in-memory ``SchedulingStore``: same public method
surface (so ``router.py`` barely changes), real persistence underneath. One
``Interview`` DB row spans the whole lifecycle of a request - `request_id`,
its `Round` fields, its `FeasibilityResult` cache, and (once the candidate
picks a slot) its booked `Interview` state all live on that single row, per
DATA_MODEL.md's own design (there was never a separate `Round`/`Booking`
table). See ``app/db/models.py``'s `Interview` docstring for the handful of
deliberate departures from DATA_MODEL.md's literal column list.

``Interview.interview_id`` (the engine's own booking identifier) is always
forced to equal the row's primary key (== `request_id`) immediately after the
engine mints one (see :func:`_finalize_interview_id`) - the engine generates
its own random id internally (``state_machine.create_interview``, untouched
pure code), but every FK in this schema (`InterviewSlotOffer.interview_id`,
`InterviewParticipant.interview_id`) needs to resolve back to `interviews.id`,
so this collapses the two identifiers rather than tracking a translation
table for no benefit.

``CalendarProvider`` stays mocked this phase (Phase 3, not this one) -
`MockCalendarProvider` never has any interviewer's busy times configured
here, same as ``store.py`` before it, so everyone reads as calendar-free;
working hours + skills/seniority are what actually filter people today.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import Interview as InterviewRow
from app.db.models import InterviewerProfile as InterviewerProfileRow
from app.db.models import InterviewParticipant
from app.db.models import InterviewSlotOffer
from app.db.models import User as UserRow
from app.notifications.provider import ResendNotificationProvider

from .assignment import AssignmentOutcome, PanelAssignmentAgent
from .config import SchedulingConfig
from .escalation import escalate_to_manual_scheduling
from .feasibility import feasible_interviewers_at_fixed_time
from .models import (
    AvailabilityWindow,
    CandidateAvailability,
    FeasibilityResult,
    Interview,
    InterviewRequest,
    InterviewSeat,
    Round,
    WorkingHours,
)
from .pipeline import FeasibilityOutcome, find_feasible_slots
from .pool import resolve_interviewer_pool
from .providers.db_availability_repository import DbAvailabilityRepository
from .providers.db_interviewer_load_provider import DbInterviewerLoadProvider
from .providers.db_reservation_ledger import DbReservationLedger
from .providers.db_repositories import DbCandidateRepository, DbInterviewerRepository
from .providers.mock_calendar_provider import MockCalendarProvider
from .state_machine import InterviewStateMachine

UTC = timezone.utc


class NotFoundError(KeyError):
    """A request/interview id that doesn't exist in the DB."""


class ForbiddenError(Exception):
    """The caller isn't the owner of the resource they're acting on."""


# --------------------------------------------------------------------------- #
# Row <-> engine Pydantic model conversion
# --------------------------------------------------------------------------- #


def _row_to_request(row: InterviewRow) -> InterviewRequest:
    return InterviewRequest(
        request_id=row.id,
        candidate_id=row.candidate_email or "",
        interview_type=row.interview_type or "",
        required_skills=list(row.required_skills or []),
        seniority=row.required_seniority or "MID",  # type: ignore[arg-type]
        panelists_required=row.panelists_required or 1,
        hiring_manager_email=row.hiring_manager_email,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
    )


def _row_to_round(row: InterviewRow) -> Round:
    return Round(
        round_id=f"round-{row.id}",
        interview_type=row.interview_type or "",
        duration_minutes=row.duration_minutes or 60,
        buffer_minutes_before=row.buffer_minutes_before or 0,
        buffer_minutes_after=row.buffer_minutes_after or 0,
        default_working_hours=WorkingHours(start="09:00", end="18:00"),
    )


def _row_to_interview(row: InterviewRow) -> Optional[Interview]:
    if not row.seats_json:
        return None
    seats = [InterviewSeat(**s) for s in row.seats_json]
    return Interview(
        interview_id=row.id,
        request_id=row.id,
        candidate_id=row.candidate_email or "",
        interview_type=row.interview_type or "",
        hiring_manager_email=row.hiring_manager_email,
        slot_start=row.confirmed_start_utc,
        slot_end=row.confirmed_end_utc,
        seats=seats,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at or row.created_at,
        calendar_event_id=row.calendar_event_id,
        meet_link=row.meeting_link,
    )


def _persist_interview(row: InterviewRow, interview: Interview, request: InterviewRequest) -> None:
    """Write an engine outcome back onto its row. Both `interview.status` and
    `request.status` are the same column here (one row, whole lifecycle) -
    the interview's is authoritative once it exists."""

    row.status = interview.status
    row.confirmed_start_utc = interview.slot_start
    row.confirmed_end_utc = interview.slot_end
    row.seats_json = [s.model_dump(mode="json") for s in interview.seats]
    row.updated_at = interview.updated_at
    row.calendar_event_id = interview.calendar_event_id
    row.meeting_link = interview.meet_link


def _finalize_interview_id(interview: Interview, request_id: str) -> Interview:
    """Force the engine's freshly-minted interview_id to equal the row's own
    id (== request_id) - see the module docstring."""
    if interview.interview_id == request_id:
        return interview
    return interview.model_copy(update={"interview_id": request_id})


class SchedulingService:
    """One instance per request (built fresh in ``router.py`` via
    ``Depends`` - no process-global singleton, unlike ``store.py``'s
    ``get_store()``, since state now lives in the DB, not in this object)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.candidate_repo = DbCandidateRepository(db)
        self.interviewer_repo = DbInterviewerRepository(db)
        self.availability_repo = DbAvailabilityRepository(db)
        self.calendar = MockCalendarProvider()
        self.reservations = DbReservationLedger(db)
        self.load_provider = DbInterviewerLoadProvider(db)
        self.notifier = ResendNotificationProvider(
            self.interviewer_repo, self._resolve_recruiter_email, self._resolve_recruiter_identity
        )
        self.config = SchedulingConfig()

    # -- recruiter identity resolution (for ResendNotificationProvider) ------

    def _resolve_recruiter_email(self, request_id: str) -> Optional[str]:
        row = self.db.query(InterviewRow).filter(InterviewRow.id == request_id).first()
        return row.created_by_email if row else None

    def _resolve_recruiter_identity(self, request_id: str) -> Optional[str]:
        row = self.db.query(InterviewRow).filter(InterviewRow.id == request_id).first()
        return row.created_by if row else None

    # -- row lookups ----------------------------------------------------------

    def _get_row(self, request_id: str) -> InterviewRow:
        row = self.db.query(InterviewRow).filter(InterviewRow.id == request_id).first()
        if row is None:
            raise NotFoundError(f"no interview request {request_id!r}")
        return row

    # -- requests ------------------------------------------------------------

    def create_request(
        self,
        *,
        owner_user_id: str,
        owner_email: str,
        interview_type: str,
        required_skills: List[str],
        seniority: str,
        panelists_required: int,
        duration_minutes: int,
        buffer_minutes_before: int,
        buffer_minutes_after: int,
        hiring_manager_email: Optional[str],
        candidate_name: str,
        candidate_email: str,
        candidate_timezone: str,
    ) -> Tuple[InterviewRequest, Round]:
        request_id = f"req-{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        row = InterviewRow(
            id=request_id,
            title=f"{interview_type} - {candidate_name}",
            status="collecting_availability",
            created_by=owner_user_id,
            created_by_email=owner_email,
            created_at=now,
            updated_at=now,
            interview_type=interview_type,
            required_skills=list(required_skills),
            required_seniority=seniority,
            panelists_required=panelists_required,
            hiring_manager_email=hiring_manager_email,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            candidate_timezone=candidate_timezone,
            duration_minutes=duration_minutes,
            buffer_minutes_before=buffer_minutes_before,
            buffer_minutes_after=buffer_minutes_after,
        )
        self.db.add(row)
        self.db.commit()
        return _row_to_request(row), _row_to_round(row)

    def list_requests(self) -> List[InterviewRequest]:
        rows = (
            self.db.query(InterviewRow)
            .filter(InterviewRow.interview_type.isnot(None))
            .order_by(InterviewRow.created_at.desc())
            .all()
        )
        return [_row_to_request(r) for r in rows]

    def get_request(self, request_id: str) -> InterviewRequest:
        return _row_to_request(self._get_row(request_id))

    def get_round(self, request_id: str) -> Round:
        return _row_to_round(self._get_row(request_id))

    def get_feasibility(self, request_id: str) -> Optional[FeasibilityResult]:
        row = self._get_row(request_id)
        if not row.feasibility_json:
            return None
        return FeasibilityResult.model_validate(row.feasibility_json)

    def find_request_by_candidate_email(self, email: str) -> Optional[InterviewRequest]:
        row = (
            self.db.query(InterviewRow)
            .filter(InterviewRow.candidate_email.isnot(None))
            .filter(InterviewRow.candidate_email.ilike(email))
            .order_by(InterviewRow.created_at.desc())
            .first()
        )
        return _row_to_request(row) if row else None

    def get_interview_for_request(self, request_id: str) -> Optional[Interview]:
        row = self.db.query(InterviewRow).filter(InterviewRow.id == request_id).first()
        return _row_to_interview(row) if row else None

    def get_interview(self, interview_id: str) -> Interview:
        row = self._get_row(interview_id)
        interview = _row_to_interview(row)
        if interview is None:
            raise NotFoundError(f"no interview {interview_id!r}")
        return interview

    # -- availability + feasibility (step 3 -> 4) -----------------------------

    def submit_availability(
        self, request_id: str, windows: List[AvailabilityWindow]
    ) -> Tuple[InterviewRequest, FeasibilityOutcome]:
        row = self._get_row(request_id)
        request = _row_to_request(row)
        round_ = _row_to_round(row)
        try:
            self.availability_repo.save_availability(
                CandidateAvailability(
                    request_id=request_id,
                    candidate_id=request.candidate_id,
                    windows=windows,
                    submitted_at=datetime.now(UTC),
                )
            )
            outcome = find_feasible_slots(
                request,
                round_,
                interviewer_repo=self.interviewer_repo,
                availability_repo=self.availability_repo,
                calendar=self.calendar,
                notifier=self.notifier,
                config=self.config,
            )
            row.status = outcome.request.status
            row.feasibility_json = outcome.feasibility.model_dump(mode="json")
            row.updated_at = datetime.now(UTC)
            self.db.commit()
            return outcome.request, outcome
        except Exception:
            self.db.rollback()
            raise

    # -- slot selection + panel assignment (step 5 -> 6) ----------------------

    def select_slot(self, request_id: str, slot_id: str) -> Tuple[InterviewRequest, Interview]:
        """Inlines `pipeline.assign_panel`'s orchestration rather than calling
        it directly, for one reason: `sm.create_interview(...)` mints a fresh
        random `interview_id` internally, and `sm.assign_panel(...)` (called
        right after, still inside `pipeline.assign_panel`) immediately uses
        that id to create `InterviewSlotOffer` rows via the reservation
        ledger - by the time `pipeline.assign_panel` *returns*, those rows
        would already be written with the wrong id. Forcing
        `interview_id = request_id` has to happen *between* those two calls,
        which means owning both calls here instead of through the wrapper.
        Every other primitive (pool resolution, live feasibility, the state
        machine) is the exact same call `pipeline.assign_panel` makes."""
        row = self._get_row(request_id)
        request = _row_to_request(row)
        round_ = _row_to_round(row)
        feasibility = self.get_feasibility(request_id)
        if feasibility is None:
            raise ValueError("feasibility has not been computed for this request yet")

        chosen = next((s for s in feasibility.feasible_slots if s.slot_id == slot_id), None)
        if chosen is None:
            raise ValueError(f"chosen_slot_id {slot_id!r} is not in the feasible set")

        try:
            pool_result = resolve_interviewer_pool(
                request, self.interviewer_repo.list_interviewers(active_only=True), self.config.pool_policy
            )
            fixed_feasible = feasible_interviewers_at_fixed_time(
                request, round_, pool_result, chosen.start, chosen.end, self.calendar, self.reservations
            )

            sm = self._state_machine()
            interview = sm.create_interview(request, chosen, round_)
            interview = _finalize_interview_id(interview, request_id)  # see docstring above

            if len(fixed_feasible) < request.panelists_required:
                reason = (
                    f"chosen slot {chosen.start.isoformat()} no longer has "
                    f"{request.panelists_required} feasible interviewer(s) on live recompute "
                    f"(only {len(fixed_feasible)}) - calendars/reservations changed since selection"
                )
                updated_request = escalate_to_manual_scheduling(request, reason, self.notifier)
                interview = interview.model_copy(update={"status": "manual_scheduling_required"})
                _persist_interview(row, interview, updated_request)
                self.db.commit()
                return _row_to_request(row), _row_to_interview(row)

            outcome: AssignmentOutcome = sm.assign_panel(
                interview=interview, request=request, round_=round_, feasible_ids_at_slot=fixed_feasible
            )
            _persist_interview(row, outcome.interview, outcome.request)
            self._sync_accepted_seats(row, outcome.interview)
            self._create_hiring_manager_participant(row)
            self.db.commit()
            return _row_to_request(row), _row_to_interview(row)
        except Exception:
            self.db.rollback()
            raise

    # -- seat responses + interviewer cancel (step 6 continued, step 8) ------

    def respond_to_seat(
        self, interview_id: str, seat_index: int, *, accept: bool, actor_interviewer_id: str
    ) -> Tuple[Interview, InterviewRequest]:
        row = self._get_row(interview_id)
        interview = _row_to_interview(row)
        if interview is None:
            raise NotFoundError(f"no interview {interview_id!r}")
        request = _row_to_request(row)
        round_ = _row_to_round(row)

        if not (0 <= seat_index < len(interview.seats)):
            raise ValueError(f"interview has no seat {seat_index}")
        seat = interview.seats[seat_index]
        if seat.interviewer_id != actor_interviewer_id:
            raise ForbiddenError("this offer wasn't made to you")
        if seat.status != "offered":
            raise ValueError(f"seat {seat_index} is {seat.status!r}, not awaiting a response")

        try:
            feasible_now = self._feasible_now(request, round_, interview)
            sm = self._state_machine()
            outcome: AssignmentOutcome = sm.respond_to_seat(
                interview=interview,
                request=request,
                round_=round_,
                seat_index=seat_index,
                accepted=accept,
                feasible_ids_at_slot=feasible_now,
            )
            _persist_interview(row, outcome.interview, outcome.request)
            if accept:
                self._mark_offer_and_confirm(row, seat_index, actor_interviewer_id, outcome.interview)
            self._sync_accepted_seats(row, outcome.interview)
            self.db.commit()
            return _row_to_interview(row), _row_to_request(row)
        except Exception:
            self.db.rollback()
            raise

    def interviewer_cancel(self, interview_id: str, interviewer_id: str) -> Tuple[Interview, InterviewRequest]:
        row = self._get_row(interview_id)
        interview = _row_to_interview(row)
        if interview is None:
            raise NotFoundError(f"no interview {interview_id!r}")
        request = _row_to_request(row)
        round_ = _row_to_round(row)

        try:
            # Cancel the confirmed roster row *before* the engine re-cascades
            # this seat - its `is_free()` checks (for other candidates on
            # this same seat, and for any *other* interview's concurrent
            # cascade) must see this interviewer as free again immediately,
            # not after the fact.
            (
                self.db.query(InterviewParticipant)
                .filter(
                    InterviewParticipant.interview_id == interview_id,
                    InterviewParticipant.user_id == interviewer_id,
                    InterviewParticipant.role == "panelist",
                    InterviewParticipant.status == "confirmed",
                )
                .update({"status": "cancelled"}, synchronize_session=False)
            )
            self.db.flush()

            feasible_now = self._feasible_now(request, round_, interview)
            sm = self._state_machine()
            outcome: AssignmentOutcome = sm.interviewer_cancel(
                interview=interview,
                request=request,
                round_=round_,
                interviewer_id=interviewer_id,
                feasible_ids_at_slot=feasible_now,
            )
            _persist_interview(row, outcome.interview, outcome.request)
            self._sync_accepted_seats(row, outcome.interview)
            self.db.commit()
            return _row_to_interview(row), _row_to_request(row)
        except Exception:
            self.db.rollback()
            raise

    def candidate_cancel(self, request_id: str, reason: str = "candidate cancelled") -> InterviewRequest:
        row = self._get_row(request_id)
        try:
            interview = _row_to_interview(row)
            if interview is not None and interview.status != "cancelled":
                sm = self._state_machine()
                cancelled = sm.candidate_cancel(interview, reason=reason)
                _persist_interview(row, cancelled, _row_to_request(row))
            row.status = "cancelled"
            row.updated_at = datetime.now(UTC)
            self.db.commit()
            return _row_to_request(row)
        except Exception:
            self.db.rollback()
            raise

    # -- internal helpers -------------------------------------------------

    def _feasible_now(self, request: InterviewRequest, round_: Round, interview: Interview) -> List[str]:
        pool_result = resolve_interviewer_pool(
            request, self.interviewer_repo.list_interviewers(active_only=True), self.config.pool_policy
        )
        return feasible_interviewers_at_fixed_time(
            request, round_, pool_result, interview.slot_start, interview.slot_end,
            self.calendar, self.reservations,
        )

    def _state_machine(self) -> InterviewStateMachine:
        agent = PanelAssignmentAgent(
            load_provider=self.load_provider,
            reservations=self.reservations,
            notifier=self.notifier,
            config=self.config,
        )
        return InterviewStateMachine(self.reservations, self.notifier, agent)

    def _mark_offer_and_confirm(
        self, row: InterviewRow, seat_index: int, interviewer_id: str, interview: Interview
    ) -> None:
        """On acceptance: flip the InterviewSlotOffer row ACCEPTED and insert
        the confirmed InterviewParticipant roster row (DATA_MODEL.md) -
        the engine's own reservations hook is never called on accept (the
        reservation is meant to persist through acceptance), so this is the
        one place that has to happen explicitly."""
        offer = (
            self.db.query(InterviewSlotOffer)
            .filter(
                InterviewSlotOffer.interview_id == row.id,
                InterviewSlotOffer.seat_index == seat_index,
                InterviewSlotOffer.interviewer_user_id == interviewer_id,
                InterviewSlotOffer.status == "OFFERED",
            )
            .order_by(InterviewSlotOffer.offered_at.desc())
            .first()
        )
        if offer is not None:
            offer.status = "ACCEPTED"
            offer.responded_at = datetime.now(UTC)

        self.db.add(
            InterviewParticipant(
                interview_id=row.id,
                user_id=interviewer_id,
                role="panelist",
                seat_index=seat_index,
                status="confirmed",
                created_at=datetime.now(UTC),
            )
        )
        self.db.flush()

    def _sync_accepted_seats(self, row: InterviewRow, interview: Interview) -> None:
        """Belt-and-suspenders: make sure every seat the engine currently
        reports as ``accepted`` has a matching confirmed InterviewParticipant
        row, in case a caller reaches this via a path that didn't already
        create one explicitly (e.g. the initial parallel offer somehow
        resolving straight to accepted - doesn't happen today, but cheap
        insurance against the load provider silently under-counting)."""
        for seat in interview.seats:
            if seat.status != "accepted" or not seat.interviewer_id:
                continue
            exists = (
                self.db.query(InterviewParticipant)
                .filter(
                    InterviewParticipant.interview_id == row.id,
                    InterviewParticipant.seat_index == seat.seat_index,
                    InterviewParticipant.user_id == seat.interviewer_id,
                    InterviewParticipant.status == "confirmed",
                )
                .first()
            )
            if exists is None:
                self.db.add(
                    InterviewParticipant(
                        interview_id=row.id,
                        user_id=seat.interviewer_id,
                        role="panelist",
                        seat_index=seat.seat_index,
                        status="confirmed",
                        created_at=seat.responded_at or datetime.now(UTC),
                    )
                )
        self.db.flush()

    def _create_hiring_manager_participant(self, row: InterviewRow) -> None:
        """Best-effort - only if the named hiring manager already has a
        `User` row (they may never have logged in yet). Not required for any
        scheduling decision (load/ranking queries filter role='panelist'),
        just roster completeness per DATA_MODEL.md."""
        if not row.hiring_manager_email:
            return
        user = self.db.query(UserRow).filter(UserRow.email == row.hiring_manager_email).first()
        if user is None:
            return
        exists = (
            self.db.query(InterviewParticipant)
            .filter(InterviewParticipant.interview_id == row.id, InterviewParticipant.role == "hiring_manager")
            .first()
        )
        if exists is None:
            self.db.add(
                InterviewParticipant(
                    interview_id=row.id,
                    user_id=user.id,
                    role="hiring_manager",
                    status="confirmed",
                    created_at=datetime.now(UTC),
                )
            )
            self.db.flush()

    # -- interviewer directory (Module 2B) ------------------------------------

    def upsert_interviewer_profile(
        self,
        *,
        interviewer_id: str,
        name: str,
        email: str,
        skills: List[str],
        seniority: str,
        interview_types: List[str],
        timezone_name: str,
        working_hours_start: str,
        working_hours_end: str,
        active: bool,
    ):
        row = (
            self.db.query(InterviewerProfileRow)
            .filter(InterviewerProfileRow.user_id == interviewer_id)
            .first()
        )
        if row is None:
            row = InterviewerProfileRow(user_id=interviewer_id)
            self.db.add(row)
        row.name = name
        row.email = email
        row.skills = list(skills)
        row.seniority = seniority
        row.qualified_interview_types = list(interview_types)
        row.timezone = timezone_name
        row.working_hours_start = working_hours_start
        row.working_hours_end = working_hours_end
        row.active = active
        row.updated_at = datetime.now(UTC)
        self.db.commit()
        return self.interviewer_repo.get_interviewer(interviewer_id)

    def get_interviewer_profile(self, interviewer_id: str):
        try:
            return self.interviewer_repo.get_interviewer(interviewer_id)
        except KeyError:
            return None

    def list_interviewers(self):
        return self.interviewer_repo.list_interviewers()

    def list_offers_for_interviewer(self, interviewer_id: str) -> List[Tuple[Interview, InterviewSeat]]:
        rows = (
            self.db.query(InterviewRow)
            .filter(InterviewRow.seats_json.isnot(None))
            .order_by(InterviewRow.confirmed_start_utc)
            .all()
        )
        out: List[Tuple[Interview, InterviewSeat]] = []
        for row in rows:
            interview = _row_to_interview(row)
            if interview is None:
                continue
            for seat in interview.seats:
                if seat.interviewer_id == interviewer_id and seat.status in ("offered", "accepted"):
                    out.append((interview, seat))
        return out
