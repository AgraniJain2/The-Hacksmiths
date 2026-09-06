"""Module 8 (Phase 5): `SchedulingService.candidate_cancel` /
`.candidate_reschedule` / `.interviewer_cancel` touching the real Calendar
event, plus the "can't cancel/reschedule something that already happened"
guard. Fake/recorded transport throughout - never hits real Google/Resend.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.security import encrypt_token
from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.models import Interview as InterviewRow
from app.db.models import OAuthToken, User
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
    # The organizer needs a real (fake) OAuthToken row, or every Calendar
    # call correctly no-ops via ReauthRequired - not what these tests exist
    # to check (that's test_google_calendar_provider.py's job).
    db = svc.db
    db.add(User(id="u-rec", google_id="g-rec", email="rec@example.com", name="Riya", role="recruiter"))
    db.add(
        OAuthToken(
            user_id="u-rec",
            access_token_enc=encrypt_token("fake-token"),
            refresh_token_enc=encrypt_token("fake-refresh"),
            scope="https://www.googleapis.com/auth/calendar",
            expiry_utc=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db.commit()
    for iid in ("u-iv1", "u-iv2"):
        svc.upsert_interviewer_profile(
            interviewer_id=iid, name=iid, email=f"{iid}@example.com", skills=["python"],
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


def _stub_calendar_and_email(monkeypatch):
    import app.scheduling.event_dispatch as dispatch_module

    calls = {"delete": [], "patch": [], "sent": []}

    class _FakeEvents:
        def get(self, calendarId, eventId):
            self._last_get = eventId
            return self

        def patch(self, calendarId, eventId, body, sendUpdates):
            calls["patch"].append((eventId, body))
            return self

        def delete(self, calendarId, eventId, sendUpdates):
            calls["delete"].append(eventId)
            return self

        def insert(self, calendarId, body, conferenceDataVersion, sendUpdates):
            self._insert_body = body
            return self

        def execute(self):
            if hasattr(self, "_insert_body"):
                return {"id": "gcal-evt", "conferenceData": {"entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/abc"}
                ]}}
            return {"attendees": [{"email": "cara@example.com"}, {"email": "u-iv1@example.com"}]}

    class _FakeService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: _FakeService())
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: calls["sent"].append(to),
    )
    return calls


def test_candidate_cancel_deletes_the_real_event(db, monkeypatch):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    interviewer_id = interview.seats[0].interviewer_id

    calls = _stub_calendar_and_email(monkeypatch)
    interview2, _req = svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=interviewer_id)
    assert interview2.calendar_event_id == "gcal-evt"
    calls["delete"].clear()  # only care about the cancel below
    calls["sent"].clear()

    request_after = svc.candidate_cancel(request_id, "the candidate withdrew")

    assert request_after.status == "cancelled"
    assert calls["delete"] == ["gcal-evt"]
    assert "cara@example.com" in calls["sent"]


def test_candidate_reschedule_deletes_old_event_and_recomputes_feasibility(db, monkeypatch):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    interviewer_id = interview.seats[0].interviewer_id

    calls = _stub_calendar_and_email(monkeypatch)
    svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=interviewer_id)
    calls["delete"].clear()

    new_start = datetime.now(UTC) + timedelta(days=3, hours=2)
    new_windows = [AvailabilityWindow(start=new_start, end=new_start + timedelta(hours=8))]
    request_after, outcome = svc.candidate_reschedule(request_id, new_windows)

    assert calls["delete"] == ["gcal-evt"]  # old event gone
    assert request_after.status == "awaiting_candidate_selection"
    assert len(outcome.feasibility.feasible_slots) > 0  # looped back to Module 3/4 for real

    row = db.query(InterviewRow).filter_by(id=request_id).first()
    assert row.calendar_event_id is None  # cleared, not left pointing at a deleted event
    assert row.meeting_link is None


def test_interviewer_cancel_removes_the_attendee_immediately(db, monkeypatch):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    first_id = interview.seats[0].interviewer_id
    second_id = "u-iv2" if first_id == "u-iv1" else "u-iv1"

    calls = _stub_calendar_and_email(monkeypatch)
    svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=first_id)
    calls["patch"].clear()
    calls["sent"].clear()

    interview2, _request2 = svc.interviewer_cancel(interview.interview_id, first_id)

    # Removed from the existing event right away, independent of whether a
    # replacement has been found yet.
    assert len(calls["patch"]) >= 1
    # The cascade re-*offers* the seat (doesn't auto-accept - someone still
    # has to say yes) to the other ranked interviewer.
    assert interview2.status == "assigning_panel"
    assert interview2.seats[0].status == "offered"
    assert interview2.seats[0].interviewer_id == second_id
    assert first_id in interview2.seats[0].declined_interviewer_ids


def test_replacement_gets_added_to_the_existing_event_once_they_accept(db, monkeypatch):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    first_id = interview.seats[0].interviewer_id
    second_id = "u-iv2" if first_id == "u-iv1" else "u-iv1"

    calls = _stub_calendar_and_email(monkeypatch)
    svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=first_id)
    svc.interviewer_cancel(interview.interview_id, first_id)
    calls["patch"].clear()

    interview3, _request3 = svc.respond_to_seat(
        interview.interview_id, 0, accept=True, actor_interviewer_id=second_id
    )

    assert interview3.status == "panel_complete"
    assert interview3.seats[0].interviewer_id == second_id
    # Re-synced the existing event (no second event created) with the new
    # roster - the replacement is now on it.
    assert len(calls["patch"]) == 1
    assert {a["email"] for a in calls["patch"][0][1]["attendees"]} == {
        "cara@example.com", f"{second_id}@example.com",
    }


def test_cannot_cancel_an_interview_that_already_happened(db, monkeypatch):
    svc = SchedulingService(db)
    _two_interviewer_setup(svc)
    request_id, interview = _create_and_book(svc)
    interviewer_id = interview.seats[0].interviewer_id
    _stub_calendar_and_email(monkeypatch)
    svc.respond_to_seat(interview.interview_id, 0, accept=True, actor_interviewer_id=interviewer_id)

    # Force the confirmed time into the past.
    row = db.query(InterviewRow).filter_by(id=request_id).first()
    row.confirmed_start_utc = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    with pytest.raises(ValueError, match="already happened"):
        svc.candidate_cancel(request_id)

    with pytest.raises(ValueError, match="already happened"):
        svc.candidate_reschedule(request_id, [])

    with pytest.raises(ValueError, match="already happened"):
        svc.interviewer_cancel(interview.interview_id, interviewer_id)
