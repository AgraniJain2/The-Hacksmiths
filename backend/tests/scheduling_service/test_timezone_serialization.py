"""Regression guard: `SchedulingService`'s row<->engine-model conversion must
hand out timezone-*aware* UTC datetimes, never naive ones.

SQLite silently drops `tzinfo` off plain `DateTime` columns on read (verified
directly against `Interview.confirmed_start_utc` while building this test) -
`_row_to_interview`/`_row_to_request` must re-attach it via `ensure_utc()`
before handing values to the Pydantic engine models, or a naive datetime
serializes to JSON with no `Z`/offset and the browser's `new Date(...)`
silently parses it as *local* time instead of UTC (every confirmed interview
time in the UI would then be off by the viewer's own UTC offset).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.session import Base
from app.scheduling.models import AvailabilityWindow
from app.scheduling.service import SchedulingService

UTC = timezone.utc


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_confirmed_interview_and_request_timestamps_are_tz_aware(db):
    svc = SchedulingService(db)
    svc.upsert_interviewer_profile(
        interviewer_id="u-iv1", name="Ivy", email="ivy@example.com", skills=["python"],
        seniority="SENIOR", interview_types=["TECHNICAL_ROUND_1"], timezone_name="UTC",
        working_hours_start="00:00", working_hours_end="23:59", active=True,
    )
    request, _round = svc.create_request(
        owner_user_id="u-rec", owner_email="rec@example.com", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python"], seniority="MID", panelists_required=1,
        duration_minutes=30, buffer_minutes_before=10, buffer_minutes_after=10,
        hiring_manager_email=None, candidate_name="Cara Candidate",
        candidate_email="cara@example.com", candidate_timezone="UTC",
    )
    start = datetime.now(UTC) + timedelta(days=1, hours=1)
    _req2, outcome = svc.submit_availability(
        request.request_id, [AvailabilityWindow(start=start, end=start + timedelta(hours=8))]
    )
    slot = outcome.feasibility.feasible_slots[0]
    svc.select_slot(request.request_id, slot.slot_id)

    # Force a real round-trip through SQLite (not just the in-memory Python
    # objects still attached to this session) - this is exactly the path
    # that used to strip `tzinfo`.
    db.expire_all()

    interview = svc.get_interview_for_request(request.request_id)
    assert interview is not None
    assert interview.slot_start.tzinfo is not None
    assert interview.slot_end.tzinfo is not None
    assert interview.created_at.tzinfo is not None
    assert interview.updated_at.tzinfo is not None

    reloaded_request = svc.get_request(request.request_id)
    assert reloaded_request.created_at.tzinfo is not None


def test_inconsistent_row_returns_no_interview_instead_of_crashing(db):
    """Live bug found in dev.db: a stale/duplicate `submit_availability` call
    landing on a row that already has a panel being assigned (bypassing
    `candidate_reschedule`'s clearing) leaves `seats_json` populated with a
    stale seat while `confirmed_start_utc`/`_end` are `None` and `status` is
    back to a request-level value ("awaiting_candidate_selection") - not a
    valid `InterviewStatus`. This used to raise an uncaught
    `pydantic.ValidationError` out of `_row_to_interview`, 500-ing every GET
    on the request (candidate page, dashboard, request detail) from then on.
    """
    from app.db.models import Interview as InterviewRow
    from app.scheduling.service import _row_to_interview

    row = InterviewRow(
        id="req-broken",
        title="TECHNICAL_ROUND_1 - Test Candidate",
        status="awaiting_candidate_selection",
        created_by="u-rec",
        created_by_email="rec@example.com",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        interview_type="TECHNICAL_ROUND_1",
        required_skills=["python"],
        required_seniority="MID",
        panelists_required=1,
        candidate_name="Test Candidate",
        candidate_email="cara@example.com",
        candidate_timezone="UTC",
        duration_minutes=60,
        buffer_minutes_before=15,
        buffer_minutes_after=15,
        confirmed_start_utc=None,
        confirmed_end_utc=None,
        seats_json=[
            {
                "seat_index": 0,
                "interviewer_id": "u-iv1",
                "status": "offered",
                "declined_interviewer_ids": [],
            }
        ],
    )
    assert _row_to_interview(row) is None

