from __future__ import annotations

from datetime import datetime, timezone

from app.scheduling.pipeline import assign_panel, find_feasible_slots, run_happy_path
from app.scheduling.reservations import ReservationLedger

UTC = timezone.utc


def _find(scn):
    return find_feasible_slots(
        scn.request, scn.round_,
        interviewer_repo=scn.interviewer_repo, availability_repo=scn.availability_repo,
        calendar=scn.calendar, notifier=scn.notifier, now=scn.now,
    )


def test_find_feasible_slots_normal(normal_single):
    out = _find(normal_single)
    assert out.status == "awaiting_candidate_selection"
    assert out.request.status == "awaiting_candidate_selection"
    assert out.feasibility.feasible_slots
    assert normal_single.notifier.manual_escalations == []


def test_find_feasible_slots_escalates_when_nothing_feasible(no_feasible_slot):
    out = _find(no_feasible_slot)
    assert out.status == "manual_scheduling_required"
    assert out.request.status == "manual_scheduling_required"
    assert "no time in the candidate's submitted availability" in out.reason
    assert no_feasible_slot.notifier.manual_escalations


def test_find_feasible_slots_escalates_on_insufficient_pool(insufficient_pool):
    out = _find(insufficient_pool)
    assert out.status == "manual_scheduling_required"
    assert "1 eligible & active, 3 required" in out.reason


def test_assign_panel_rejects_unknown_slot_id(normal_single):
    feas = _find(normal_single)
    import pytest

    with pytest.raises(ValueError):
        assign_panel(
            feas.request, normal_single.round_, feas.feasibility, "not-a-slot",
            interviewer_repo=normal_single.interviewer_repo, calendar=normal_single.calendar,
            load_provider=normal_single.load_provider, notifier=normal_single.notifier,
            reservations=ReservationLedger(), now=normal_single.now,
        )


def test_happy_path_normal_single_books_lowest_load_interviewer(normal_single):
    feas, panel = run_happy_path(
        normal_single.request, normal_single.round_,
        interviewer_repo=normal_single.interviewer_repo, availability_repo=normal_single.availability_repo,
        calendar=normal_single.calendar, load_provider=normal_single.load_provider,
        notifier=normal_single.notifier, now=normal_single.now,
    )
    assert feas.status == "awaiting_candidate_selection"
    assert panel.status == "panel_complete"
    assert panel.interview.panel == ["iv-ben"]  # lowest rolling load
    assert panel.interview.slot_start == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    assert panel.interview.hiring_manager_email == "hm@example.com"
    kinds = normal_single.notifier.kinds()
    assert "seat_offer" in kinds and "seat_filled" in kinds and "panel_complete" in kinds


def test_happy_path_panel_offers_three_lowest_load(panel_scenario):
    feas, panel = run_happy_path(
        panel_scenario.request, panel_scenario.round_,
        interviewer_repo=panel_scenario.interviewer_repo, availability_repo=panel_scenario.availability_repo,
        calendar=panel_scenario.calendar, load_provider=panel_scenario.load_provider,
        notifier=panel_scenario.notifier, now=panel_scenario.now,
    )
    assert panel.status == "panel_complete"
    assert sorted(panel.interview.panel) == ["iv-p1", "iv-p2", "iv-p3"]


def test_happy_path_escalation_scenarios_return_no_panel(no_feasible_slot, insufficient_pool):
    for scn in (no_feasible_slot, insufficient_pool):
        feas, panel = run_happy_path(
            scn.request, scn.round_,
            interviewer_repo=scn.interviewer_repo, availability_repo=scn.availability_repo,
            calendar=scn.calendar, load_provider=scn.load_provider,
            notifier=scn.notifier, now=scn.now,
        )
        assert feas.status == "manual_scheduling_required"
        assert panel is None
        assert scn.notifier.manual_escalations


def test_reservations_shared_across_two_requests_prevent_double_booking(panel_scenario):
    """Two interviews that need the same person at overlapping times can't both get them."""
    scn = panel_scenario
    ledger = ReservationLedger()

    feas = _find(scn)
    chosen = feas.feasibility.feasible_slots[0]
    first = assign_panel(
        feas.request, scn.round_, feas.feasibility, chosen.slot_id,
        interviewer_repo=scn.interviewer_repo, calendar=scn.calendar,
        load_provider=scn.load_provider, notifier=scn.notifier, reservations=ledger, now=scn.now,
    )
    reserved = set(first.interview.panel or [s.interviewer_id for s in first.interview.seats])

    # A second request for the SAME slot, same ledger: the already-reserved people
    # are excluded from the live recompute, so only iv-p4 remains -> < 3 -> escalate.
    second = assign_panel(
        feas.request.model_copy(update={"request_id": "req-panel-2"}),
        scn.round_, feas.feasibility, chosen.slot_id,
        interviewer_repo=scn.interviewer_repo, calendar=scn.calendar,
        load_provider=scn.load_provider, notifier=scn.notifier, reservations=ledger, now=scn.now,
    )
    assert second.status == "manual_scheduling_required"
    assert "live recompute" in second.reason
