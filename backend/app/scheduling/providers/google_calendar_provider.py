"""Real ``CalendarProvider`` - Phase 3 (Documentation/IMPLEMENTATION_PLAN.md).

Calls Google Calendar's ``freebusy.query`` for an interviewer's own primary
calendar, using the *interviewer's own* token via
``google_oauth.get_valid_access_token`` - the one hard rule in
ARCHITECTURE.md ("feature modules never talk to Google or hold tokens
directly"). Only ever called for ``owner_type="interviewer"`` in practice;
candidates submit availability directly and have no calendar here (see the
``CalendarProvider`` ABC's own docstring) - ``owner_id`` for an interviewer
call is their ``User.id``, the same id ``InterviewerProfile.user_id`` and
every ``InterviewSlotOffer``/``InterviewParticipant`` row already key on.

A dead connection (``ReauthRequired``) is *not* re-raised - it's reported as
``FreeBusyResponse.reauth_required=True`` with an empty busy list, so
``feasibility.py`` can exclude that one interviewer from this computation
without crashing the whole request for everyone else, and without silently
treating "couldn't check" as "confirmed free." Same for a transient Calendar
API error (rate limit, timeout, ...) - conservative, not a 500.
"""

from __future__ import annotations

import logging
from typing import Literal

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.auth.google_oauth import ReauthRequired, get_valid_access_token

from ..models import FreeBusyBlock, FreeBusyResponse, TimeRange
from .interfaces import CalendarProvider

logger = logging.getLogger(__name__)


class GoogleCalendarProvider(CalendarProvider):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_free_busy(
        self,
        owner_id: str,
        owner_type: Literal["candidate", "interviewer"],
        time_range: TimeRange,
    ) -> FreeBusyResponse:
        if owner_type == "candidate":
            # Nothing should call this for a candidate today (see module
            # docstring), but degrade safely (empty busy, not reauth) rather
            # than crash if something ever does - a candidate has no
            # OAuthToken row to look up.
            return FreeBusyResponse(
                owner_id=owner_id, owner_type=owner_type, timezone="UTC",
                busy=[], queried_range=time_range,
            )

        try:
            access_token = get_valid_access_token(self.db, owner_id)
        except ReauthRequired:
            logger.info("Skipping calendar check for %s - Google connection is dead", owner_id)
            return FreeBusyResponse(
                owner_id=owner_id, owner_type=owner_type, timezone="UTC",
                busy=[], queried_range=time_range, reauth_required=True,
            )

        try:
            credentials = Credentials(token=access_token)
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            body = {
                "timeMin": time_range.start.isoformat(),
                "timeMax": time_range.end.isoformat(),
                "items": [{"id": "primary"}],
            }
            result = service.freebusy().query(body=body).execute()
            calendar_result = result.get("calendars", {}).get("primary", {})
            if calendar_result.get("errors"):
                # Google accepted the request but couldn't read *this*
                # calendar (e.g. the grant was revoked server-side without
                # our refresh token noticing yet) - same conservative
                # treatment as ReauthRequired, not a crash.
                logger.warning(
                    "freebusy.query returned an error for %s: %s", owner_id, calendar_result["errors"]
                )
                return FreeBusyResponse(
                    owner_id=owner_id, owner_type=owner_type, timezone="UTC",
                    busy=[], queried_range=time_range, reauth_required=True,
                )
            busy = [
                FreeBusyBlock(start=b["start"], end=b["end"])
                for b in calendar_result.get("busy", [])
            ]
        except HttpError as exc:
            logger.warning("Calendar freebusy query failed for %s: %s", owner_id, exc)
            # Transient/API-side failure, not necessarily a dead connection -
            # still can't confirm free, so still exclude rather than guess.
            return FreeBusyResponse(
                owner_id=owner_id, owner_type=owner_type, timezone="UTC",
                busy=[], queried_range=time_range, reauth_required=True,
            )

        return FreeBusyResponse(
            owner_id=owner_id,
            owner_type=owner_type,
            timezone="UTC",
            busy=busy,
            queried_range=time_range,
        )
