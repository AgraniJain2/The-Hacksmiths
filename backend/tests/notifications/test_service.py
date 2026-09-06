from __future__ import annotations

import pytest

import app.notifications.service as service
from app.notifications.service import EmailSendError, send_email


class _Response:
    def __init__(self, status_code: int, text: str = "{}"):
        self.status_code = status_code
        self.text = text


def test_send_email_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Response(200)

    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(service.settings, "RESEND_FROM_EMAIL", "WorkHire <test@example.com>")
    monkeypatch.setattr(service.requests, "post", fake_post)

    send_email("candidate@example.com", "Subject line", "<p>Body</p>")

    assert captured["url"] == service.RESEND_API_URL
    assert captured["json"]["to"] == ["candidate@example.com"]
    assert captured["json"]["subject"] == "Subject line"
    assert captured["json"]["html"] == "<p>Body</p>"
    assert captured["json"]["from"] == "WorkHire <test@example.com>"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in str(captured["json"])  # never in the body, only the auth header


def test_send_email_includes_base64_ics_attachment(monkeypatch):
    captured = {}
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(service.requests, "post", lambda url, json, headers, timeout: (captured.update(json=json), _Response(200))[1])

    send_email("a@example.com", "Subj", "<p>x</p>", ics_attachment=b"BEGIN:VCALENDAR", ics_filename="invite.ics")

    attachment = captured["json"]["attachments"][0]
    assert attachment["filename"] == "invite.ics"
    import base64
    assert base64.b64decode(attachment["content"]) == b"BEGIN:VCALENDAR"


def test_send_email_skips_without_configured_key(monkeypatch):
    calls = []
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(service.requests, "post", lambda *a, **k: calls.append(1))

    send_email("a@example.com", "Subj", "<p>x</p>")  # must not raise

    assert calls == []  # never called Resend at all


def test_send_email_raises_on_non_2xx(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(service.requests, "post", lambda *a, **k: _Response(422, "bad payload"))

    with pytest.raises(EmailSendError, match="422"):
        send_email("a@example.com", "Subj", "<p>x</p>")


def test_send_email_raises_on_network_failure(monkeypatch):
    import requests as real_requests

    def raise_network_error(*a, **k):
        raise real_requests.ConnectionError("boom")

    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(service.requests, "post", raise_network_error)

    with pytest.raises(EmailSendError, match="Resend request failed"):
        send_email("a@example.com", "Subj", "<p>x</p>")
