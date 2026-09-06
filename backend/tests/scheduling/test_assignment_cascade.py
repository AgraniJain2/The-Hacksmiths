from __future__ import annotations

from datetime import timedelta

from app.scheduling.assignment import PanelAssignmentAgent
from app.scheduling.config import AssignmentConfig, SchedulingConfig
from app.scheduling.pipeline import assign_panel, find_feasible_slots
from app.scheduling.reservations import ReservationLedger
from app.scheduling.state_machine import InterviewStateMachine
from app.scheduling.timeutils import buffered_interval


class _RaceLosingLedger(ReservationLedger):
    """Wraps a real ledger but makes the *first* `reserve()` attempt for one
    specific interviewer raise, exactly as a real `DbReservationLedger` would
    if a *different*, concurrent interview's reserve() call landed between
    this seat's own `is_free()` pre-check and its `reserve()` call (Phase 6 -
    Documentation/IMPLEMENTATION_PLAN.md). Everyone else, and this same
    interviewer on any later attempt, behaves normally."""

    def __init__(self, loses_race_for: str) -> None:
        super().__init__()
        self._loses_race_for = loses_race_for
        self._raised_once = False

    def reserve(self, interviewer_id, interview_id, seat_index, start, end):
        if interviewer_id == self._loses_race_for and not self._raised_once:
            self._raised_once = True
            raise ValueError(f"simulated concurrent reservation for {interviewer_id}")
        super().reserve(interviewer_id, interview_id, seat_index, start, end)


def _setup(scn, config=None):
    config = config or SchedulingConfig()
    reservations = ReservationLedger()
    feas = find_feasible_slots(
        scn.request, scn.round_,
        interviewer_repo=scn.interviewer_repo, availability_repo=scn.availability_repo,
        calendar=scn.calendar, notifier=scn.notifier, config=config, now=scn.now,
    )
    chosen = feas.feasibility.feasible_slots[0]
    panel = assign_panel(
        feas.request, scn.round_, feas.feasibility, chosen.slot_id,
        interviewer_repo=scn.interviewer_repo, calendar=scn.calendar,
        load_provider=scn.load_provider, notifier=scn.notifier,
        reservations=reservations, config=config, now=scn.now,
    )
    agent = PanelAssignmentAgent(
        load_provider=scn.load_provider, reservations=reservations,
        notifier=scn.notifier, config=config,
    )
    sm = InterviewStateMachine(reservations, scn.notifier, agent)
    return reservations, agent, sm, panel, chosen


def test_parallel_offers_go_to_distinct_lowest_load_interviewers(panel_scenario):
    _, _, _, panel, _ = _setup(panel_scenario)
    assert panel.status == "assigning_panel"
    offered = [s.interviewer_id for s in panel.interview.seats]
    assert sorted(offered) == ["iv-p1", "iv-p2", "iv-p3"]  # p4 has the highest load
    assert len(set(offered)) == 3
    assert all(s.status == "offered" for s in panel.interview.seats)


def test_reservation_is_held_at_offer_and_released_on_decline(interviewer_cancel_refill):
    scn = interviewer_cancel_refill
    reservations, _, sm, panel, chosen = _setup(scn)
    b_start, b_end = buffered_interval(chosen.start, chosen.end, scn.round_)
    assert not reservations.is_free("iv-s1", b_start, b_end)  # held by the offer

    out = sm.respond_to_seat(
        interview=panel.interview, request=panel.request, round_=scn.round_,
        seat_index=0, accepted=False, feasible_ids_at_slot=panel.feasible_ids_at_slot, now=scn.now,
    )
    # s1's reservation is gone; the seat cascaded to s3 (next lowest load)
    seat0 = out.interview.seats[0]
    assert seat0.interviewer_id == "iv-s3"
    assert seat0.status == "offered"
    assert "iv-s1" in seat0.declined_interviewer_ids
    assert not reservations.is_free("iv-s3", b_start, b_end)


def test_all_accept_completes_the_panel(interviewer_cancel_refill):
    scn = interviewer_cancel_refill
    _, _, sm, panel, _ = _setup(scn)
    interview, request = panel.interview, panel.request
    for seat in list(interview.seats):
        out = sm.respond_to_seat(
            interview=interview, request=request, round_=scn.round_,
            seat_index=seat.seat_index, accepted=True,
            feasible_ids_at_slot=panel.feasible_ids_at_slot, now=scn.now,
        )
        interview, request = out.interview, out.request
    assert out.status == "panel_complete"
    assert sorted(interview.panel) == ["iv-s1", "iv-s2"]
    assert "panel_complete" in scn.notifier.kinds()


