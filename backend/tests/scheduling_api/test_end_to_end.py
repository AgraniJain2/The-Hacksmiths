"""Integration test for app/scheduling/router.py - the HTTP surface wired
onto Agrani's scheduling engine (app/scheduling/{pipeline,assignment,...}.py)
via the real, DB-backed SchedulingService (app/scheduling/service.py, Phase 2
- Documentation/IMPLEMENTATION_PLAN.md).

Uses FastAPI's TestClient with get_current_user / get_db overridden, so it
exercises real RBAC + real HTTP request/response shapes without needing a
real Google OAuth round-trip or the real dev DB. This is the "does the
router actually wire the engine up correctly" check that a pure engine unit
test (tests/scheduling/) can't give - those already fully cover the engine
itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_user
from app.db import models as db_models  # noqa: F401 - import registers tables on Base.metadata
from app.db.session import Base, get_db
from app.main import app

UTC = timezone.utc


class FakeUser:
    def __init__(self, id: str, email: str, name: str, role: str):
        self.id = id
        self.email = email
        self.name = name
        self.role = role


_current_user: dict[str, FakeUser | None] = {"user": None}


def _override_get_current_user():
    if _current_user["user"] is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="not_authenticated")
    return _current_user["user"]


_test_engine = sa.create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=sa.pool.StaticPool,  # one shared connection - a plain :memory: db is per-connection
)
_TestSession = sessionmaker(bind=_test_engine)
Base.metadata.create_all(_test_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_current_user] = _override_get_current_user
app.dependency_overrides[get_db] = _override_get_db

client = TestClient(app)

RECRUITER = FakeUser("user-recruiter-1", "recruiter@example.com", "Riya Recruiter", "recruiter")
CANDIDATE = FakeUser("user-candidate-1", "cand@example.com", "Priya Candidate", "candidate")
INTERVIEWER = FakeUser("user-interviewer-1", "iv@example.com", "Ivan Interviewer", "interviewer")


def as_(user: FakeUser):
    _current_user["user"] = user


@pytest.fixture(autouse=True)
def fresh_store():
    """Each test gets a clean DB - state must not leak between tests any
    more than it should leak between real requests for different interviews.
    Drop + recreate every table rather than deleting rows, so a schema
    change here can't quietly leave an old table around."""
    Base.metadata.drop_all(_test_engine)
    Base.metadata.create_all(_test_engine)
    yield
    _current_user["user"] = None


