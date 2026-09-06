from __future__ import annotations

from datetime import datetime, timezone

from hacksmiths.scheduler.config import SchedulingConfig
from hacksmiths.scheduler.feasibility import (
    feasible_interviewers_at_fixed_time,
    run_feasibility,
)
from hacksmiths.scheduler.pool import resolve_interviewer_pool

UTC = timezone.utc


def _feasibility(scn):
    pool = resolve_interviewer_pool(scn.request, scn.all_interviewers)
    availability = scn.availability_repo.get_availability(scn.request.request_id)
    return pool, run_feasibility(
        scn.request, scn.round_, pool, availability, scn.calendar, now=scn.now
    )


def test_normal_single_produces_binary_feasible_slots(normal_single):
    _, result = _feasibility(normal_single)
    assert result.feasible_slots
    assert result.no_match_reason is None
    for slot in result.feasible_slots:
        assert slot.feasible_count >= 1
        assert slot.feasible_count == len(slot.feasible_interviewer_ids)
        # no scoring on the slot at all
        assert not hasattr(slot, "score")
    # slots are sorted earliest-first
    starts = [s.start for s in result.feasible_slots]
    assert starts == sorted(starts)


def test_slots_are_bounded_by_candidate_windows_and_interviewer_hours(normal_single):
    _, result = _feasibility(normal_single)
    # Candidate windows are 07:30-13:30 UTC; ben works 09:00-15:00 UTC; ana is
    # busy Mon until 11:00. So the earliest feasible slot is Mon 09:00 (ben only).
    first = result.feasible_slots[0]
    assert first.start == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    assert first.feasible_interviewer_ids == ["iv-ben"]
    # every slot sits inside a candidate window
    for slot in result.feasible_slots:
        assert datetime(2026, 9, 7, 7, 30, tzinfo=UTC).time() <= slot.start.time()
        assert slot.end.time() <= datetime(2026, 9, 7, 13, 30, tzinfo=UTC).time()


def test_interviewer_own_working_hours_enforced_even_with_empty_calendar(normal_single):
    _, result = _feasibility(normal_single)
    # ben's calendar is empty but he works 10:00-16:00 London == 09:00-15:00 UTC.
    for slot in result.feasible_slots:
        if "iv-ben" in slot.feasible_interviewer_ids:
            assert slot.start.astimezone(UTC).hour >= 9
            assert slot.end.astimezone(UTC).hour <= 15


def test_panel_needs_at_least_n_feasible_per_slot(panel_scenario):
    _, result = _feasibility(panel_scenario)
    assert result.feasible_slots
    for slot in result.feasible_slots:
        assert slot.feasible_count >= 3


def test_no_feasible_slot_returns_reason_and_no_slots(no_feasible_slot):
    _, result = _feasibility(no_feasible_slot)
    assert result.feasible_slots == []
    assert "no time in the candidate's submitted availability" in result.no_match_reason


def test_insufficient_pool_short_circuits_feasibility(insufficient_pool):
    _, result = _feasibility(insufficient_pool)
    assert result.feasible_slots == []
    assert "insufficient interviewer pool" in result.no_match_reason


def test_empty_availability_is_reported(normal_single):
    from hacksmiths.scheduler.models import CandidateAvailability

    empty = CandidateAvailability(
        request_id=normal_single.request.request_id,
        candidate_id=normal_single.candidate.candidate_id,
        windows=[],
        submitted_at=normal_single.now,
    )
    pool = resolve_interviewer_pool(normal_single.request, normal_single.all_interviewers)
    result = run_feasibility(
        normal_single.request, normal_single.round_, pool, empty, normal_single.calendar, now=normal_single.now
    )
    assert result.feasible_slots == []
    assert "has not submitted any availability" in result.no_match_reason


def test_fixed_time_recompute_excludes_reserved_interviewers(seat_cascade_exhaustion):
    from hacksmiths.scheduler.reservations import ReservationLedger

    scn = seat_cascade_exhaustion
    pool, result = _feasibility(scn)
    slot = result.feasible_slots[0]
    assert set(slot.feasible_interviewer_ids) == {"iv-s1", "iv-s2"}

    ledger = ReservationLedger()
    # Pretend s1 is already reserved for an overlapping interview.
    ledger.reserve("iv-s1", "other-interview", 0, slot.start, slot.end)
    live = feasible_interviewers_at_fixed_time(
        scn.request, scn.round_, pool, slot.start, slot.end, scn.calendar, ledger, now=scn.now
    )
    assert live == ["iv-s2"]
