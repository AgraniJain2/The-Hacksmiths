"""Tunable knobs for pool resolution, feasibility, and panel assignment.

No slot-scoring weights any more - feasibility is binary and interviewer
selection is a deterministic ranking. What's left to tune: the pool policy, the
slot search granularity, the rolling-load window, and the offer timeout.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# Ordinal seniority scale. Pool resolution compares interviewers against the
# request on this ladder rather than by string equality.
SENIORITY_ORDER: dict[str, int] = {
    "JUNIOR": 0,
    "MID": 1,
    "SENIOR": 2,
    "STAFF": 3,
    "PRINCIPAL": 4,
}


class SkillMatchMode(str, Enum):
    """How an interviewer's ``skills`` must line up with ``required_skills``.

    - ``ALL`` (default): must cover every required skill - the recruiter's list is
      the minimum competency bar for the round.
    - ``ANY``: at least one overlapping skill (broad behavioural / HR rounds).
    - ``RATIO``: covered / required >= ``skill_match_ratio`` (thin pools).
    """

    ANY = "any"
    ALL = "all"
    RATIO = "ratio"


class SeniorityMode(str, Enum):
    """How the request's ``seniority`` is interpreted.

    - ``AT_LEAST`` (default): interviewer seniority >= requested. A more senior
      person can reliably assess at or below their level; exact-match needlessly
      shrinks the pool.
    - ``EXACT``: interviewer seniority == requested (leveling-calibration rounds).
    """

    AT_LEAST = "at_least"
    EXACT = "exact"


class PoolPolicy(BaseModel):
    skill_match_mode: SkillMatchMode = SkillMatchMode.ALL
    skill_match_ratio: float = 1.0  # only consulted when skill_match_mode == RATIO
    seniority_mode: SeniorityMode = SeniorityMode.AT_LEAST
    require_active: bool = True  # drop interviewers whose active toggle is off


class AssignmentConfig(BaseModel):
    # Granularity of candidate slot start times inside each availability window.
    slot_granularity_minutes: int = 15
    # Trailing window for the "confirmed interview count" load metric (step 6 rank).
    rolling_window_days: int = 7
    # How long an interviewer has to accept a seat offer before it times out and
    # the seat cascades to the next-ranked person.
    offer_timeout_minutes: int = 1440  # 24h
    # Offer all N open seats at once (to N distinct people) vs. one at a time.
    parallel_offers: bool = True


class SchedulingConfig(BaseModel):
    pool_policy: PoolPolicy = Field(default_factory=PoolPolicy)
    assignment: AssignmentConfig = Field(default_factory=AssignmentConfig)