def test_full_happy_path_request_to_panel_complete():
    # 1. Recruiter creates the request.
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1",
            "required_skills": ["python"],
            "seniority": "MID",
            "panelists_required": 1,
            "candidate_name": "Priya Candidate",
            "candidate_email": "cand@example.com",
            "candidate_timezone": "Asia/Kolkata",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    request_id = body["request"]["request_id"]
    assert body["request"]["status"] == "collecting_availability"
    assert "/login?invite_token=" in body["invite_link"]

    # A candidate can't create requests.
    as_(CANDIDATE)
    assert client.post("/scheduling/requests", json={}).status_code in (403, 422)

    # 2. Interviewer registers a Module-2B-lite profile.
    as_(INTERVIEWER)
    resp = client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"],
            "seniority": "SENIOR",
            "interview_types": ["TECHNICAL"],
            "timezone": "Asia/Kolkata",
            "working_hours_start": "09:00",
            "working_hours_end": "18:00",
            "active": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["interviewer_id"] == INTERVIEWER.id

    # 3. Candidate submits availability - a window safely inside the
    # interviewer's 09:00-18:00 IST working hours (04:00-11:00 UTC ==
    # 09:30-16:30 IST), wide enough for a 60m slot + 15/15 buffers.
    as_(CANDIDATE)
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["request"]["status"] == "awaiting_candidate_selection"
    feasible_slots = detail["feasibility"]["feasible_slots"]
    assert len(feasible_slots) > 0, detail["feasibility"]
    slot_id = feasible_slots[0]["slot_id"]

    # Another candidate can't act on this request.
    as_(FakeUser("user-other", "other@example.com", "Other", "candidate"))
    assert client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id}).status_code == 403

    # 4. Candidate picks the slot -> panel assignment runs, one seat offered.
    as_(CANDIDATE)
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["request"]["status"] == "assigning_panel"
    interview = detail["interview"]
    assert interview["status"] == "assigning_panel"
    assert len(interview["seats"]) == 1
    seat = interview["seats"][0]
    assert seat["status"] == "offered"
    assert seat["interviewer_id"] == INTERVIEWER.id
    interview_id = interview["interview_id"]

    # 5. Interviewer sees the offer in their inbox-of-offers.
    as_(INTERVIEWER)
    resp = client.get("/scheduling/interviewer/offers")
    assert resp.status_code == 200
    offers = resp.json()
    assert len(offers) == 1
    assert offers[0]["interview"]["interview_id"] == interview_id

    # 6. Interviewer accepts -> panel_complete.
    resp = client.post(f"/scheduling/interviews/{interview_id}/seats/0/respond", json={"accept": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["interview"]["status"] == "panel_complete"

    # 7. Interviewer got notified along the way (still acting as INTERVIEWER).
    resp = client.get("/scheduling/notifications")
    kinds = [n["kind"] for n in resp.json()]
    assert "seat_offer" in kinds
    assert "panel_complete" in kinds

    # Request mirrors the interview's final status - recruiter's view.
    as_(RECRUITER)
    resp = client.get(f"/scheduling/requests/{request_id}")
    assert resp.json()["request"]["status"] == "panel_complete"

    as_(CANDIDATE)
    resp = client.get("/scheduling/notifications")
    kinds = [n["kind"] for n in resp.json()]
    assert "panel_complete" in kinds


def test_insufficient_pool_escalates_instead_of_hanging():
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1",
            "required_skills": ["rust"],
            "seniority": "SENIOR",
            "panelists_required": 2,
            "candidate_name": "Nobody Qualified",
            "candidate_email": "nq@example.com",
            "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(FakeUser("user-nq", "nq@example.com", "Nobody Qualified", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    detail = resp.json()
    assert detail["request"]["status"] == "manual_scheduling_required"
    assert detail["feasibility"]["no_match_reason"]
    assert detail["feasibility"]["feasible_slots"] == []
    # Candidate-facing copy is a separate, generic field over the API too -
    # never the same string as the recruiter's specific no_match_reason.
    assert detail["feasibility"]["candidate_message"]
    assert detail["feasibility"]["candidate_message"] != detail["feasibility"]["no_match_reason"]


def test_dead_google_connection_surfaces_over_the_api_not_a_500(monkeypatch):
    """Phase 3: the one real interviewer for this request has a dead Google
    connection - the request must escalate with a specific, visible reason
    (RequestDetail.feasibility.reauth_required_interviewer_ids), never a
    silently-empty pool or a 500 from deep inside a Calendar call."""
    import app.scheduling.providers.google_calendar_provider as gcal_module
    from app.scheduling.models import FreeBusyResponse

    def _dead_connection(self, owner_id, owner_type, time_range):
        return FreeBusyResponse(
            owner_id=owner_id, owner_type=owner_type, timezone="UTC",
            busy=[], queried_range=time_range, reauth_required=True,
        )

    monkeypatch.setattr(gcal_module.GoogleCalendarProvider, "get_free_busy", _dead_connection)

    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1",
            "required_skills": ["python"],
            "seniority": "MID",
            "panelists_required": 1,
            "candidate_name": "Dana Disconnected",
            "candidate_email": "dana@example.com",
            "candidate_timezone": "UTC",
        },
    )
    assert resp.status_code == 200, resp.text
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    resp = client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59",
            "active": True,
        },
    )
    assert resp.status_code == 200, resp.text

    as_(FakeUser("user-dana", "dana@example.com", "Dana Disconnected", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()

    assert detail["request"]["status"] == "manual_scheduling_required"
    assert detail["feasibility"]["reauth_required_interviewer_ids"] == [INTERVIEWER.id]
    assert "dead Google connection" in detail["feasibility"]["no_match_reason"]


def test_panel_complete_creates_a_real_calendar_event_over_the_api(monkeypatch):
    """Phase 4 (Module 7): once the last seat is accepted, the router's
    response (and a follow-up GET) carry the real calendar_event_id/meet_link
    - proves the service-layer wiring (SchedulingService -> event_dispatch),
    not just the dispatch function in isolation
    (tests/scheduling_service/test_event_dispatch.py already covers that)."""
    import app.scheduling.event_dispatch as dispatch_module
    from app.core.security import encrypt_token
    from app.db.models import OAuthToken

    # The recruiter is the organizer - needs a real (fake) OAuthToken row.
    seed_db = _TestSession()
    seed_db.add(
        OAuthToken(
            user_id=RECRUITER.id,
            access_token_enc=encrypt_token("fake-token"),
            refresh_token_enc=encrypt_token("fake-refresh"),
            scope="https://www.googleapis.com/auth/calendar",
            expiry_utc=datetime(2100, 1, 1),
        )
    )
    seed_db.commit()
    seed_db.close()

    class _FakeEvents:
        def insert(self, calendarId, body, conferenceDataVersion, sendUpdates):
            self.body = body
            return self

        def execute(self):
            return {
                "id": "gcal-event-xyz",
                "conferenceData": {
                    "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/xyz-abcd"}]
                },
            }

    class _FakeCalendarService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: _FakeCalendarService())
    sent_emails = []
    monkeypatch.setattr(
        dispatch_module, "send_email",
        lambda to, subject, body, ics_attachment=None, ics_filename=None: sent_emails.append(to),
    )

    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Cara Candidate",
            "candidate_email": "cara-p4@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-cara-p4", "cara-p4@example.com", "Cara Candidate", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    interview_id = resp.json()["interview"]["interview_id"]

    as_(INTERVIEWER)
    resp = client.post(f"/scheduling/interviews/{interview_id}/seats/0/respond", json={"accept": True})
    assert resp.status_code == 200, resp.text
    interview = resp.json()["interview"]
    assert interview["status"] == "panel_complete"
    assert interview["calendar_event_id"] == "gcal-event-xyz"
    assert interview["meet_link"] == "https://meet.google.com/xyz-abcd"

    # Both attendees actually got a confirmation email.
    assert set(sent_emails) == {"cara-p4@example.com", INTERVIEWER.email}

    # And it's durable - a fresh GET shows the same event, not recomputed.
    as_(RECRUITER)
    resp = client.get(f"/scheduling/requests/{request_id}")
    assert resp.json()["interview"]["calendar_event_id"] == "gcal-event-xyz"


