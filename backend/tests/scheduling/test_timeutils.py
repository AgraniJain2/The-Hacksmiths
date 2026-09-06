from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.scheduling.models import FreeBusyBlock, Round, WorkingHours
from app.scheduling.timeutils import (
    buffered_interval,
    ensure_utc,
    has_busy_conflict,
    is_within_working_hours,
    iter_slot_starts,
    parse_hhmm,
    working_window_on_date,
)

UTC = timezone.utc
ROUND = Round(
    round_id="r",
    interview_type="T",
    duration_minutes=60,
    buffer_minutes_before=15,
    buffer_minutes_after=15,
    default_working_hours=WorkingHours(start="09:00", end="18:00"),
)


def test_parse_hhmm():
    assert parse_hhmm("09:00").hour == 9
    assert parse_hhmm("7:30") == parse_hhmm("07:30")
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def test_ensure_utc_naive_treated_as_utc():
    naive = datetime(2026, 9, 7, 10, 0)
    assert ensure_utc(naive) == datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def test_working_window_london_is_bst_in_september():
    # 09:00-18:00 Europe/London on 2026-09-07 is BST (UTC+1) -> 08:00-17:00 UTC.
    start, end = working_window_on_date(
        datetime(2026, 9, 7).date(), WorkingHours(start="09:00", end="18:00"), "Europe/London"
    )
    assert start == datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 7, 17, 0, tzinfo=UTC)


def test_seven_to_three_person_is_never_offered_a_four_pm_slot():
    hours = WorkingHours(start="07:00", end="15:00")  # local
    tz = "America/New_York"  # EDT (UTC-4) on this date
    four_pm_local = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)  # 16:00 EDT
    assert not is_within_working_hours(
        four_pm_local, four_pm_local + timedelta(hours=1), hours, tz
    )
    ten_am_local = datetime(2026, 9, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT
    assert is_within_working_hours(
        ten_am_local, ten_am_local + timedelta(hours=1), hours, tz
    )


def test_slot_that_spills_past_end_of_working_day_is_rejected():
    hours = WorkingHours(start="09:00", end="17:00")
    start = datetime(2026, 9, 7, 16, 30, tzinfo=UTC)  # UTC tz owner
    assert not is_within_working_hours(start, start + timedelta(hours=1), hours, "UTC")


def test_busy_conflict_includes_buffer_padding():
    slot_start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    slot_end = slot_start + timedelta(hours=1)
    # Busy block ends exactly at slot start -> the 15m pre-buffer still overlaps it.
    touching = [FreeBusyBlock(start=slot_start - timedelta(hours=1), end=slot_start)]
    assert has_busy_conflict(touching, slot_start, slot_end, ROUND)
    # Busy block ending 20 minutes before the slot -> outside the 15m buffer.
    clear = [FreeBusyBlock(start=slot_start - timedelta(hours=1), end=slot_start - timedelta(minutes=20))]
    assert not has_busy_conflict(clear, slot_start, slot_end, ROUND)


def test_buffered_interval_expands_by_round_buffers():
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    end = datetime(2026, 9, 7, 11, 0, tzinfo=UTC)
    b_start, b_end = buffered_interval(start, end, ROUND)
    assert b_start == datetime(2026, 9, 7, 9, 45, tzinfo=UTC)
    assert b_end == datetime(2026, 9, 7, 11, 15, tzinfo=UTC)


def test_iter_slot_starts_bounds_and_step():
    start = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    end = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    starts = list(iter_slot_starts(start, end, timedelta(minutes=60), timedelta(minutes=30)))
    assert starts[0] == start
    assert starts[-1] == datetime(2026, 9, 7, 11, 0, tzinfo=UTC)  # 11:00 + 60m == 12:00
    assert all((b - a) == timedelta(minutes=30) for a, b in zip(starts, starts[1:]))
