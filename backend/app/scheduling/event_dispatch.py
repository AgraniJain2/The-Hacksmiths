"""Module 7 - Event Creation & Dispatch (Phase 4), extended in Phase 5
(Module 8) to keep the real Calendar event in sync with cancellations and
send reminders - Documentation/IMPLEMENTATION_PLAN.md.

Once every seat is ``ACCEPTED`` (``Interview.status == "panel_complete"``),
create the real Google Calendar event (Meet link via ``conferenceData``) and
send a confirmation email with an ``.ics`` fallback to every attendee.
Called again (idempotently) if a confirmed interviewer later cancels and a
replacement is found - the *same* function then patches the existing
event's attendee list instead of creating a second one.

Deliberately **not** inside the pure engine (``assignment.py``/
``state_machine.py``/``escalation.py`` never call anything here - see those
modules' own docstrings: event creation is teammate/service-owned, not
engine logic) and **not** folded into ``NotificationProvider`` (Phase 1)
either - those hooks fire *from inside* the engine's own state transitions,
before any real event exists; everything here is a separate, later step
called by ``service.py``/``jobs.py`` once a transition has already landed,
using the *real* event/Meet link this module produces.

Every Google/email failure anywhere in this module is logged and swallowed,
never raised past a public function - the booking/cancellation itself is
already durable in the DB by the time any of these run; the Calendar event
and its emails are best-effort follow-ups, not what makes a seat "count."
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from icalendar import Calendar, Event, vCalAddress, vText
from sqlalchemy.orm import Session

from app.auth.google_oauth import ReauthRequired, get_valid_access_token
from app.db.models import Interview as InterviewRow
from app.notifications.service import EmailSendError, send_email

from .models import Interview
from .providers.interfaces import InterviewerRepository

logger = logging.getLogger(__name__)

UTC = timezone.utc


def _calendar_service(db: Session, organizer_id: Optional[str], *, interview_id: str):
    """Returns a real Calendar API client for the organizer, or None if their
    connection is dead - logged, never raised, every caller treats None as
    "skip the Google-side step, the DB state is still correct." """
    if not organizer_id:
        logger.warning("No organizer (created_by) on interview %s - skipping Calendar call", interview_id)
        return None
    try:
        access_token = get_valid_access_token(db, organizer_id)
    except ReauthRequired:
        logger.warning(
            "Organizer %s has a dead Google connection - skipping Calendar call for %s",
            organizer_id, interview_id,
        )
        return None
    credentials = Credentials(token=access_token)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _attendee_emails(row: InterviewRow, interview: Interview, interviewer_repo: InterviewerRepository) -> List[str]:
    emails: List[str] = []
    if row.candidate_email:
        emails.append(row.candidate_email)
    if row.hiring_manager_email:
        emails.append(row.hiring_manager_email)
    for interviewer_id in interview.panel:  # confirmed seats only
        try:
            emails.append(interviewer_repo.get_interviewer(interviewer_id).email)
        except Exception:  # noqa: BLE001 - a missing profile shouldn't break the others' invite
            logger.warning("Couldn't resolve email for confirmed interviewer %s", interviewer_id)
    return emails


def _build_ics(interview: Interview, attendee_emails: List[str], organizer_email: str, *, cancelled: bool = False) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//WorkHire//Interview Scheduler//EN")
    cal.add("version", "2.0")
    cal.add("method", "CANCEL" if cancelled else "REQUEST")

    event = Event()
    event.add("summary", f"{interview.interview_type.replace('_', ' ')} interview")
    event.add("dtstart", interview.slot_start)
    event.add("dtend", interview.slot_end)
    event.add("dtstamp", datetime.now(UTC))
    event["uid"] = f"{interview.interview_id}@workhire"
    if cancelled:
        event.add("status", "CANCELLED")

    if organizer_email:
        organizer = vCalAddress(f"MAILTO:{organizer_email}")
        organizer.params["cn"] = vText(organizer_email)
        event["organizer"] = organizer
    for email in attendee_emails:
        attendee = vCalAddress(f"MAILTO:{email}")
        attendee.params["role"] = vText("REQ-PARTICIPANT")
        event.add("attendee", attendee, encode=0)
    if interview.meet_link and not cancelled:
        event.add("location", interview.meet_link)
        event.add("description", f"Join: {interview.meet_link}")

    cal.add_component(event)
    return cal.to_ical()


# --------------------------------------------------------------------------- #
# Module 7 - create (or, on a later re-fill, sync) the confirmed booking
# --------------------------------------------------------------------------- #


def dispatch_confirmed_booking(
    db: Session,
    row: InterviewRow,
    interview: Interview,
    interviewer_repo: InterviewerRepository,
) -> Interview:
    """Create the real Calendar event the first time a panel completes, or -
    if one already exists (a confirmed interviewer cancelled post-booking and
    a replacement was just found, Phase 5) - patch its attendee list to match
    the *current* confirmed roster instead of creating a second event.
    Returns the (possibly updated) engine `Interview` with
    `calendar_event_id`/`meet_link` filled in - callers should use this
    return value, not the one they passed in, for anything built after this
    call (e.g. the HTTP response).
    """

    attendee_emails = _attendee_emails(row, interview, interviewer_repo)
    calendar_service = _calendar_service(db, row.created_by, interview_id=row.id)
    if calendar_service is None:
        return interview

    if row.calendar_event_id:
        return _sync_event_attendees(db, row, interview, calendar_service, attendee_emails)
    return _create_event(db, row, interview, calendar_service, attendee_emails)


def _create_event(db, row, interview, calendar_service, attendee_emails: List[str]) -> Interview:
    try:
        body = {
            "summary": f"{interview.interview_type.replace('_', ' ')} interview",
            # `timeZone` is required by the real Calendar API even though the
            # dateTime string carries a UTC offset - found by an actual
            # events.insert call against a real account during Phase 4's
            # manual verification, not by inspection (see IMPLEMENTATION_PLAN.md).
            "start": {"dateTime": interview.slot_start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": interview.slot_end.isoformat(), "timeZone": "UTC"},
            "attendees": [{"email": e} for e in attendee_emails],
            "conferenceData": {
                "createRequest": {
                    "requestId": row.id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        result = (
            calendar_service.events()
            .insert(calendarId="primary", body=body, conferenceDataVersion=1, sendUpdates="none")
            .execute()
        )
    except HttpError as exc:
        logger.warning("events.insert failed for interview %s: %s", row.id, exc)
        return interview

    event_id = result.get("id")
    meet_link = None
    for entry_point in result.get("conferenceData", {}).get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            meet_link = entry_point.get("uri")
            break

    row.calendar_event_id = event_id
    row.meeting_link = meet_link
    db.commit()

    interview = interview.model_copy(update={"calendar_event_id": event_id, "meet_link": meet_link})
    _send_confirmation_emails(row, interview, attendee_emails)
    return interview


def _sync_event_attendees(db, row, interview, calendar_service, attendee_emails: List[str]) -> Interview:
    """A confirmed interviewer already left (their own `events.patch` ran via
    `remove_attendee_from_event` at cancellation time) and the cascade has
    now found - or exhausted looking for - a replacement. Patch the existing
    event's attendee list to match the current roster exactly, rather than
    trying to track "add this one, remove that one" as two separate calls."""
    # The caller's `interview` may be stale on these two fields (e.g. built
    # from a row fetched before the event ever existed) - `row` is always
    # current, so always return an Interview reflecting it, same as
    # `_create_event` does explicitly after its own insert.
    interview = interview.model_copy(
        update={"calendar_event_id": row.calendar_event_id, "meet_link": row.meeting_link}
    )
    try:
        calendar_service.events().patch(
            calendarId="primary",
            eventId=row.calendar_event_id,
            body={"attendees": [{"email": e} for e in attendee_emails]},
            sendUpdates="none",
        ).execute()
    except HttpError as exc:
        logger.warning("events.patch (attendee sync) failed for interview %s: %s", row.id, exc)
        return interview

    _send_confirmation_emails(row, interview, attendee_emails)
    return interview


def _send_confirmation_emails(row: InterviewRow, interview: Interview, attendee_emails: List[str]) -> None:
    organizer_email = row.created_by_email or ""
    ics_bytes = _build_ics(interview, attendee_emails, organizer_email)
    subject = f"Confirmed — {interview.interview_type.replace('_', ' ')} interview"
    when = interview.slot_start.isoformat()
    meet_line = (
        f'<p>Join via Google Meet: <a href="{interview.meet_link}">{interview.meet_link}</a></p>'
        if interview.meet_link
        else ""
    )
    body_html = (
        f"<p>Your interview is confirmed for <strong>{when}</strong>.</p>"
        f"{meet_line}"
        "<p>A calendar invite (.ics) is attached — add it to your calendar of choice.</p>"
    )
    for to in attendee_emails:
        try:
            send_email(to, subject, body_html, ics_attachment=ics_bytes, ics_filename="interview.ics")
        except EmailSendError:
            logger.warning("Confirmation email failed for %s (interview %s)", to, row.id, exc_info=True)


# --------------------------------------------------------------------------- #
# Module 8 (Phase 5) - cancellation touches the real event too
# --------------------------------------------------------------------------- #


def cancel_event(
    db: Session,
    row: InterviewRow,
    interview: Interview,
    interviewer_repo: InterviewerRepository,
    reason: str,
) -> None:
    """Candidate cancel/reschedule: the whole booking is off - delete the
    real event (not just mark it internally) and notify every attendee.
    No-op if there was never a real event (e.g. cancelled before Module 7
    ran).

    Reads the event id off `interview` (the caller's pre-cancellation
    snapshot), not `row.calendar_event_id` - a reschedule clears the row's
    own field *before* calling this (so a later `dispatch_confirmed_booking`
    creates a fresh event instead of trying to sync a deleted one), and this
    must still know which event to actually delete."""
    event_id = interview.calendar_event_id
    if not event_id:
        return
    attendee_emails = _attendee_emails(row, interview, interviewer_repo)
    calendar_service = _calendar_service(db, row.created_by, interview_id=row.id)
    if calendar_service is not None:
        try:
            calendar_service.events().delete(
                calendarId="primary", eventId=event_id, sendUpdates="none"
            ).execute()
        except HttpError as exc:
            # 410 Gone means someone already deleted it (e.g. manually) -
            # that's the outcome we wanted anyway, not a real failure.
            if getattr(exc, "status_code", None) != 410 and getattr(exc.resp, "status", None) != 410:
                logger.warning("events.delete failed for interview %s: %s", row.id, exc)

    subject = f"Cancelled — {interview.interview_type.replace('_', ' ')} interview"
    body_html = f"<p>This interview has been cancelled: {reason}</p>"
    ics_bytes = _build_ics(interview, attendee_emails, row.created_by_email or "", cancelled=True)
    for to in attendee_emails:
        try:
            send_email(to, subject, body_html, ics_attachment=ics_bytes, ics_filename="cancelled.ics")
        except EmailSendError:
            logger.warning("Cancellation email failed for %s (interview %s)", to, row.id, exc_info=True)


def remove_attendee_from_event(db: Session, row: InterviewRow, departing_email: Optional[str]) -> None:
    """A single confirmed interviewer backs out (Stage 8's per-seat cancel) -
    drop just them from the existing event immediately, independent of
    whether/when a replacement is found (that's `dispatch_confirmed_booking`'s
    job, once the cascade lands on someone). No-op if there's no real event
    yet, no departing email to remove, or the organizer's connection is dead."""
    if not row.calendar_event_id or not departing_email:
        return
    calendar_service = _calendar_service(db, row.created_by, interview_id=row.id)
    if calendar_service is None:
        return
    try:
        event = calendar_service.events().get(calendarId="primary", eventId=row.calendar_event_id).execute()
        remaining = [a for a in event.get("attendees", []) if a.get("email") != departing_email]
        calendar_service.events().patch(
            calendarId="primary", eventId=row.calendar_event_id,
            body={"attendees": remaining}, sendUpdates="none",
        ).execute()
    except HttpError as exc:
        logger.warning("Removing %s from interview %s's event failed: %s", departing_email, row.id, exc)


# --------------------------------------------------------------------------- #
# Module 8 (Phase 5) - reminders
# --------------------------------------------------------------------------- #


def send_reminder(row: InterviewRow, interview: Interview, interviewer_repo: InterviewerRepository) -> None:
    attendee_emails = _attendee_emails(row, interview, interviewer_repo)
    subject = f"Reminder — {interview.interview_type.replace('_', ' ')} interview soon"
    when = interview.slot_start.isoformat()
    meet_line = (
        f'<p>Join via Google Meet: <a href="{interview.meet_link}">{interview.meet_link}</a></p>'
        if interview.meet_link
        else ""
    )
    body_html = f"<p>Reminder: your interview is coming up at <strong>{when}</strong>.</p>{meet_line}"
    for to in attendee_emails:
        try:
            send_email(to, subject, body_html)
        except EmailSendError:
            logger.warning("Reminder email failed for %s (interview %s)", to, row.id, exc_info=True)
