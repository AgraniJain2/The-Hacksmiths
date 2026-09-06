from __future__ import annotations

from datetime import datetime, timezone

from app.scheduling.config import PoolPolicy, SeniorityMode, SkillMatchMode
from app.scheduling.models import Interviewer, InterviewRequest, WorkingHours
from app.scheduling.pool import resolve_interviewer_pool


def _ids(result):
    return sorted(i.interviewer_id for i in result.pool)


def test_default_policy_filters_by_active_type_skill_and_seniority(normal_single):
    result = resolve_interviewer_pool(normal_single.request, normal_single.all_interviewers)
    # cara: missing "algorithms"; dan: JUNIOR < MID; eve: inactive.
    assert _ids(result) == ["iv-ana", "iv-ben"]
    assert result.sufficient is True
    assert result.matched == 2 and result.required == 1
    assert result.reason is None


def test_inactive_interviewers_are_excluded_unless_policy_says_otherwise(normal_single):
    strict = resolve_interviewer_pool(normal_single.request, normal_single.all_interviewers)
    assert "iv-eve" not in _ids(strict)

    lax = resolve_interviewer_pool(
        normal_single.request,
        normal_single.all_interviewers,
        PoolPolicy(require_active=False),
    )
    assert "iv-eve" in _ids(lax)


def test_any_skill_mode_widens_the_pool(normal_single):
    result = resolve_interviewer_pool(
        normal_single.request,
        normal_single.all_interviewers,
        PoolPolicy(skill_match_mode=SkillMatchMode.ANY),
    )
    assert "iv-cara" in _ids(result)  # has "python"
    assert "iv-dan" not in _ids(result)  # still fails seniority


def test_exact_seniority_mode_is_stricter(normal_single):
    result = resolve_interviewer_pool(
        normal_single.request,
        normal_single.all_interviewers,
        PoolPolicy(seniority_mode=SeniorityMode.EXACT),  # request asks MID
    )
    assert result.pool == []
    assert result.sufficient is False


def test_interview_type_capability_required(insufficient_pool):
    result = resolve_interviewer_pool(insufficient_pool.request, insufficient_pool.all_interviewers)
    assert "iv-r4" not in _ids(result)  # only does TECHNICAL_ROUND_1


def test_insufficient_pool_is_explicit_with_a_specific_reason(insufficient_pool):
    result = resolve_interviewer_pool(insufficient_pool.request, insufficient_pool.all_interviewers)
    assert _ids(result) == ["iv-r1"]
    assert result.sufficient is False
    assert result.matched == 1 and result.required == 3
    assert "1 eligible & active, 3 required" in result.reason


def _interviewer(iid: str, *, types: list[str]) -> Interviewer:
    return Interviewer(
        interviewer_id=iid,
        name=iid,
        email=f"{iid}@example.com",
        timezone="Europe/London",
        skills=["python"],
        seniority="MID",
        interview_types=types,
        working_hours=WorkingHours(start="09:00", end="18:00"),
        calendar_id=f"cal-{iid}",
        active=True,
    )


def _request(*, interview_type: str) -> InterviewRequest:
    return InterviewRequest(
        request_id="req-generic-technical",
        candidate_id="cand-1",
        interview_type=interview_type,
        required_skills=["python"],
        seniority="MID",
        panelists_required=1,
        status="collecting_availability",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def test_generic_technical_qualification_satisfies_either_round():
    # An interviewer who declares the generic "TECHNICAL" capability (Phase 0.2 -
    # interviewer dashboard no longer asks them to pick Round 1 vs Round 2) is
    # eligible for a request for *either* round.
    generic = _interviewer("iv-generic", types=["TECHNICAL"])
    for round_type in ("TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2"):
        result = resolve_interviewer_pool(_request(interview_type=round_type), [generic])
        assert _ids(result) == ["iv-generic"], round_type


def test_granular_technical_qualification_still_matches_only_its_own_round():
    # Backward compatible: an interviewer who still has the old granular value
    # stored keeps matching only that exact round, same as before this change.
    round1_only = _interviewer("iv-round1", types=["TECHNICAL_ROUND_1"])
    result = resolve_interviewer_pool(_request(interview_type="TECHNICAL_ROUND_2"), [round1_only])
    assert _ids(result) == []


def test_generic_technical_does_not_satisfy_non_technical_types():
    generic = _interviewer("iv-generic", types=["TECHNICAL"])
    result = resolve_interviewer_pool(_request(interview_type="HR"), [generic])
    assert _ids(result) == []
