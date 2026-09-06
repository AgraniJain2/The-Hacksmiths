"""Concurrency test for `DbReservationLedger.reserve()` - Documentation/
IMPLEMENTATION_PLAN.md Phase 2's promised proof that the "lock the target
interviewer's InterviewerProfile row, re-check, then insert" transaction
(DATA_MODEL.md) actually guards against two *different* interviews grabbing
the same person for overlapping times (ARCHITECTURE.md's one remaining race).

Uses a real file-based SQLite DB (not `:memory:`, which is per-connection -
two threads would each get their own empty database and never contend at
all) so two independent sessions genuinely share state and SQLite's own
write-lock has something to serialize. See `db_reservation_ledger.py`'s
docstring: `with_for_update()` is a no-op on SQLite (real per-row locking
needs Postgres, ARCHITECTURE.md/Phase 6); here, correctness instead comes
from SQLite's coarser whole-database write lock - a genuinely different
mechanism, but still race-free, which is exactly what this test checks.
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
from app.db.models import Interview as InterviewRow
from app.db.models import InterviewerProfile, InterviewSlotOffer, User
from app.db.session import Base
from app.scheduling.providers.db_reservation_ledger import DbReservationLedger

UTC = timezone.utc


@pytest.fixture
def file_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = sa.create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Seed one interviewer and two *different* interviews (simulating two
    # different interviews independently trying to offer the same person
    # overlapping times - the exact race ARCHITECTURE.md names).
    seed = Session()
    seed.add(User(id="u-iv", google_id="g-iv", email="iv@example.com", name="Ivan", role="interviewer"))
    seed.add(
        InterviewerProfile(
            user_id="u-iv", name="Ivan", email="iv@example.com", skills=["python"],
            seniority="SENIOR", qualified_interview_types=["TECHNICAL_ROUND_1"],
            active=True, timezone="UTC", working_hours_start="09:00", working_hours_end="18:00",
        )
    )
    for iid in ("interview-a", "interview-b"):
        seed.add(InterviewRow(id=iid, title=iid, status="assigning_panel"))
    seed.commit()
    seed.close()

    try:
        yield Session
    finally:
        engine.dispose()
        os.remove(path)


def test_two_concurrent_interviews_cannot_both_reserve_the_same_overlapping_slot(file_db):
    Session = file_db
    start = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)

    barrier = threading.Barrier(2)
    results = {}

    def attempt(interview_id: str):
        db = Session()
        try:
            barrier.wait(timeout=5)  # both threads hit reserve() at roughly the same instant
            ledger = DbReservationLedger(db)
            ledger.reserve("u-iv", interview_id, 0, start, end)
            db.commit()
            results[interview_id] = "ok"
        except Exception as exc:  # noqa: BLE001 - either a clean ValueError or a locked-DB error is a pass
            db.rollback()
            results[interview_id] = type(exc).__name__
        finally:
            db.close()

    t1 = threading.Thread(target=attempt, args=("interview-a",))
    t2 = threading.Thread(target=attempt, args=("interview-b",))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    outcomes = list(results.values())
    assert len(outcomes) == 2, results
    assert outcomes.count("ok") == 1, (
        f"expected exactly one of the two concurrent reservations to win, got: {results}"
    )

    # The losing thread's failure must be an actual conflict, not something
    # unrelated silently swallowing a real bug.
    loser = [v for v in outcomes if v != "ok"][0]
    assert loser in ("ValueError", "OperationalError"), results

    # And the DB itself never ended up with two overlapping OFFERED rows for
    # this interviewer, no matter which thread "won".
    verify = Session()
    offers = (
        verify.query(InterviewSlotOffer)
        .filter(InterviewSlotOffer.interviewer_user_id == "u-iv", InterviewSlotOffer.status == "OFFERED")
        .all()
    )
    verify.close()
    assert len(offers) == 1
