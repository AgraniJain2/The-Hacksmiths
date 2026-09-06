from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.notifications.provider as provider_module
from app.notifications.provider import ResendNotificationProvider
from app.scheduling.models import Interview, InterviewRequest, InterviewSeat
from app.scheduling.providers.mock_repositories import MockInterviewerRepository

UTC = timezone.utc


def _interviewer(iid: str, email: str):
    from app.scheduling.models import Interviewer, WorkingHours

    return Interviewer(
        interviewer_id=iid,
        name=iid,
        email=email,
        timezone="UTC",
        skills=["python"],
        seniority="MID",
        interview_types=["TECHNICAL_ROUND_1"],
        working_hours=WorkingHours(start="09:00", end="18:00"),
        calendar_id=f"cal-{iid}",
        active=True,
    )


def _interview(seats):
    return Interview(
        interview_id="iv-1",
        request_id="req-1",
        candidate_id="candidate@example.com",
        interview_type="TECHNICAL_ROUND_1",
        slot_start=datetime(2026, 9, 10, 9, tzinfo=UTC),
        slot_end=datetime(2026, 9, 10, 10, tzinfo=UTC),
        seats=seats,
        status="assigning_panel",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


@pytest.fixture
def sent(monkeypatch):
    """Captures every call the provider makes to send_email, without hitting Resend."""
    calls = []
    monkeypatch.setattr(provider_module, "send_email", lambda *a, **k: calls.append((a, k)))
    return calls


@pytest.fixture
def failing_send(monkeypatch):
    """send_email always raises - proves the provider swallows it."""
    from app.notifications.service import EmailSendError

    def _raise(*a, **k):
        raise EmailSendError("simulated outage")

    monkeypatch.setattr(provider_module, "send_email", _raise)


def _provider():
    repo = MockInterviewerRepository([_interviewer("iv-ana", "ana@example.com")])
    emails = {"req-1": "recruiter@example.com"}
    identities = {"req-1": "user-1"}
    return ResendNotificationProvider(repo, emails.get, identities.get)


def test_seat_offer_emails_the_interviewer_and_writes_inbox(sent):
    p = _provider()
    seat = InterviewSeat(seat_index=0, interviewer_id="iv-ana", status="offered")

    p.send_seat_offer(_interview([seat]), seat)

    assert len(sent) == 1
    (to, subject, _body), _ = sent[0]
    assert to == "ana@example.com"
    assert "panel seat" in subject.lower()
    # dual-write: the in-app inbox still has it too
    assert p.for_recipient("iv-ana")


def test_panel_complete_emails_every_interviewer_and_the_candidate(sent):
    p = _provider()
    seat = InterviewSeat(seat_index=0, interviewer_id="iv-ana", status="accepted")

    p.send_panel_complete(_interview([seat]))

    recipients = {call[0][0] for call in sent}
    assert recipients == {"ana@example.com", "candidate@example.com"}


def test_manual_scheduling_emails_the_recruiter_not_the_candidate(sent):
    p = _provider()
    request = InterviewRequest(
        request_id="req-1",
        candidate_id="candidate@example.com",
        interview_type="TECHNICAL_ROUND_1",
        required_skills=["python"],
        seniority="MID",
        panelists_required=1,
        status="manual_scheduling_required",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    p.notify_recruiter_manual_scheduling(request, "insufficient interviewer pool")

    assert len(sent) == 1
    (to, _subject, _body), _ = sent[0]
    assert to == "recruiter@example.com"


def test_unresolvable_interviewer_email_is_skipped_not_raised(sent):
    p = _provider()
    seat = InterviewSeat(seat_index=0, interviewer_id="iv-unknown", status="offered")

    p.send_seat_offer(_interview([seat]), seat)  # must not raise

    assert sent == []  # nothing to send to - silently skipped, inbox still recorded
    assert p.for_recipient("iv-unknown")


def test_email_failure_never_propagates_out_of_the_hook(failing_send):
    p = _provider()
    seat = InterviewSeat(seat_index=0, interviewer_id="iv-ana", status="offered")

    p.send_seat_offer(_interview([seat]), seat)  # must not raise despite failing_send

    assert p.for_recipient("iv-ana")  # inbox write still happened
