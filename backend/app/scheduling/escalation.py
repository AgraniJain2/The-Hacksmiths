"""Manual-scheduling escalation - the terminal state of the automated pipeline.

Triggered when any of these can't be resolved automatically:

* fewer than N eligible+active interviewers in the directory (pool resolution),
* no time in the candidate's submitted availability has >= N interviewers free
  (feasibility),
* a panel seat's cascade runs out of qualified interviewers (assignment),
* the chosen slot no longer has >= N feasible interviewers on live recompute.

We do NOT retry, widen anything, or relax buffers behind the scenes. We flip the
request to ``manual_scheduling_required`` and notify the recruiter with a
specific, human-readable reason. A human owns it from there.
"""

from __future__ import annotations

from .models import FeasibilityResult, InterviewRequest
from .providers.interfaces import NotificationProvider


def escalate_to_manual_scheduling(
    request: InterviewRequest,
    reason: str,
    notifier: NotificationProvider,
) -> InterviewRequest:
    """Transition ``request`` to ``manual_scheduling_required`` and notify the recruiter.

    Returns the updated request (a copy - originals are treated as immutable).
    ``reason`` must be specific and human-readable.
    """

    if not reason or not reason.strip():
        raise ValueError("escalation requires a specific, human-readable reason")

    updated = request.model_copy(update={"status": "manual_scheduling_required"})
    notifier.notify_recruiter_manual_scheduling(updated, reason.strip())
    return updated


def escalate_if_no_feasible_slot(
    request: InterviewRequest,
    feasibility: FeasibilityResult,
    notifier: NotificationProvider,
) -> tuple[InterviewRequest, bool]:
    """Escalate iff ``feasibility`` produced no slots. Returns ``(request, escalated)``."""

    if feasibility.feasible_slots:
        return request, False
    reason = feasibility.no_match_reason or "no feasible slot found in the candidate's availability"
    return escalate_to_manual_scheduling(request, reason, notifier), True
