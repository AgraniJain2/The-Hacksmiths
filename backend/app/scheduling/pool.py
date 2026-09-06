"""Interviewer pool resolution by criteria (workflow step 4, first half).

Recruiters never hand-pick an interviewer. They describe what the round needs
(``interview_type``, ``required_skills``, ``seniority``, ``panelists_required``)
and this filters the whole interviewer directory down to the eligible pool.

If fewer than ``panelists_required`` interviewers are eligible+active, the result
is an explicit ``sufficient=False`` with a specific reason - never a silent short
list. The caller escalates that to manual scheduling.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from pydantic import BaseModel

from .config import SENIORITY_ORDER, PoolPolicy, SeniorityMode, SkillMatchMode
from .models import Interviewer, InterviewRequest

# Request-side interview types that are "just a round number" rather than a
# distinct qualification - an interviewer who declares the generic "TECHNICAL"
# capability (see Documentation/IMPLEMENTATION_PLAN.md Phase 0.2) is eligible
# for either round without picking Round 1 vs Round 2 specifically. This is
# purely additive: an interviewer who still declares the exact granular type
# (e.g. only "TECHNICAL_ROUND_1") keeps matching only that round, unchanged.
TECHNICAL_ROUND_TYPES = {"TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2"}
GENERIC_TECHNICAL_TYPE = "TECHNICAL"


class PoolResolutionResult(BaseModel):
    """Engine-internal (not part of the wire contract)."""

    pool: List[Interviewer]
    required: int
    matched: int
    sufficient: bool
    reason: Optional[str] = None


def _skill_ok(required: Sequence[str], interviewer_skills: Sequence[str], policy: PoolPolicy) -> bool:
    required_set = {s.strip().lower() for s in required if s.strip()}
    if not required_set:
        return True
    have = {s.strip().lower() for s in interviewer_skills}
    overlap = required_set & have
    mode = policy.skill_match_mode
    if mode == SkillMatchMode.ANY:
        return len(overlap) >= 1
    if mode == SkillMatchMode.ALL:
        return overlap == required_set
    if mode == SkillMatchMode.RATIO:
        return (len(overlap) / len(required_set)) >= policy.skill_match_ratio
    raise ValueError(f"unhandled skill_match_mode: {mode!r}")


def _type_ok(requested: str, interviewer_types: Sequence[str]) -> bool:
    if requested in interviewer_types:
        return True
    return requested in TECHNICAL_ROUND_TYPES and GENERIC_TECHNICAL_TYPE in interviewer_types


def _seniority_ok(requested: str, interviewer: str, policy: PoolPolicy) -> bool:
    req_rank = SENIORITY_ORDER[requested]
    iv_rank = SENIORITY_ORDER[interviewer]
    if policy.seniority_mode == SeniorityMode.EXACT:
        return iv_rank == req_rank
    return iv_rank >= req_rank  # AT_LEAST (default)


def resolve_interviewer_pool(
    request: InterviewRequest,
    all_interviewers: Sequence[Interviewer],
    policy: PoolPolicy | None = None,
) -> PoolResolutionResult:
    """Filter ``all_interviewers`` to those eligible for ``request``.

    Eligible iff **all** of:

    1. ``policy.require_active`` is False, or the interviewer's ``active`` flag is on.
    2. ``request.interview_type`` is one of their ``interview_types``.
    3. Their ``skills`` satisfy ``required_skills`` under ``policy.skill_match_mode``
       (default ``ALL``).
    4. Their ``seniority`` satisfies ``request.seniority`` under
       ``policy.seniority_mode`` (default ``AT_LEAST`` - interviewer >= requested).

    "Sufficient" iff at least ``panelists_required`` interviewers remain.
    """

    policy = policy or PoolPolicy()
    pool: List[Interviewer] = []
    for interviewer in all_interviewers:
        if policy.require_active and not interviewer.active:
            continue
        if not _type_ok(request.interview_type, interviewer.interview_types):
            continue
        if not _skill_ok(request.required_skills, interviewer.skills, policy):
            continue
        if not _seniority_ok(request.seniority, interviewer.seniority, policy):
            continue
        pool.append(interviewer)

    required = request.panelists_required
    matched = len(pool)
    sufficient = matched >= required
    reason = None
    if not sufficient:
        reason = (
            f"insufficient interviewer pool: {matched} eligible & "
            f"{'active' if policy.require_active else 'listed'}, {required} required "
            f"(interview_type={request.interview_type!r}, "
            f"required_skills={list(request.required_skills)}, "
            f"seniority>={request.seniority} [{policy.seniority_mode.value}], "
            f"skill_match={policy.skill_match_mode.value})"
        )

    return PoolResolutionResult(
        pool=pool, required=required, matched=matched, sufficient=sufficient, reason=reason
    )