def test_staff_can_cancel_and_it_deletes_the_real_calendar_event(monkeypatch):
    """Phase 5 (Module 8): a recruiter (not just the candidate) can cancel a
    booked interview over the API, and doing so actually deletes the real
    Calendar event, not just the DB row."""
    import app.scheduling.event_dispatch as dispatch_module
    from app.core.security import encrypt_token
    from app.db.models import OAuthToken

    seed_db = _TestSession()
    seed_db.add(
        OAuthToken(
            user_id=RECRUITER.id,
            access_token_enc=encrypt_token("fake-token"),
            refresh_token_enc=encrypt_token("fake-refresh"),
            scope="https://www.googleapis.com/auth/calendar",
            expiry_utc=datetime(2100, 1, 1),
        )
    )
    seed_db.commit()
    seed_db.close()

    delete_calls = []

    class _FakeEvents:
        def insert(self, calendarId, body, conferenceDataVersion, sendUpdates):
            return self

        def delete(self, calendarId, eventId, sendUpdates):
            delete_calls.append(eventId)
            return self

        def execute(self):
            return {
                "id": "gcal-event-cancel-me",
                "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/x"}]},
            }

    class _FakeCalendarService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: _FakeCalendarService())
    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: None)

    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Cara Cancel",
            "candidate_email": "cara-cancel@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-cara-cancel", "cara-cancel@example.com", "Cara Cancel", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    interview_id = resp.json()["interview"]["interview_id"]

    as_(INTERVIEWER)
    client.post(f"/scheduling/interviews/{interview_id}/seats/0/respond", json={"accept": True})

    # A candidate cannot cancel someone else's interview...
    as_(FakeUser("user-other-2", "other2@example.com", "Other", "candidate"))
    assert client.post(f"/scheduling/requests/{request_id}/cancel").status_code == 403

    # ...but the recruiter who owns it can.
    as_(RECRUITER)
    resp = client.post(f"/scheduling/requests/{request_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["request"]["status"] == "cancelled"
    assert delete_calls == ["gcal-event-cancel-me"]


def test_cancelling_an_interview_that_already_happened_is_rejected(monkeypatch):
    """Phase 5's guard: MODULE_GUIDE.md's Module 8 edge case - a cancel
    arriving after the interview's already happened must be rejected, not
    silently processed."""
    import app.scheduling.event_dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "build", lambda *a, **k: pytest.fail("should not reach Calendar"))
    monkeypatch.setattr(dispatch_module, "send_email", lambda *a, **k: None)

    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Cara Past",
            "candidate_email": "cara-past@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-cara-past", "cara-past@example.com", "Cara Past", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})

    # Force the confirmed time into the past, directly in the DB.
    force_db = _TestSession()
    row = force_db.query(db_models.Interview).filter_by(id=request_id).first()
    row.confirmed_start_utc = datetime(2020, 1, 1)
    force_db.commit()
    force_db.close()

    resp = client.post(f"/scheduling/requests/{request_id}/cancel")
    assert resp.status_code == 400
    assert "already happened" in resp.json()["detail"]


