from __future__ import annotations

from datetime import datetime, timezone

from app.scheduling.assignment import rank_interviewers
from app.scheduling.models import InterviewerLoadSnapshot
from app.scheduling.providers import MockInterviewerLoadProvider

UTC = timezone.utc
AS_OF = datetime(2026, 9, 1, tzinfo=UTC)


def test_rank_by_rolling_load_then_round_robin():
    provider = MockInterviewerLoadProvider(
        {
            "a": InterviewerLoadSnapshot(interviewer_id="a", rolling_confirmed_count=2, last_assigned_at=datetime(2026, 8, 30, tzinfo=UTC)),
            "b": InterviewerLoadSnapshot(interviewer_id="b", rolling_confirmed_count=0, last_assigned_at=datetime(2026, 8, 20, tzinfo=UTC)),
            "c": InterviewerLoadSnapshot(interviewer_id="c", rolling_confirmed_count=0, last_assigned_at=None),
            "d": InterviewerLoadSnapshot(interviewer_id="d", rolling_confirmed_count=0, last_assigned_at=datetime(2026, 8, 25, tzinfo=UTC)),
        }
    )
    # count asc first (b/c/d all 0, a is 2 -> last); within the 0s, never-assigned
    # (c) first, then least-recently-assigned (b before d).
    assert rank_interviewers(["a", "b", "c", "d"], provider, AS_OF) == ["c", "b", "d", "a"]


def test_rank_excludes_ids():
    provider = MockInterviewerLoadProvider(
        {k: InterviewerLoadSnapshot(interviewer_id=k, rolling_confirmed_count=0) for k in "abc"}
    )
    assert rank_interviewers(["a", "b", "c"], provider, AS_OF, exclude={"b"}) == ["a", "c"]


def test_from_history_counts_rolling_window():
    provider = MockInterviewerLoadProvider.from_history(
        {
            "a": [datetime(2026, 8, 20, tzinfo=UTC), datetime(2026, 8, 29, tzinfo=UTC), datetime(2026, 8, 31, tzinfo=UTC)],
        },
        window_days=7,
    )
    snap = provider.get_load_snapshot("a", AS_OF)
    # only 08-29 and 08-31 fall within the trailing 7 days of 09-01
    assert snap.rolling_confirmed_count == 2
    assert snap.last_assigned_at == datetime(2026, 8, 31, tzinfo=UTC)
