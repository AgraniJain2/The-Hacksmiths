"""Timezone- and working-hours-aware interval helpers.

Every datetime that flows through the matching engine is normalised to a
timezone-aware UTC instant here. "Working hours" are always interpreted in the
*owner's* IANA timezone and then converted to UTC for comparison, which is what
makes "a 7am-3pm person is never offered a 4pm slot" hold regardless of where the
candidate or the other panellists sit.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from .models import FreeBusyBlock, Round, WorkingHours

UTC = timezone.utc


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as a timezone-aware UTC datetime.

    Naive datetimes are assumed to already be in UTC - the API contract expects
    aware UTC timestamps, this is just a defensive normalisation.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_hhmm(value: str) -> time:
    """Parse ``"09:00"`` / ``"9:00"`` / ``"17:30"`` into a :class:`datetime.time`."""

    hours_str, _, minutes_str = value.strip().partition(":")
    hours, minutes = int(hours_str), int(minutes_str or "0")
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"invalid HH:MM working-hours value: {value!r}")
    return time(hour=hours, minute=minutes)


def working_window_on_date(
    local_day: date, hours: WorkingHours, tz_name: str
) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC instants of ``hours`` on ``local_day``.

    ``local_day`` is a calendar date in the owner's own timezone.
    """

    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(local_day, parse_hhmm(hours.start), tzinfo=tz)
    end_local = datetime.combine(local_day, parse_hhmm(hours.end), tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def is_within_working_hours(
    slot_start: datetime, slot_end: datetime, hours: WorkingHours, tz_name: str
) -> bool:
    """True iff the whole slot fits inside the owner's working hours for that day.

    The owner's local calendar date is taken from ``slot_start``; a slot that
    would spill past the end of that local working day (or start before it) is
    rejected. This is the individual working-hours guarantee - it is checked for
    every panellist against *their own* ``working_hours`` and for the candidate
    against the round's ``default_working_hours``.
    """

    slot_start = ensure_utc(slot_start)
    slot_end = ensure_utc(slot_end)
    local_day = slot_start.astimezone(ZoneInfo(tz_name)).date()
    window_start, window_end = working_window_on_date(local_day, hours, tz_name)
    return window_start <= slot_start and slot_end <= window_end


def intervals_overlap(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Half-open overlap test: do ``[a_start, a_end)`` and ``[b_start, b_end)`` intersect?"""

    return ensure_utc(a_start) < ensure_utc(b_end) and ensure_utc(b_start) < ensure_utc(a_end)


def has_busy_conflict(
    busy: Iterable[FreeBusyBlock], slot_start: datetime, slot_end: datetime, round_: Round
) -> bool:
    """True if any busy block overlaps the slot *expanded by the round's buffers*.

    The buffer is travel/context-switch time the round requires before and after
    the interview; a busy block touching that padding is still a conflict.
    """

    expanded_start = ensure_utc(slot_start) - timedelta(minutes=round_.buffer_minutes_before)
    expanded_end = ensure_utc(slot_end) + timedelta(minutes=round_.buffer_minutes_after)
    for block in busy:
        if intervals_overlap(block.start, block.end, expanded_start, expanded_end):
            return True
    return False


def buffered_interval(
    slot_start: datetime, slot_end: datetime, round_: Round
) -> tuple[datetime, datetime]:
    """The slot expanded by the round's before/after buffers.

    This is the interval reserved on an interviewer's row when a seat offer is
    created, so two interviews whose padded times overlap can't land on the same
    person.
    """

    return (
        ensure_utc(slot_start) - timedelta(minutes=round_.buffer_minutes_before),
        ensure_utc(slot_end) + timedelta(minutes=round_.buffer_minutes_after),
    )


def iter_slot_starts(
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    granularity: timedelta,
) -> Iterator[datetime]:
    """Yield candidate start instants at ``granularity`` steps such that the whole
    interview (``duration``) finishes on or before ``window_end``.
    """

    cursor = ensure_utc(window_start)
    window_end = ensure_utc(window_end)
    if granularity <= timedelta(0):
        raise ValueError("granularity must be positive")
    while cursor + duration <= window_end:
        yield cursor
        cursor += granularity
