"""In-memory :class:`InterviewerLoadProvider`.

Two ways to build one:

* ``MockInterviewerLoadProvider({"iv-1": InterviewerLoadSnapshot(...)})`` - hand
  the exact snapshots (most predictable for tests);
* ``MockInterviewerLoadProvider.from_history({"iv-1": [dt, dt, ...]}, window_days=7)``
  - pass confirmed-interview timestamps and let it compute the rolling count and
  last-assigned time relative to ``as_of``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Mapping, Sequence

from ..models import InterviewerLoadSnapshot
from ..timeutils import ensure_utc
from .interfaces import InterviewerLoadProvider


class MockInterviewerLoadProvider(InterviewerLoadProvider):
    def __init__(
        self,
        snapshots: Mapping[str, InterviewerLoadSnapshot] | None = None,
        *,
        history: Mapping[str, Sequence[datetime]] | None = None,
        window_days: int = 7,
    ) -> None:
        self._snapshots: Dict[str, InterviewerLoadSnapshot] = dict(snapshots or {})
        self._history: Dict[str, List[datetime]] = {
            k: sorted(ensure_utc(d) for d in v) for k, v in (history or {}).items()
        }
        self._window_days = window_days

    @classmethod
    def from_history(
        cls, history: Mapping[str, Sequence[datetime]], window_days: int = 7
    ) -> "MockInterviewerLoadProvider":
        return cls(history=history, window_days=window_days)

    def record_assignment(self, interviewer_id: str, when: datetime) -> None:
        self._history.setdefault(interviewer_id, []).append(ensure_utc(when))
        self._history[interviewer_id].sort()

    def get_load_snapshot(self, interviewer_id: str, as_of) -> InterviewerLoadSnapshot:
        if interviewer_id in self._snapshots:
            return self._snapshots[interviewer_id]

        as_of_dt = ensure_utc(as_of) if as_of is not None else datetime.now(timezone.utc)
        cutoff = as_of_dt - timedelta(days=self._window_days)
        stamps = self._history.get(interviewer_id, [])
        in_window = [d for d in stamps if cutoff <= d <= as_of_dt]
        past = [d for d in stamps if d <= as_of_dt]
        return InterviewerLoadSnapshot(
            interviewer_id=interviewer_id,
            rolling_confirmed_count=len(in_window),
            last_assigned_at=max(past) if past else None,
        )
