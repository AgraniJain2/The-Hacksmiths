"""DB-backed :class:`CandidateRepository` / :class:`InterviewerRepository` -
Phase 2's real implementations of the ABCs in ``interfaces.py``, replacing
``mock_repositories.py``'s in-memory versions for the live app (those stay in
place - the pure engine's own tests in ``tests/scheduling/`` are built on
them and don't touch the DB at all).

Mirrors the split in ``mock_repositories.py`` (one file, both repos) since
both are thin reads over the same session.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Interview as InterviewRow
from app.db.models import InterviewerProfile as InterviewerProfileRow

from ..models import Candidate, Interviewer, WorkingHours
from .interfaces import CandidateRepository, InterviewerRepository


class DbCandidateRepository(CandidateRepository):
    """Candidates have no profile table of their own - `DATA_MODEL.md` never
    specified one, since everything the engine needs (name/email/timezone)
    already lives on the `Interview` row that names them. `candidate_id` is
    always the candidate's email (see `service.py`), so this is a lookup by
    `Interview.candidate_email`, most-recent request first.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_candidate(self, candidate_id: str) -> Candidate:
        row = (
            self.db.query(InterviewRow)
            .filter(InterviewRow.candidate_email == candidate_id)
            .order_by(InterviewRow.created_at.desc())
            .first()
        )
        if row is None:
            raise KeyError(f"unknown candidate_id: {candidate_id!r}")
        return Candidate(
            candidate_id=candidate_id,
            name=row.candidate_name or candidate_id,
            email=candidate_id,
            timezone=row.candidate_timezone or "UTC",
        )


def _to_interviewer(row: InterviewerProfileRow) -> Interviewer:
    return Interviewer(
        interviewer_id=row.user_id,
        name=row.name,
        email=row.email,
        timezone=row.timezone,
        skills=list(row.skills or []),
        seniority=row.seniority,  # type: ignore[arg-type]
        interview_types=list(row.qualified_interview_types or []),
        working_hours=WorkingHours(start=row.working_hours_start, end=row.working_hours_end),
        calendar_id=f"cal-{row.user_id}",
        active=bool(row.active),
    )


class DbInterviewerRepository(InterviewerRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_interviewer(self, interviewer_id: str) -> Interviewer:
        row = (
            self.db.query(InterviewerProfileRow)
            .filter(InterviewerProfileRow.user_id == interviewer_id)
            .first()
        )
        if row is None:
            raise KeyError(f"unknown interviewer_id: {interviewer_id!r}")
        return _to_interviewer(row)

    def list_interviewers(self, active_only: bool = False) -> list[Interviewer]:
        query = self.db.query(InterviewerProfileRow)
        if active_only:
            query = query.filter(InterviewerProfileRow.active.is_(True))
        return [_to_interviewer(row) for row in query.all()]
