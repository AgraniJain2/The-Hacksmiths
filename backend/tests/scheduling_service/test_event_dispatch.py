"""Tests for Module 7's event creation/dispatch (Phase 4 -
Documentation/IMPLEMENTATION_PLAN.md) - ``event_dispatch.dispatch_confirmed_booking``.

Fake/recorded transport throughout (googleapiclient's ``build`` and
``send_email`` are both monkeypatched) - never hits real Google or Resend,
per the same policy Phase 3's tests follow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from googleapiclient.errors import HttpError
from sqlalchemy.orm import sessionmaker

from app.core.security import encrypt_token
from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.models import Interview as InterviewRow
from app.db.models import InterviewerProfile, OAuthToken, User
from app.db.session import Base
from app.notifications.service import EmailSendError
import app.scheduling.event_dispatch as dispatch_module
from app.scheduling.event_dispatch import (
    cancel_event,
    dispatch_confirmed_booking,
    remove_attendee_from_event,
)
from app.scheduling.models import Interview, InterviewSeat
from app.scheduling.providers.db_repositories import DbInterviewerRepository

UTC = timezone.utc


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed(db):
    db.add(User(id="u-rec", google_id="g-rec", email="recruiter@example.com", name="Riya", role="recruiter"))
    db.add(
        OAuthToken(
            user_id="u-rec",
            access_token_enc=encrypt_token("fake-token"),
            refresh_token_enc=encrypt_token("fake-refresh"),
            scope="https://www.googleapis.com/auth/calendar",
            expiry_utc=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db.add(User(id="u-iv", google_id="g-iv", email="iv@example.com", name="Ivan", role="interviewer"))
    db.add(
        InterviewerProfile(
            user_id="u-iv", name="Ivan", email="iv@example.com", skills=["python"], seniority="SENIOR",
            qualified_interview_types=["TECHNICAL_ROUND_1"], active=True, timezone="UTC",
            working_hours_start="09:00", working_hours_end="18:00",
        )
    )
    row = InterviewRow(
        id="req-1", title="TECHNICAL_ROUND_1 - Cara Candidate", status="panel_complete",
        created_by="u-rec", created_by_email="recruiter@example.com",
        interview_type="TECHNICAL_ROUND_1", candidate_email="cara@example.com",
        candidate_name="Cara Candidate", candidate_timezone="UTC",
        panelists_required=1, duration_minutes=60, buffer_minutes_before=15, buffer_minutes_after=15,
    )
    db.add(row)
    db.commit()
    return row


def _interview(row) -> Interview:
    start = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    return Interview(
        interview_id=row.id, request_id=row.id, candidate_id="cara@example.com",
        interview_type="TECHNICAL_ROUND_1", slot_start=start, slot_end=start + timedelta(hours=1),
        seats=[InterviewSeat(seat_index=0, interviewer_id="u-iv", status="accepted", responded_at=start)],
        status="panel_complete", created_at=start, updated_at=start,
    )


class _FakeEventsResource:
    def __init__(self, response=None, http_error=None):
        self._response = response
        self._http_error = http_error
        self.insert_calls = []
        self.patch_calls = []
        self.delete_calls = []
        self.get_response = None

    def insert(self, calendarId, body, conferenceDataVersion, sendUpdates):
        self.insert_calls.append(body)
        return self

    def patch(self, calendarId, eventId, body, sendUpdates):
        self.patch_calls.append(body)
        return self

    def get(self, calendarId, eventId):
        return self

    def delete(self, calendarId, eventId, sendUpdates):
        self.delete_calls.append(eventId)
        return self

    def execute(self):
        if self._http_error:
            raise self._http_error
        return self.get_response if self.get_response is not None else self._response


class _FakeCalendarService:
    def __init__(self, response=None, http_error=None):
        self.events_resource = _FakeEventsResource(response, http_error)

    def events(self):
        return self.events_resource


def _default_event_response():
    return {
        "id": "gcal-event-123",
        "conferenceData": {
            "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}]
        },
    }


def test_creates_event_and_sends_confirmation_with_ics(db, monkeypatch):
    row = _seed(db)
    interview = _interview(row)
    fake_service = _FakeCalendarService(response=_default_event_response())
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)

    sent = []
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: sent.append(
            (to, subject, ics_attachment is not None)
        ),
    )

    result = dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))

    assert result.calendar_event_id == "gcal-event-123"
    assert result.meet_link == "https://meet.google.com/abc-defg-hij"
    assert row.calendar_event_id == "gcal-event-123"
    assert row.meeting_link == "https://meet.google.com/abc-defg-hij"

    # Candidate + the one confirmed interviewer, both emailed, both with an .ics.
    recipients = {r[0] for r in sent}
    assert recipients == {"cara@example.com", "iv@example.com"}
    assert all(has_ics for _, _, has_ics in sent)

    # The real events.insert payload shape.
    body = fake_service.events_resource.insert_calls[0]
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
    assert {a["email"] for a in body["attendees"]} == {"cara@example.com", "iv@example.com"}
    # Regression: a real events.insert call rejects a bare dateTime with no
    # `timeZone` ("Missing time zone definition for start/end time"), even
    # though the dateTime string itself carries a UTC offset - found against
    # a real account during Phase 4's manual verification, not by inspection.
    assert body["start"]["timeZone"] == "UTC"
    assert body["end"]["timeZone"] == "UTC"


def test_is_idempotent_a_retry_never_creates_a_second_event(db, monkeypatch):
    """A retry with the exact same confirmed roster must not create a second
    event - it takes the "sync attendees" path (same one a real interviewer
    reshuffle uses, tested below), which patches the *existing* event rather
    than inserting a new one."""
    row = _seed(db)
    interview = _interview(row)
    fake_service = _FakeCalendarService(response=_default_event_response())
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)
    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: None)

    dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))
    assert len(fake_service.events_resource.insert_calls) == 1

    # Retry - same row, now already has calendar_event_id set.
    result = dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))
    assert len(fake_service.events_resource.insert_calls) == 1  # unchanged - no second event
    assert len(fake_service.events_resource.patch_calls) == 1  # synced instead
    assert result.calendar_event_id == "gcal-event-123"


def test_a_replacement_interviewer_gets_added_to_the_existing_event(db, monkeypatch):
    """The Phase 5 scenario: a confirmed interviewer already cancelled (their
    own removal already patched the event elsewhere -
    test_event_dispatch_cancellation.py), the cascade just landed on a
    replacement, and the interview is panel_complete again. This must patch
    the *existing* event to the new roster, not create a second event."""
    row = _seed(db)
    row.calendar_event_id = "gcal-event-existing"
    row.meeting_link = "https://meet.google.com/existing"
    db.commit()
    interview = _interview(row).model_copy(
        update={"calendar_event_id": "gcal-event-existing", "meet_link": "https://meet.google.com/existing"}
    )
    fake_service = _FakeCalendarService(response=_default_event_response())
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)
    sent = []
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: sent.append(to),
    )

    dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))

    assert fake_service.events_resource.insert_calls == []  # never created a second event
    assert len(fake_service.events_resource.patch_calls) == 1
    assert {a["email"] for a in fake_service.events_resource.patch_calls[0]["attendees"]} == {
        "cara@example.com", "iv@example.com",
    }
    assert "iv@example.com" in sent  # the (re-)confirmed interviewer gets the confirmation too


def test_organizer_dead_connection_does_not_raise(db):
    # No OAuthToken seeded for u-rec this time.
    db.add(User(id="u-rec", google_id="g-rec", email="recruiter@example.com", name="Riya", role="recruiter"))
    db.add(User(id="u-iv", google_id="g-iv", email="iv@example.com", name="Ivan", role="interviewer"))
    row = InterviewRow(
        id="req-2", title="x", status="panel_complete", created_by="u-rec",
        created_by_email="recruiter@example.com", interview_type="TECHNICAL_ROUND_1",
        candidate_email="cara@example.com", panelists_required=1,
    )
    db.add(row)
    db.commit()
    interview = _interview(row)

    result = dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))  # must not raise

    assert result.calendar_event_id is None
    assert row.calendar_event_id is None


def test_calendar_http_error_does_not_raise_or_partially_commit(db, monkeypatch):
    row = _seed(db)
    interview = _interview(row)
    fake_resp = type("Resp", (), {"status": 500, "reason": "boom"})()
    fake_service = _FakeCalendarService(http_error=HttpError(fake_resp, b'{"error":"boom"}'))
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)

    result = dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))  # must not raise

    assert result.calendar_event_id is None
    assert row.calendar_event_id is None


def test_email_failure_does_not_undo_the_already_created_event(db, monkeypatch):
    row = _seed(db)
    interview = _interview(row)
    fake_service = _FakeCalendarService(response=_default_event_response())
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)

    def _raise(*a, **k):
        raise EmailSendError("simulated outage")

    monkeypatch.setattr(dispatch_module, "send_email", _raise)

    result = dispatch_confirmed_booking(db, row, interview, DbInterviewerRepository(db))  # must not raise

    # The event is real and durable even though the follow-up email failed.
    assert result.calendar_event_id == "gcal-event-123"
    assert row.calendar_event_id == "gcal-event-123"


def test_cancel_event_deletes_the_real_event_and_notifies_attendees(db, monkeypatch):
    row = _seed(db)
    row.calendar_event_id = "gcal-event-to-cancel"
    row.meeting_link = "https://meet.google.com/xyz"
    db.commit()
    interview = _interview(row).model_copy(
        update={"calendar_event_id": "gcal-event-to-cancel", "meet_link": "https://meet.google.com/xyz"}
    )
    fake_service = _FakeCalendarService()
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)
    sent = []
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: sent.append((to, subject)),
    )

    cancel_event(db, row, interview, DbInterviewerRepository(db), "the candidate cancelled")

    assert fake_service.events_resource.delete_calls == ["gcal-event-to-cancel"]
    recipients = {r[0] for r in sent}
    assert recipients == {"cara@example.com", "iv@example.com"}
    assert all("Cancelled" in subject for _to, subject in sent)


def test_cancel_event_is_a_noop_when_there_was_never_a_real_event(db, monkeypatch):
    row = _seed(db)  # calendar_event_id is None
    interview = _interview(row)
    fake_service = _FakeCalendarService()
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)
    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: pytest.fail("should not be called"))

    cancel_event(db, row, interview, DbInterviewerRepository(db), "reason")  # must not raise or email anyone

    assert fake_service.events_resource.delete_calls == []


def test_cancel_event_treats_already_deleted_as_success(db, monkeypatch):
    row = _seed(db)
    row.calendar_event_id = "gcal-event-gone"
    db.commit()
    interview = _interview(row)
    fake_resp = type("Resp", (), {"status": 410, "reason": "gone"})()
    fake_service = _FakeCalendarService(http_error=HttpError(fake_resp, b"{}"))
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)
    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: None)

    cancel_event(db, row, interview, DbInterviewerRepository(db), "reason")  # must not raise


def test_remove_attendee_from_event_patches_without_the_departing_person(db, monkeypatch):
    row = _seed(db)
    row.calendar_event_id = "gcal-event-existing"
    db.commit()
    fake_service = _FakeCalendarService()
    fake_service.events_resource.get_response = {
        "attendees": [{"email": "cara@example.com"}, {"email": "iv@example.com"}]
    }
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)

    remove_attendee_from_event(db, row, "iv@example.com")

    assert len(fake_service.events_resource.patch_calls) == 1
    remaining = {a["email"] for a in fake_service.events_resource.patch_calls[0]["attendees"]}
    assert remaining == {"cara@example.com"}


def test_remove_attendee_from_event_is_a_noop_without_a_real_event(db, monkeypatch):
    row = _seed(db)  # no calendar_event_id
    fake_service = _FakeCalendarService()
    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: fake_service)

    remove_attendee_from_event(db, row, "iv@example.com")  # must not raise

    assert fake_service.events_resource.patch_calls == []
