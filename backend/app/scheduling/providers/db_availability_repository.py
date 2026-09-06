"""DB-backed :class:`AvailabilityRepository` - Phase 2's real implementation,
backed by `CandidateAvailabilityWindow` (DATA_MODEL.md, Module 3).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import CandidateAvailabilityWindow as WindowRow
from app.db.models import Interview as InterviewRow

from ..models import AvailabilityWindow, CandidateAvailability
from .interfaces import AvailabilityRepository

UTC = timezone.utc


class DbAvailabilityRepository(AvailabilityRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_availability(self, request_id: str) -> CandidateAvailability:
        rows = (
            self.db.query(WindowRow)
            .filter(WindowRow.interview_id == request_id)
            .order_by(WindowRow.start_utc)
            .all()
        )
        if not rows:
            raise KeyError(f"no candidate availability submitted for request {request_id!r}")
        interview = self.db.query(InterviewRow).filter(InterviewRow.id == request_id).first()
        return CandidateAvailability(
            request_id=request_id,
            candidate_id=(interview.candidate_email if interview else "") or "",
            windows=[
                AvailabilityWindow(start=r.start_utc, end=r.end_utc, source_timezone=r.source_timezone)
                for r in rows
            ],
            submitted_at=datetime.now(UTC),
        )

    def save_availability(self, availability: CandidateAvailability) -> None:
        # Replace, don't append - a candidate resubmitting after already
        # picking a slot shouldn't leave stale windows behind (MODULE_GUIDE.md
        # Module 3's edge case). Caller (service.py) commits the transaction.
        self.db.query(WindowRow).filter(
            WindowRow.interview_id == availability.request_id
        ).delete(synchronize_session=False)
        for w in availability.windows:
            self.db.add(
                WindowRow(
                    interview_id=availability.request_id,
                    start_utc=w.start,
                    end_utc=w.end,
                    source_timezone=w.source_timezone,
                )
            )
        self.db.flush()