def test_invalid_enum_values_are_rejected_with_422_not_a_500():
    """Phase 6 (CONVENTIONS.md pass): a garbage seniority/interview_type used
    to sail past validation, get committed to the DB, and only blow up as an
    unhandled 500 the next time anything read the row back. Now rejected at
    the request boundary instead."""
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "NOT_A_REAL_TYPE",
            "required_skills": ["python"],
            "seniority": "MID",
            "panelists_required": 1,
            "candidate_name": "Test",
            "candidate_email": "test@example.com",
            "candidate_timezone": "UTC",
        },
    )
    assert resp.status_code == 422

    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1",
            "required_skills": ["python"],
            "seniority": "NOT_A_LEVEL",
            "panelists_required": 1,
            "candidate_name": "Test",
            "candidate_email": "test@example.com",
            "candidate_timezone": "UTC",
        },
    )
    assert resp.status_code == 422

    as_(INTERVIEWER)
    resp = client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR",
            "interview_types": ["TECHNICAL_ROUND_1"],  # the old granular value - no longer accepted here
            "timezone": "UTC", "working_hours_start": "09:00", "working_hours_end": "18:00", "active": True,
        },
    )
    assert resp.status_code == 422


def test_inverted_working_hours_are_rejected():
    as_(INTERVIEWER)
    resp = client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "18:00", "working_hours_end": "09:00", "active": True,
        },
    )
    assert resp.status_code == 422


def test_double_submitting_select_slot_is_rejected_not_a_silent_double_run():
    """Phase 6 / MODULE_GUIDE.md Module 5 edge case."""
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Double Submitter",
            "candidate_email": "double@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-double", "double@example.com", "Double Submitter", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]

    resp1 = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    assert resp1.status_code == 200, resp1.text

    # Same click fired twice (double-click / a retried request).
    resp2 = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    assert resp2.status_code == 400
    assert "not awaiting a slot selection" in resp2.json()["detail"]


