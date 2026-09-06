"""Session-wide test safety net.

``backend/.env`` carries a real ``RESEND_API_KEY`` (see .env.example / Phase 1
of Documentation/IMPLEMENTATION_PLAN.md), so without this, any test that
happens to trigger a notification (creating a request, an escalation, ...)
would make a real HTTP call to Resend and send a real email. This autouse
fixture stubs that one call out for every test in the suite.

``tests/notifications/`` further monkeypatches on top of this within
individual tests to assert specific request/response behavior — layering
another ``monkeypatch.setattr`` in the same test is fine, pytest undoes both
at teardown regardless of order.

Also resets the shared in-app notification inbox (``app/notifications/inbox.py``
- process-lifetime by design since Phase 2 builds a fresh ``SchedulingService``
per request) so one test's notifications can't leak into another's.

And stubs ``GoogleCalendarProvider.get_free_busy`` (Phase 3) to "always free,
never a reauth issue" by default - the same default behavior an empty
`MockCalendarProvider()` gave every test before Phase 3, so tests that don't
care about calendar behavior specifically (most of them) don't need a real
Google token/OAuthToken row just to reach `awaiting_candidate_selection`.
`tests/scheduling_service/test_google_calendar_provider.py` monkeypatches the
lower-level `googleapiclient` seam directly to test the real class's logic,
bypassing this stub within its own tests (pytest layers/undoes correctly).
"""

from __future__ import annotations

import pytest


class _FakeResendResponse:
    status_code = 200
    text = "{}"


@pytest.fixture(autouse=True)
def _no_real_email_sends(monkeypatch):
    import app.notifications.service as service

    monkeypatch.setattr(service.requests, "post", lambda *a, **k: _FakeResendResponse())


@pytest.fixture(autouse=True)
def _fresh_notification_inbox():
    from app.notifications.inbox import reset_shared_inbox

    reset_shared_inbox()
    yield
    reset_shared_inbox()


@pytest.fixture(autouse=True)
def _no_real_google_calendar_calls(monkeypatch):
    import app.scheduling.providers.google_calendar_provider as gcal
    from app.scheduling.models import FreeBusyResponse

    def _always_free(self, owner_id, owner_type, time_range):
        return FreeBusyResponse(
            owner_id=owner_id, owner_type=owner_type, timezone="UTC",
            busy=[], queried_range=time_range,
        )

    monkeypatch.setattr(gcal.GoogleCalendarProvider, "get_free_busy", _always_free)
