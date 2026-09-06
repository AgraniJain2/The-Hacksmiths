from __future__ import annotations

import pytest

from hacksmiths.scheduler.assignment import PanelAssignmentAgent
from hacksmiths.scheduler.config import SchedulingConfig
from hacksmiths.scheduler.pipeline import assign_panel, find_feasible_slots
from hacksmiths.scheduler.reservations import ReservationLedger
from hacksmiths.scheduler.state_machine import (
    BookingConflictError,
    InterviewStateMachine,
    InvalidTransitionError,
)


def _assigned(scn, accept_all=True):
    """Return (sm, reservations, interview, request, feasible_ids) with seats offered
    (and optionally all accepted)."""
    config = SchedulingConfig()
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
    interview, request = panel.interview, panel.request
    if accept_all:
        for seat in list(interview.seats):
            out = sm.respond_to_seat(
                interview=interview, request=request, round_=scn.round_,
                seat_index=seat.seat_index, accepted=True,
                feasible_ids_at_slot=panel.feasible_ids_at_slot, now=scn.now,
            )
            interview, request = out.interview, out.request
    return sm, reservations, interview, request, panel.feasible_ids_at_slot


def test_create_interview_has_n_pending_seats(normal_single):
    config = SchedulingConfig()
    sm = InterviewStateMachine(
        ReservationLedger(), normal_single.notifier,
        PanelAssignmentAgent(
            load_provider=normal_single.load_provider,
            reservations=ReservationLedger(), notifier=normal_single.notifier, config=config,
        ),
    )
    from hacksmiths.scheduler.models import FeasibleSlot

    slot = FeasibleSlot(
        slot_id="x", start=normal_single.now, end=normal_single.now,
        feasible_interviewer_ids=["iv-ana"], feasible_count=1,
    )
    interview = sm.create_interview(normal_single.request, slot, normal_single.round_, now=normal_single.now)
    assert interview.status == "assigning_panel"
    assert len(interview.seats) == 1
    assert all(s.status == "pending" for s in interview.seats)


def test_panel_complete_then_verify_ready_to_finalize_passes(panel_scenario):
    sm, _, interview, _, _ = _assigned(panel_scenario)
    assert interview.status == "panel_complete"
    sm.verify_ready_to_finalize(interview, panel_scenario.round_)  # no raise


def test_verify_ready_to_finalize_rejects_incomplete_panel(panel_scenario):
    sm, _, interview, _, _ = _assigned(panel_scenario, accept_all=False)
    with pytest.raises(BookingConflictError):
        sm.verify_ready_to_finalize(interview, panel_scenario.round_)


def test_candidate_cancel_releases_all_seats(panel_scenario):
    sm, reservations, interview, _, _ = _assigned(panel_scenario)
    held = list(interview.panel)
    cancelled = sm.candidate_cancel(interview, now=panel_scenario.now)
    assert cancelled.status == "cancelled"
    for iid in held:
        assert reservations.is_free(iid, interview.slot_start, interview.slot_end)
    assert "interview_cancelled" in panel_scenario.notifier.kinds()


def test_cancelled_interview_cannot_transition_again(panel_scenario):
    sm, _, interview, _, _ = _assigned(panel_scenario)
    cancelled = sm.candidate_cancel(interview, now=panel_scenario.now)
    with pytest.raises(InvalidTransitionError):
        sm.candidate_cancel(cancelled, now=panel_scenario.now)


def test_candidate_reschedule_resets_request_to_collecting_availability(panel_scenario):
    sm, reservations, interview, request, _ = _assigned(panel_scenario)
    cancelled, updated_request = sm.candidate_reschedule(interview, request, now=panel_scenario.now)
    assert cancelled.status == "cancelled"
    assert updated_request.status == "collecting_availability"
    for iid in ["iv-p1", "iv-p2", "iv-p3"]:
        assert reservations.is_free(iid, interview.slot_start, interview.slot_end)


def test_interviewer_cancel_refills_just_that_seat(interviewer_cancel_refill):
    scn = interviewer_cancel_refill
    sm, reservations, interview, request, feasible = _assigned(scn)
    assert sorted(interview.panel) == ["iv-s1", "iv-s2"]

    out = sm.interviewer_cancel(
        interview=interview, request=request, round_=scn.round_,
        interviewer_id="iv-s1", feasible_ids_at_slot=feasible, now=scn.now,
    )
    # s2's seat untouched; s1's seat re-offered to s3
    seat_by_idx = {s.seat_index: s for s in out.interview.seats}
    assert any(s.interviewer_id == "iv-s2" and s.status == "accepted" for s in out.interview.seats)
    reoffered = [s for s in out.interview.seats if s.interviewer_id == "iv-s3"]
    assert reoffered and reoffered[0].status == "offered"
    assert reservations.is_free("iv-s1", interview.slot_start, interview.slot_end)

    # accept the refilled seat -> panel complete with s2 + s3
    final = sm.respond_to_seat(
        interview=out.interview, request=out.request, round_=scn.round_,
        seat_index=reoffered[0].seat_index, accepted=True,
        feasible_ids_at_slot=feasible, now=scn.now,
    )
    assert final.status == "panel_complete"
    assert sorted(final.interview.panel) == ["iv-s2", "iv-s3"]


def test_interviewer_cancel_escalates_when_seat_pool_exhausted(seat_cascade_exhaustion):
    scn = seat_cascade_exhaustion
    sm, _, interview, request, feasible = _assigned(scn)  # panel = s1, s2
    out = sm.interviewer_cancel(
        interview=interview, request=request, round_=scn.round_,
        interviewer_id="iv-s1", feasible_ids_at_slot=feasible, now=scn.now,
    )
    # only s1 & s2 were ever feasible; s2 holds the other seat; s1 just cancelled
    assert out.status == "manual_scheduling_required"
    assert scn.notifier.manual_escalations