def test_resubmitting_availability_once_a_panel_is_assigning_is_rejected():
    """Same Module 5 edge case as the select-slot test above, for
    `submit_availability`'s own guard: a stale/duplicate availability
    submission (stale tab, browser back button) landing after the candidate
    already picked a slot must not silently reset `status` back to a
    request-level value while a panel's `seats_json` is still in place -
    live in dev.db this produced a row `_row_to_interview` couldn't
    reconstruct, 500-ing every later GET on the request."""
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Resubmitter",
            "candidate_email": "resubmitter@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-resubmitter", "resubmitter@example.com", "Resubmitter", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    assert resp.status_code == 200, resp.text

    # The (now stale) availability form fires again after the panel is
    # already being assigned.
    resp2 = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-11T04:00:00Z", "end": "2026-09-11T11:00:00Z"}]},
    )
    assert resp2.status_code == 400
    assert "not collecting availability" in resp2.json()["detail"]

    # And the request must still be readable afterwards - not left crashing
    # every subsequent GET.
    resp3 = client.get(f"/scheduling/requests/{request_id}")
    assert resp3.status_code == 200, resp3.text


def test_candidate_can_cancel_out_of_manual_scheduling_required(monkeypatch):
    """Phase 6: found reachable and previously crashed with an unhandled
    InvalidTransitionError - a candidate's request escalated to
    manual_scheduling_required (seat pool exhausted) while a real Interview
    row already existed, and cancelling from there is a legitimate action
    ("never mind"), not something that needs a human to pick it up first."""
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Cara Exhausted",
            "candidate_email": "cara-exhausted@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-cara-exhausted", "cara-exhausted@example.com", "Cara Exhausted", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    interview_id = resp.json()["interview"]["interview_id"]

    # The only eligible interviewer declines - pool exhausted for this seat,
    # nowhere to cascade to - escalates, with a real Interview row already
    # in place.
    as_(INTERVIEWER)
    resp = client.post(f"/scheduling/interviews/{interview_id}/seats/0/respond", json={"accept": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["interview"]["status"] == "manual_scheduling_required"

    as_(FakeUser("user-cara-exhausted", "cara-exhausted@example.com", "Cara Exhausted", "candidate"))
    resp = client.post(f"/scheduling/requests/{request_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["request"]["status"] == "cancelled"


def test_interviewer_cancelling_a_seat_they_dont_hold_is_a_clean_400(monkeypatch):
    """Phase 6: SeatError used to escape _wrap() uncaught."""
    as_(RECRUITER)
    resp = client.post(
        "/scheduling/requests",
        json={
            "interview_type": "TECHNICAL_ROUND_1", "required_skills": ["python"], "seniority": "MID",
            "panelists_required": 1, "candidate_name": "Cara NotHeld",
            "candidate_email": "cara-notheld@example.com", "candidate_timezone": "UTC",
        },
    )
    request_id = resp.json()["request"]["request_id"]

    as_(INTERVIEWER)
    client.put(
        "/scheduling/interviewer/profile",
        json={
            "skills": ["python"], "seniority": "SENIOR", "interview_types": ["TECHNICAL"],
            "timezone": "UTC", "working_hours_start": "00:00", "working_hours_end": "23:59", "active": True,
        },
    )

    as_(FakeUser("user-cara-notheld", "cara-notheld@example.com", "Cara NotHeld", "candidate"))
    resp = client.post(
        f"/scheduling/requests/{request_id}/availability",
        json={"windows": [{"start": "2026-09-10T04:00:00Z", "end": "2026-09-10T11:00:00Z"}]},
    )
    slot_id = resp.json()["feasibility"]["feasible_slots"][0]["slot_id"]
    resp = client.post(f"/scheduling/requests/{request_id}/select-slot", json={"slot_id": slot_id})
    interview_id = resp.json()["interview"]["interview_id"]

    # Seat is only OFFERED, not yet accepted - INTERVIEWER doesn't hold a
    # confirmed seat to cancel.
    as_(INTERVIEWER)
    resp = client.post(f"/scheduling/interviews/{interview_id}/interviewer-cancel")
    assert resp.status_code == 400
