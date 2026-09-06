"""Tests for the real ``GoogleCalendarProvider`` (Phase 3 -
Documentation/IMPLEMENTATION_PLAN.md), using a fake/recorded transport
instead of real Google credentials - never hits a real Google server, per
the plan's explicit requirement. `tests/conftest.py`'s autouse
`_no_real_google_calendar_calls` fixture stubs the whole class for every
*other* test in the suite; these tests monkeypatch the lower-level
`googleapiclient`/`get_valid_access_token` seams directly instead, so they
exercise the real class body (reauth handling, response parsing, error
handling) rather than bypassing it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from googleapiclient.errors import HttpError
from sqlalchemy.orm import sessionmaker

from app.core.security import encrypt_token
from app.db import models as db_models  # noqa: F401 - registers tables on Base.metadata
from app.db.models import OAuthToken, User
from app.db.session import Base
import app.scheduling.providers.google_calendar_provider as gcal_module
from app.scheduling.models import TimeRange
from app.scheduling.providers.google_calendar_provider import GoogleCalendarProvider

UTC = timezone.utc

# tests/conftest.py's autouse `_no_real_google_calendar_calls` replaces
# `GoogleCalendarProvider.get_free_busy` on the class for every test in the
# suite (so the other 60-odd tests never need a real token). These tests
# exist specifically to test *that real method's* logic, so each one restores
# it first - captured here, before anything patches it.
_REAL_GET_FREE_BUSY = GoogleCalendarProvider.get_free_busy


@pytest.fixture(autouse=True)
def _use_the_real_method(monkeypatch):
    monkeypatch.setattr(GoogleCalendarProvider, "get_free_busy", _REAL_GET_FREE_BUSY)


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_connected_interviewer(db, user_id="u-iv") -> None:
    db.add(User(id=user_id, google_id=f"g-{user_id}", email=f"{user_id}@example.com", name="Ivan", role="interviewer"))
    db.add(
        OAuthToken(
            user_id=user_id,
            access_token_enc=encrypt_token("fake-access-token"),
            refresh_token_enc=encrypt_token("fake-refresh-token"),
            scope="https://www.googleapis.com/auth/calendar",
            expiry_utc=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db.commit()


def _time_range():
    start = datetime(2026, 9, 10, 8, tzinfo=UTC)
    return TimeRange(start=start, end=start + timedelta(hours=8))


class _FakeFreebusyQuery:
    def __init__(self, response=None, http_error=None):
        self._response = response
        self._http_error = http_error

    def execute(self):
        if self._http_error:
            raise self._http_error
        return self._response


class _FakeFreebusyResource:
    def __init__(self, response=None, http_error=None):
        self._response = response
        self._http_error = http_error

    def query(self, body):
        self.last_body = body
        return _FakeFreebusyQuery(self._response, self._http_error)


class _FakeCalendarService:
    def __init__(self, response=None, http_error=None):
        self._freebusy = _FakeFreebusyResource(response, http_error)

    def freebusy(self):
        return self._freebusy


def test_returns_real_busy_blocks_on_success(db, monkeypatch):
    _seed_connected_interviewer(db)
    response = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-09-10T10:00:00Z", "end": "2026-09-10T11:00:00Z"},
                ]
            }
        }
    }
    fake_service = _FakeCalendarService(response=response)
    monkeypatch.setattr(gcal_module, "build", lambda *a, **k: fake_service)

    provider = GoogleCalendarProvider(db)
    result = provider.get_free_busy("u-iv", "interviewer", _time_range())

    assert result.reauth_required is False
    assert len(result.busy) == 1
    assert result.busy[0].start.hour == 10


def test_dead_connection_reports_reauth_required_not_an_exception(db, monkeypatch):
    # No OAuthToken row seeded at all - get_valid_access_token raises
    # ReauthRequired("no_google_connection") internally.
    db.add(User(id="u-iv", google_id="g-iv", email="iv@example.com", name="Ivan", role="interviewer"))
    db.commit()

    provider = GoogleCalendarProvider(db)
    result = provider.get_free_busy("u-iv", "interviewer", _time_range())  # must not raise

    assert result.reauth_required is True
    assert result.busy == []


def test_calendar_level_error_in_response_is_treated_as_reauth_required(db, monkeypatch):
    _seed_connected_interviewer(db)
    response = {"calendars": {"primary": {"errors": [{"domain": "global", "reason": "notFound"}]}}}
    monkeypatch.setattr(gcal_module, "build", lambda *a, **k: _FakeCalendarService(response=response))

    provider = GoogleCalendarProvider(db)
    result = provider.get_free_busy("u-iv", "interviewer", _time_range())

    assert result.reauth_required is True
    assert result.busy == []


def test_http_error_from_the_api_is_conservative_not_a_crash(db, monkeypatch):
    _seed_connected_interviewer(db)
    fake_resp = type("Resp", (), {"status": 500, "reason": "boom"})()
    error = HttpError(fake_resp, b'{"error": "boom"}')
    monkeypatch.setattr(gcal_module, "build", lambda *a, **k: _FakeCalendarService(http_error=error))

    provider = GoogleCalendarProvider(db)
    result = provider.get_free_busy("u-iv", "interviewer", _time_range())  # must not raise

    assert result.reauth_required is True
    assert result.busy == []


def test_candidate_owner_type_is_never_queried_against_google(db, monkeypatch):
    calls = []
    monkeypatch.setattr(gcal_module, "build", lambda *a, **k: calls.append(1))

    provider = GoogleCalendarProvider(db)
    result = provider.get_free_busy("cand-1", "candidate", _time_range())

    assert calls == []  # never even tried to build a Calendar client
    assert result.reauth_required is False
    assert result.busy == []
