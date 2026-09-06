from __future__ import annotations

from app.scheduling.config import PoolPolicy, SeniorityMode, SkillMatchMode
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
