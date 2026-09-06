"""Module 8 (Phase 5) - the two scheduled sweeps
(`SchedulingService.sweep_expired_offers` / `.sweep_reminders`), tested at
the service level directly (not through `jobs.py`'s APScheduler wrapper,
which is just a thin "run periodically, log the outcome" shell around
these).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.models import Interview as InterviewRow
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


def _two_interviewer_setup(svc: SchedulingService):
    svc.upsert_interviewer_profile(
        interviewer_id="u-iv1", name="Ivan One", email="iv1@example.com", skills=["python"],
        seniority="SENIOR", interview_types=["TECHNICAL_ROUND_1"], timezone_name="UTC",
        working_hours_start="00:00", working_hours_end="23:59", active=True,
    )
    svc.upsert_interviewer_profile(
        interviewer_id="u-iv2", name="Ivan Two", email="iv2@example.com", skills=["python"],
        seniority="SENIOR", interview_types=["TECHNICAL_ROUND_1"], timezone_name="UTC",
        working_hours_start="00:00", working_hours_end="23:59", active=True,
    )


def _create_and_book(svc: SchedulingService, *, start_offset_days=1):
    request, _round = svc.create_request(
        owner_user_id="u-rec", owner_email="rec@example.com", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python"], seniority="MID", panelists_required=1,
        duration_minutes=30, buffer_minutes_before=10, buffer_minutes_after=10,
        hiring_manager_email=None, candidate_name="Cara Candidate",
        candidate_email="cara@example.com", candidate_timezone="UTC",
    )
    now = datetime.now(UTC)
    start = now + timedelta(days=start_offset_days, hours=1)
    _req2, outcome = svc.submit_availability(
        request.request_id, [AvailabilityWindow(start=start, end=start + timedelta(hours=8))]
    )
    slot = outcome.feasibility.feasible_slots[0]
    _req3, interview = svc.select_slot(request.request_id, slot.slot_id)
    return request.request_id, interview


def test_expired_offer_cascades_to_the_next_ranked_interviewer(db):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    first_offered = interview.seats[0].interviewer_id
    assert first_offered in ("u-iv1", "u-iv2")

    # Backdate the offer past its expiry - the sweep should find it without
    # needing to actually wait out the real 24h timeout. A fresh list/dict
    # (not an in-place mutation of the fetched value) so SQLAlchemy's plain
    # JSON column type actually notices the column changed.
    row = db.query(InterviewRow).filter_by(id=request_id).first()
    seats = [dict(s) for s in row.seats_json]
    seats[0] = {**seats[0], "offer_expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    row.seats_json = seats
    db.commit()
    db.expire_all()

    touched = svc.sweep_expired_offers()
    assert touched == [request_id]

    row = db.query(InterviewRow).filter_by(id=request_id).first()
    new_seat = row.seats_json[0]
    assert new_seat["interviewer_id"] != first_offered  # cascaded to the other one
    assert new_seat["status"] == "offered"
    assert first_offered in new_seat["declined_interviewer_ids"]


def test_sweep_is_a_noop_when_nothing_has_expired(db):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, _interview = _create_and_book(svc)

    touched = svc.sweep_expired_offers()

    assert touched == []
    row = db.query(InterviewRow).filter_by(id=request_id).first()
    assert row.seats_json[0]["status"] == "offered"  # untouched


def test_reminder_sweep_sends_once_and_marks_sent(db, monkeypatch):
    import app.scheduling.event_dispatch as dispatch_module

    sent = []
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: sent.append(to),
    )

    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    # Accept the seat so the interview is panel_complete (reminders only go
    # out for confirmed bookings).
    interviewer_id = interview.seats[0].interviewer_id
    interview2, _req = svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=interviewer_id)
    assert interview2.status == "panel_complete"

    reminded = svc.sweep_reminders(window_hours=48)
    assert reminded == [request_id]
    assert set(sent) == {"cara@example.com", f"{'iv1' if interviewer_id == 'u-iv1' else 'iv2'}@example.com"}

    row = db.query(InterviewRow).filter_by(id=request_id).first()
    assert row.reminder_sent_at is not None

    # Second run - already reminded, must not send again.
    sent.clear()
    reminded_again = svc.sweep_reminders(window_hours=48)
    assert reminded_again == []
    assert sent == []


def test_reminder_sweep_ignores_interviews_outside_the_window(db, monkeypatch):
    import app.scheduling.event_dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: None)

    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    # 10 days out - outside a 24h reminder window.
    request_id, interview = _create_and_book(svc, start_offset_days=10)
    interviewer_id = interview.seats[0].interviewer_id
    svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=interviewer_id)

    reminded = svc.sweep_reminders(window_hours=24)

    assert reminded == []
    row = db.query(InterviewRow).filter_by(id=request_id).first()
    assert row.reminder_sent_at is None
