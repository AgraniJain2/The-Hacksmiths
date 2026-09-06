"""Fixture datasets wired to the in-memory providers.

Six scenarios, each a fully wired :class:`Scenario` (candidate, request, round,
interviewer directory, candidate availability, load stats, and every provider) so
pool resolution, feasibility, N-seat assignment, escalation and the exception
paths can be exercised end-to-end with no network:

* ``normal_single``        - N=1, healthy pool, feasible slots -> panel_complete.
* ``panel``                - N=3, engine offers seats to the 3 lowest-load of 4.
* ``no_feasible_slot``     - pool ok, but the candidate's windows fall outside every
                             interviewer's working hours -> escalation.
* ``insufficient_pool``    - only 1 interviewer is eligible+active, 3 required
                             -> escalation.
* ``seat_cascade_exhaustion`` - feasible at step 4, but the two feasible people
                             both decline and the seat's pool runs out -> escalation.
* ``interviewer_cancel_refill`` - 3 feasible; assign 2, one cancels post-accept,
                             the seat re-cascades to the 3rd.

Timezone note: interviewers sit in Europe/London (BST, UTC+1 in September) with
09:00-18:00 local hours == 08:00-17:00 UTC. The candidate (Asia/Kolkata, UTC+5:30)
submits windows that, converted to UTC, overlap that band.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from ..models import (
    AvailabilityWindow,
    Candidate,
    CandidateAvailability,
    FreeBusyBlock,
    Interviewer,
    InterviewerLoadSnapshot,
    InterviewRequest,
    Round,
    WorkingHours,
)
from .mock_availability_repository import MockAvailabilityRepository
from .mock_calendar_provider import MockCalendarProvider
from .mock_interviewer_load_provider import MockInterviewerLoadProvider
from .mock_notification_provider import MockNotificationProvider
from .mock_repositories import MockCandidateRepository, MockInterviewerRepository

UTC = timezone.utc


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


REFERENCE_NOW = _dt(2026, 9, 1)

STANDARD_ROUND = Round(
    round_id="round-tech-1",
    interview_type="TECHNICAL_ROUND_1",
    duration_minutes=60,
    buffer_minutes_before=15,
    buffer_minutes_after=15,
    default_working_hours=WorkingHours(start="09:00", end="18:00"),
)
ROUND_TECH_2 = STANDARD_ROUND.model_copy(
    update={"round_id": "round-tech-2", "interview_type": "TECHNICAL_ROUND_2"}
)

CANDIDATE = Candidate(
    candidate_id="cand-1", name="Priya Nair", email="priya@example.com", timezone="Asia/Kolkata"
)

# Candidate free 13:00-19:00 IST each weekday == 07:30-13:30 UTC. Overlap with
# London 08:00-17:00 UTC gives feasible slot starts roughly 08:00-12:30 UTC.
_STANDARD_WINDOWS = [
    AvailabilityWindow(start=_dt(2026, 9, d, 7, 30), end=_dt(2026, 9, d, 13, 30), source_timezone="Asia/Kolkata")
    for d in range(7, 12)
]
# Windows that land entirely before London working hours (07:30-11:30 IST == 02:00-06:00 UTC).
_EARLY_WINDOWS = [
    AvailabilityWindow(start=_dt(2026, 9, d, 2, 0), end=_dt(2026, 9, d, 6, 0), source_timezone="Asia/Kolkata")
    for d in range(7, 12)
]


def _iv(
    iid: str,
    *,
    skills: List[str],
    seniority: str,
    types: List[str],
    active: bool = True,
    tz: str = "Europe/London",
    wh: WorkingHours = WorkingHours(start="09:00", end="18:00"),
) -> Interviewer:
    return Interviewer(
        interviewer_id=iid,
        name=iid.replace("iv-", "").replace("-", " ").title(),
        email=f"{iid}@example.com",
        timezone=tz,
        skills=skills,
        seniority=seniority,  # type: ignore[arg-type]
        interview_types=types,
        working_hours=wh,
        calendar_id=f"cal-{iid}",
        active=active,
    )


@dataclass
class Scenario:
    name: str
    candidate: Candidate
    request: InterviewRequest
    round_: Round
    interviewers: List[Interviewer]
    calendar: MockCalendarProvider
    candidate_repo: MockCandidateRepository
    interviewer_repo: MockInterviewerRepository
    availability_repo: MockAvailabilityRepository
    load_provider: MockInterviewerLoadProvider
    notifier: MockNotificationProvider
    now: datetime = REFERENCE_NOW
    expected: str = ""

    @property
    def all_interviewers(self) -> List[Interviewer]:
        return self.interviewer_repo.list_interviewers()


def _tz_map(interviewers: List[Interviewer]) -> dict[str, str]:
    m = {i.interviewer_id: i.timezone for i in interviewers}
    m[CANDIDATE.candidate_id] = CANDIDATE.timezone
    return m


def _request(
    *,
    request_id: str,
    interview_type: str,
    required_skills: List[str],
    seniority: str,
    panelists_required: int,
    hiring_manager_email: Optional[str] = None,
) -> InterviewRequest:
    return InterviewRequest(
        request_id=request_id,
        candidate_id=CANDIDATE.candidate_id,
        interview_type=interview_type,
        required_skills=required_skills,
        seniority=seniority,  # type: ignore[arg-type]
        panelists_required=panelists_required,
        hiring_manager_email=hiring_manager_email,
        status="collecting_availability",
        created_at=REFERENCE_NOW,
    )


def _availability(request_id: str, windows=None) -> CandidateAvailability:
    return CandidateAvailability(
        request_id=request_id,
        candidate_id=CANDIDATE.candidate_id,
        windows=list(windows if windows is not None else _STANDARD_WINDOWS),
        submitted_at=REFERENCE_NOW,
    )


def _wire(name, request, round_, interviewers, calendar, availability, loads, expected) -> Scenario:
    return Scenario(
        name=name,
        candidate=CANDIDATE,
        request=request,
        round_=round_,
        interviewers=interviewers,
        calendar=calendar,
        candidate_repo=MockCandidateRepository([CANDIDATE]),
        interviewer_repo=MockInterviewerRepository(interviewers),
        availability_repo=MockAvailabilityRepository([availability]),
        load_provider=MockInterviewerLoadProvider(loads),
        notifier=MockNotificationProvider(),
        expected=expected,
    )


def _loads(**counts: int) -> dict[str, InterviewerLoadSnapshot]:
    return {
        iid: InterviewerLoadSnapshot(interviewer_id=iid, rolling_confirmed_count=c, last_assigned_at=None)
        for iid, c in counts.items()
    }


# --------------------------------------------------------------------------- #


def normal_single() -> Scenario:
    interviewers = [
        _iv("iv-ana", skills=["python", "algorithms", "system-design"], seniority="SENIOR",
            types=["TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2"]),
        _iv("iv-ben", skills=["python", "algorithms"], seniority="STAFF",
            types=["TECHNICAL_ROUND_1"], wh=WorkingHours(start="10:00", end="16:00")),
        _iv("iv-cara", skills=["python"], seniority="MID", types=["TECHNICAL_ROUND_1"],
            tz="America/New_York"),  # filtered: missing "algorithms"
        _iv("iv-dan", skills=["python", "algorithms"], seniority="JUNIOR",
            types=["TECHNICAL_ROUND_1"]),  # filtered: seniority
        _iv("iv-eve", skills=["python", "algorithms"], seniority="SENIOR",
            types=["TECHNICAL_ROUND_1"], active=False),  # filtered: inactive
    ]
    request = _request(
        request_id="req-normal", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python", "algorithms"], seniority="MID", panelists_required=1,
        hiring_manager_email="hm@example.com",
    )
    calendar = MockCalendarProvider(
        busy_by_owner={"iv-ana": [FreeBusyBlock(start=_dt(2026, 9, 7, 8), end=_dt(2026, 9, 7, 11))]},
        timezone_by_owner=_tz_map(interviewers),
    )
    return _wire(
        "normal_single", request, STANDARD_ROUND, interviewers, calendar,
        _availability("req-normal"), _loads(**{"iv-ana": 3, "iv-ben": 0}),
        "pool={ana,ben}; lowest-load ben gets the single seat; earliest feasible 2026-09-07 09:00Z",
    )


def panel() -> Scenario:
    interviewers = [
        _iv(f"iv-p{i}", skills=["python", "algorithms", "extra"], seniority="SENIOR",
            types=["TECHNICAL_ROUND_1"])
        for i in range(1, 5)
    ] + [
        _iv("iv-p5", skills=["python", "algorithms"], seniority="SENIOR",
            types=["TECHNICAL_ROUND_1"], active=False),
    ]
    request = _request(
        request_id="req-panel", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python", "algorithms"], seniority="MID", panelists_required=3,
    )
    calendar = MockCalendarProvider(busy_by_owner={}, timezone_by_owner=_tz_map(interviewers))
    return _wire(
        "panel", request, STANDARD_ROUND, interviewers, calendar, _availability("req-panel"),
        _loads(**{"iv-p1": 0, "iv-p2": 1, "iv-p3": 2, "iv-p4": 5}),
        "pool={p1..p4}; seats offered to the 3 lowest-load: p1,p2,p3",
    )


def no_feasible_slot() -> Scenario:
    interviewers = [
        _iv("iv-ana", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
        _iv("iv-ben", skills=["python", "algorithms"], seniority="STAFF", types=["TECHNICAL_ROUND_1"]),
    ]
    request = _request(
        request_id="req-nofeas", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python", "algorithms"], seniority="MID", panelists_required=1,
    )
    calendar = MockCalendarProvider(busy_by_owner={}, timezone_by_owner=_tz_map(interviewers))
    return _wire(
        "no_feasible_slot", request, STANDARD_ROUND, interviewers, calendar,
        _availability("req-nofeas", _EARLY_WINDOWS), _loads(**{"iv-ana": 0, "iv-ben": 0}),
        "pool sufficient, but candidate windows are all before London working hours -> escalation",
    )


def insufficient_pool() -> Scenario:
    interviewers = [
        _iv("iv-r1", skills=["rust", "distributed-systems"], seniority="SENIOR", types=["TECHNICAL_ROUND_2"]),
        _iv("iv-r2", skills=["rust"], seniority="SENIOR", types=["TECHNICAL_ROUND_2"]),  # missing skill
        _iv("iv-r3", skills=["rust", "distributed-systems"], seniority="MID", types=["TECHNICAL_ROUND_2"]),  # junior
        _iv("iv-r4", skills=["rust", "distributed-systems"], seniority="STAFF", types=["TECHNICAL_ROUND_1"]),  # wrong round
        _iv("iv-r5", skills=["rust", "distributed-systems"], seniority="PRINCIPAL",
            types=["TECHNICAL_ROUND_2"], active=False),  # inactive
    ]
    request = _request(
        request_id="req-insuff", interview_type="TECHNICAL_ROUND_2",
        required_skills=["rust", "distributed-systems"], seniority="SENIOR", panelists_required=3,
    )
    calendar = MockCalendarProvider(busy_by_owner={}, timezone_by_owner=_tz_map(interviewers))
    return _wire(
        "insufficient_pool", request, ROUND_TECH_2, interviewers, calendar,
        _availability("req-insuff"), _loads(),
        "only iv-r1 is eligible+active; 3 required -> escalation",
    )


def seat_cascade_exhaustion() -> Scenario:
    interviewers = [
        _iv("iv-s1", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
        _iv("iv-s2", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
        _iv("iv-s3", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
    ]
    request = _request(
        request_id="req-cascade", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python", "algorithms"], seniority="MID", panelists_required=2,
    )
    # s3 is busy across every candidate window, so only s1 & s2 are ever feasible.
    calendar = MockCalendarProvider(
        busy_by_owner={
            "iv-s3": [FreeBusyBlock(start=_dt(2026, 9, d, 6), end=_dt(2026, 9, d, 15)) for d in range(7, 12)]
        },
        timezone_by_owner=_tz_map(interviewers),
    )
    return _wire(
        "seat_cascade_exhaustion", request, STANDARD_ROUND, interviewers, calendar,
        _availability("req-cascade"), _loads(**{"iv-s1": 0, "iv-s2": 1, "iv-s3": 2}),
        "feasible={s1,s2}; both decline -> seat pool exhausted -> escalation",
    )


def interviewer_cancel_refill() -> Scenario:
    interviewers = [
        _iv("iv-s1", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
        _iv("iv-s2", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
        _iv("iv-s3", skills=["python", "algorithms"], seniority="SENIOR", types=["TECHNICAL_ROUND_1"]),
    ]
    request = _request(
        request_id="req-refill", interview_type="TECHNICAL_ROUND_1",
        required_skills=["python", "algorithms"], seniority="MID", panelists_required=2,
    )
    calendar = MockCalendarProvider(busy_by_owner={}, timezone_by_owner=_tz_map(interviewers))
    return _wire(
        "interviewer_cancel_refill", request, STANDARD_ROUND, interviewers, calendar,
        _availability("req-refill"), _loads(**{"iv-s1": 0, "iv-s2": 1, "iv-s3": 2}),
        "assign s1,s2; s1 cancels post-accept -> seat 0 re-cascades to s3",
    )


ALL_SCENARIOS = {
    "normal_single": normal_single,
    "panel": panel,
    "no_feasible_slot": no_feasible_slot,
    "insufficient_pool": insufficient_pool,
    "seat_cascade_exhaustion": seat_cascade_exhaustion,
    "interviewer_cancel_refill": interviewer_cancel_refill,
}
