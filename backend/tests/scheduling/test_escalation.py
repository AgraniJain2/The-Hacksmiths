from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.scheduling.escalation import (
    escalate_if_no_feasible_slot,
    escalate_to_manual_scheduling,
)
from app.scheduling.feasibility import run_feasibility
from app.scheduling.models import FeasibilityResult
from app.scheduling.pool import resolve_interviewer_pool
from app.scheduling.providers import MockNotificationProvider

UTC = timezone.utc


def test_escalate_sets_terminal_status_and_notifies_recruiter(no_feasible_slot):
    scn = no_feasible_slot
    updated = escalate_to_manual_scheduling(scn.request, "no feasible slot in window 09-07..09-11", scn.notifier)
    assert updated.status == "manual_scheduling_required"
    assert scn.request.status == "collecting_availability"  # original untouched
    assert len(scn.notifier.manual_escalations) == 1
    assert scn.notifier.manual_escalations[0].request_id == scn.request.request_id


def test_escalate_requires_a_specific_reason(no_feasible_slot):
    with pytest.raises(ValueError):
        escalate_to_manual_scheduling(no_feasible_slot.request, "   ", no_feasible_slot.notifier)


def test_escalate_if_no_feasible_slot_noop_when_slots_exist(normal_single):
    scn = normal_single
    pool = resolve_interviewer_pool(scn.request, scn.all_interviewers)
    availability = scn.availability_repo.get_availability(scn.request.request_id)
    result = run_feasibility(scn.request, scn.round_, pool, availability, scn.calendar, now=scn.now)
    request, escalated = escalate_if_no_feasible_slot(scn.request, result, scn.notifier)
    assert escalated is False
    assert request.status == "collecting_availability"
    assert scn.notifier.manual_escalations == []


def test_escalate_if_no_feasible_slot_escalates_on_empty():
    notifier = MockNotificationProvider()
    empty = FeasibilityResult(
        request_id="r", candidate_id="c", panelists_required=3, feasible_slots=[],
        no_match_reason="insufficient interviewer pool: 1 eligible & active, 3 required",
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    from app.scheduling.providers.fixtures import insufficient_pool

    scn = insufficient_pool()
    request, escalated = escalate_if_no_feasible_slot(scn.request, empty, notifier)
    assert escalated is True
    assert request.status == "manual_scheduling_required"
    assert "3 required" in notifier.manual_escalations[0].reason
