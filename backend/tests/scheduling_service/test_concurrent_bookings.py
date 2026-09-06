"""Phase 6 - concurrency validation at the *application* level (not just the
raw ledger, which `test_reservation_concurrency.py` already covers): two
different interview requests, each wanting exactly one panelist, both
ranking the same two-person pool for the same overlapping time, both calling
`select_slot` at nearly the same instant. Confirms the whole
`SchedulingService.select_slot` -> pure engine -> `DbReservationLedger`
path - not just `reserve()` in isolation - can't double-book someone across
two independent request flows, per ARCHITECTURE.md's "one remaining race"
and Documentation/IMPLEMENTATION_PLAN.md Phase 6.

Real file-based SQLite (not `:memory:` - see test_reservation_concurrency.py
for why), real threads, one `SchedulingService` per thread (each with its
own DB session/connection, exactly like two concurrent HTTP requests would
each get their own session via `Depends(get_db)`).
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.session import Base
from app.scheduling.models import AvailabilityWindow, FreeBusyResponse
from app.scheduling.providers.google_calendar_provider import GoogleCalendarProvider
from app.scheduling.service import SchedulingService

UTC = timezone.utc


def _always_free(self, owner_id, owner_type, time_range):
    return FreeBusyResponse(owner_id=owner_id, owner_type=owner_type, timezone="UTC", busy=[], queried_range=time_range)


@pytest.fixture
def file_db(monkeypatch):
    # Same "always free" stub tests/conftest.py's autouse fixture applies -
    # this test cares about the reservation race, not real Google tokens.
    monkeypatch.setattr(GoogleCalendarProvider, "get_free_busy", _always_free)

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = sa.create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    seed_svc = SchedulingService(seed)
    for iid in ("u-iv1", "u-iv2"):
        seed_svc.upsert_interviewer_profile(
            interviewer_id=iid, name=iid, email=f"{iid}@example.com", skills=["python"],
            seniority="SENIOR", interview_types=["TECHNICAL_ROUND_1"], timezone_name="UTC",
            working_hours_start="00:00", working_hours_end="23:59", active=True,
        )
    seed.close()

    try:
        yield Session
    finally:
        engine.dispose()
        os.remove(path)


def test_two_concurrent_requests_cannot_double_book_the_same_top_ranked_interviewer(file_db):
    Session = file_db
    start = datetime.now(UTC) + timedelta(days=1, hours=1)
    window = AvailabilityWindow(start=start, end=start + timedelta(hours=4))

    # Both requests set up (created + availability submitted + slot picked)
    # *before* the concurrent part - only the final select_slot race matters.
    request_ids = []
    slot_ids = []
    for name in ("Cara A", "Cara B"):
        db = Session()
        svc = SchedulingService(db)
        request, _round = svc.create_request(
            owner_user_id="u-rec", owner_email="rec@example.com", interview_type="TECHNICAL_ROUND_1",
            required_skills=["python"], seniority="MID", panelists_required=1,
            duration_minutes=30, buffer_minutes_before=10, buffer_minutes_after=10,
            hiring_manager_email=None, candidate_name=name,
            candidate_email=f"{name.lower().replace(' ', '')}@example.com", candidate_timezone="UTC",
        )
        _req2, outcome = svc.submit_availability(request.request_id, [window])
        slot_ids.append(outcome.feasibility.feasible_slots[0].slot_id)
        request_ids.append(request.request_id)
        db.close()

    barrier = threading.Barrier(2)
    results = {}

    def attempt(request_id: str, slot_id: str):
        db = Session()
        try:
            barrier.wait(timeout=5)
            svc = SchedulingService(db)
            _req, interview = svc.select_slot(request_id, slot_id)
            results[request_id] = interview.seats[0].interviewer_id
        except Exception as exc:  # noqa: BLE001 - recorded, asserted on below
            results[request_id] = f"ERROR: {exc}"
        finally:
            db.close()

    threads = [
        threading.Thread(target=attempt, args=(request_ids[0], slot_ids[0])),
        threading.Thread(target=attempt, args=(request_ids[1], slot_ids[1])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert len(results) == 2, results
    assigned = list(results.values())
    for interviewer_id in assigned:
        assert not str(interviewer_id).startswith("ERROR"), results

    # The real point of this test: two *different* interviews never end up
    # with the *same* interviewer holding both overlapping seats.
    assert assigned[0] != assigned[1], (
        f"both interviews were assigned the same interviewer for an overlapping "
        f"time - double-booking guard failed: {results}"
    )
    assert set(assigned) == {"u-iv1", "u-iv2"}
