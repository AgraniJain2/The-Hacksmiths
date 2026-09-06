"""DB-backed :class:`InterviewerLoadProvider` - the two live-computed
queries DATA_MODEL.md specifies for `InterviewerProfile` (rolling 7-day
confirmed count, last-assigned time), read from `InterviewParticipant`
(`role='panelist'`, `status='confirmed'`) instead of a stored counter - a
cancellation flipping that row's status is what makes both queries
self-correct with no extra code, exactly per DATA_MODEL.md's reasoning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import InterviewParticipant

from ..models import InterviewerLoadSnapshot
from ..timeutils import ensure_utc
from .interfaces import InterviewerLoadProvider

UTC = timezone.utc


class DbInterviewerLoadProvider(InterviewerLoadProvider):
    def __init__(self, db: Session, window_days: int = 7) -> None:
        self.db = db
        self._window_days = window_days

    def get_load_snapshot(self, interviewer_id: str, as_of: Optional[datetime]) -> InterviewerLoadSnapshot:
        as_of_dt = ensure_utc(as_of) if as_of is not None else datetime.now(UTC)
        cutoff = as_of_dt - timedelta(days=self._window_days)

        confirmed = (
            self.db.query(InterviewParticipant)
            .filter(
                InterviewParticipant.user_id == interviewer_id,
                InterviewParticipant.role == "panelist",
                InterviewParticipant.status == "confirmed",
            )
            .all()
        )
        stamps = [ensure_utc(p.created_at) for p in confirmed if p.created_at is not None]
        in_window = [d for d in stamps if cutoff <= d <= as_of_dt]
        past = [d for d in stamps if d <= as_of_dt]
        return InterviewerLoadSnapshot(
            interviewer_id=interviewer_id,
            rolling_confirmed_count=len(in_window),
            last_assigned_at=max(past) if past else None,
        )
