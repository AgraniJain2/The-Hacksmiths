"""Resend-backed email sending — the one place any module sends an email
from (MODULE_GUIDE.md's shared Notification Service section): invite emails
(Module 2), offer/confirmation/cancellation notices (``provider.py``), and
eventually reminders + the `.ics` confirmation (Module 7/8 — not yet built).

Never reimplement an HTTP call to Resend at a call site — import
:func:`send_email` instead.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 10


class EmailSendError(Exception):
    """Resend rejected the request, or it never reached Resend at all.

    Callers that are inside a user-facing request/response (e.g. creating an
    interview request) should catch this and degrade gracefully — log it and
    keep going — never let a notification failure turn into a 500 for an
    action that otherwise fully succeeded. See ``provider.py``'s hooks, which
    do exactly this for every engine-triggered notification.
    """


def send_email(
    to: str,
    subject: str,
    body_html: str,
    *,
    ics_attachment: Optional[bytes] = None,
    ics_filename: str = "invite.ics",
) -> None:
    """Send one email via Resend's ``POST /emails``. Raises :class:`EmailSendError`
    on any failure — network, auth, or Resend rejecting the payload. Does
    nothing (logs and returns) if ``RESEND_API_KEY`` isn't configured, so a
    blank/dev-only key never breaks the feature that's calling this — see
    CONVENTIONS.md's secrets rule for why this is a config value, not a literal.
    """

    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — skipping email to %s (%r)", to, subject)
        return

    payload: dict = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": body_html,
    }
    if ics_attachment is not None:
        payload["attachments"] = [
            {
                "filename": ics_filename,
                "content": base64.b64encode(ics_attachment).decode("ascii"),
            }
        ]

    try:
        response = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Never log settings.RESEND_API_KEY or any header — CONVENTIONS.md's
        # logging rule. The exception text from `requests` doesn't include it.
        raise EmailSendError(f"Resend request failed: {exc}") from exc

    if response.status_code >= 300:
        raise EmailSendError(
            f"Resend rejected the email ({response.status_code}): {response.text[:300]}"
        )