def test_seat_pool_exhaustion_escalates_to_manual(seat_cascade_exhaustion):
    scn = seat_cascade_exhaustion
    _, _, sm, panel, _ = _setup(scn)
    # feasible at the slot is exactly {s1, s2}; s1 holds seat0, s2 holds seat1.
    out = sm.respond_to_seat(
        interview=panel.interview, request=panel.request, round_=scn.round_,
        seat_index=0, accepted=False, feasible_ids_at_slot=panel.feasible_ids_at_slot, now=scn.now,
    )
    assert out.status == "manual_scheduling_required"
    assert out.interview.seats[0].status == "exhausted"
    assert out.request.status == "manual_scheduling_required"
    assert scn.notifier.manual_escalations
    assert "exhausted" in scn.notifier.manual_escalations[0].reason


def test_offer_timeout_cascades_to_next_ranked(interviewer_cancel_refill):
    scn = interviewer_cancel_refill
    config = SchedulingConfig(assignment=AssignmentConfig(offer_timeout_minutes=60))
    _, _, sm, panel, _ = _setup(scn, config)

    # s2 accepts seat 1 promptly; only seat 0 (s1) is left outstanding.
    accepted = sm.respond_to_seat(
        interview=panel.interview, request=panel.request, round_=scn.round_,
        seat_index=1, accepted=True, feasible_ids_at_slot=panel.feasible_ids_at_slot, now=scn.now,
    )

    later = scn.now + timedelta(minutes=90)
    out = sm.process_offer_timeouts(
        interview=accepted.interview, request=accepted.request, round_=scn.round_,
        feasible_ids_at_slot=panel.feasible_ids_at_slot, now=later,
    )
    seat0 = out.interview.seats[0]
    assert "iv-s1" in seat0.declined_interviewer_ids
    assert seat0.interviewer_id == "iv-s3"
    assert out.interview.seats[1].status == "accepted"  # untouched
    assert any(
        r.kind == "seat_released" and "did not respond" in (r.reason or "")
        for r in scn.notifier.records
    )


def test_losing_the_reservation_race_cascades_to_the_next_candidate_not_a_crash(normal_single):
    """Phase 6: a real concurrency stress test (tests/scheduling_service/
    test_concurrent_bookings.py) found that fill_pending_seats used to let
    ReservationLedger.reserve()'s ValueError propagate straight out of the
    whole assignment call instead of falling back to the next-ranked
    candidate - crashing the request instead of just losing the race
    gracefully. This reproduces the exact race deterministically, without
    needing real threads."""
    scn = normal_single
    config = SchedulingConfig()
    feas = find_feasible_slots(
        scn.request, scn.round_,
        interviewer_repo=scn.interviewer_repo, availability_repo=scn.availability_repo,
        calendar=scn.calendar, notifier=scn.notifier, config=config, now=scn.now,
    )
    # normal_single's earliest slot only has iv-ben free (iv-ana is busy until
    # 11:00 that day - see fixtures.py) - find a later slot where both are
    # feasible, so there's an actual second-ranked candidate to cascade to.
    chosen = next(s for s in feas.feasibility.feasible_slots if set(s.feasible_interviewer_ids) == {"iv-ana", "iv-ben"})

    # iv-ben is the lowest-load pick (would normally win seat 0) - force
    # *their* first reserve() to simulate losing a concurrent race.
    # (assign_panel builds its own PanelAssignmentAgent/InterviewStateMachine
    # internally from the `reservations=` ledger passed in below.)
    ledger = _RaceLosingLedger(loses_race_for="iv-ben")

    panel = assign_panel(
        feas.request, scn.round_, feas.feasibility, chosen.slot_id,
        interviewer_repo=scn.interviewer_repo, calendar=scn.calendar,
        load_provider=scn.load_provider, notifier=scn.notifier,
        reservations=ledger, config=config, now=scn.now,
    )

    # Must not raise, and must have cascaded to the *other* feasible
    # candidate rather than leaving the seat unfilled or crashing.
    assert panel.status == "assigning_panel"
    seat = panel.interview.seats[0]
    assert seat.status == "offered"
    assert seat.interviewer_id == "iv-ana"
