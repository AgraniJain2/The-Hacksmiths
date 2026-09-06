"""Seed a small, ready-to-walk-through demo state - Phase 6
(Documentation/IMPLEMENTATION_PLAN.md): "a live demo doesn't start from an
empty DB."

WorkHire's only login is real Google OAuth (WORKFLOW.md - finalized, no
password/SSO alternative), so this script can't fabricate users the way a
typical seed script would: a `User` row only exists once someone has
actually logged in through the real OAuth flow at least once. This script
therefore takes real email addresses that have *already* logged in, and:

1. Gives each interviewer a real `InterviewerProfile` (skills, seniority,
   qualified types, working hours) via the same `SchedulingService` the app
   itself uses - no hand-rolled DB rows that could drift from the real
   schema.
2. Creates one interview request from the recruiter to the candidate.
3. Immediately submits a plausible candidate-availability window for it, so
   the demo can start at "recruiter/candidate look at feasible slots"
   without a live availability step.

Usage (run from backend/, after each account has logged into the app once -
the recruiter and every interviewer, at minimum; the candidate does not need
to have logged in, since create_request accepts any email):

    python scripts/seed_demo.py \\
        --recruiter-email you@gmail.com \\
        --interviewer-email teammate1@gmail.com \\
        --interviewer-email teammate2@gmail.com \\
        --candidate-name "Demo Candidate" \\
        --candidate-email candidate@example.com

Every flag has a demo-friendly default except the emails, which have no safe
default (they're this deployment's real accounts) - the script prints
exactly what's missing and exits cleanly rather than guessing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.scheduling.models import AvailabilityWindow  # noqa: E402
from app.scheduling.service import SchedulingService  # noqa: E402

UTC = timezone.utc


def _find_user(db, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        print(
            f"No User row for {email!r} yet - they need to log into WorkHire "
            f"with Google at least once first (that's what creates the row), "
            f"then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recruiter-email", required=True, help="Must have already logged in once.")
    parser.add_argument(
        "--interviewer-email", action="append", required=True, dest="interviewer_emails",
        help="Must have already logged in once. Repeat for more than one interviewer.",
    )
    parser.add_argument("--candidate-name", default="Demo Candidate")
    parser.add_argument("--candidate-email", default="demo-candidate@example.com")
    parser.add_argument("--candidate-timezone", default="Asia/Kolkata")
    parser.add_argument("--interview-type", default="TECHNICAL_ROUND_1", choices=[
        "SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR",
    ])
    parser.add_argument(
        "--panelists-required", type=int, default=1,
        help="Defaults to 1; set to len(--interviewer-email) to demo the full N-seat parallel-offer path.",
    )
    parser.add_argument(
        "--skip-availability", action="store_true",
        help="Only create the request + profiles; leave availability collection for the live demo to do.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        recruiter = _find_user(db, args.recruiter_email)
        interviewers = [_find_user(db, email) for email in args.interviewer_emails]

        svc = SchedulingService(db)

        for i, interviewer in enumerate(interviewers):
            svc.upsert_interviewer_profile(
                interviewer_id=interviewer.id,
                name=interviewer.name,
                email=interviewer.email,
                skills=["python", "system design", "algorithms"],
                seniority="SENIOR",
                interview_types=["TECHNICAL", "SCREENING"],
                timezone_name=args.candidate_timezone,
                working_hours_start="09:00",
                working_hours_end="18:00",
                active=True,
            )
            print(f"  interviewer profile ready: {interviewer.email}")

        request, round_ = svc.create_request(
            owner_user_id=recruiter.id,
            owner_email=recruiter.email,
            interview_type=args.interview_type,
            required_skills=["python"],
            seniority="MID",
            panelists_required=args.panelists_required,
            duration_minutes=45,
            buffer_minutes_before=15,
            buffer_minutes_after=15,
            hiring_manager_email=None,
            candidate_name=args.candidate_name,
            candidate_email=args.candidate_email,
            candidate_timezone=args.candidate_timezone,
        )
        print(f"  request created: {request.request_id} ({request.status})")

        if not args.skip_availability:
            start = datetime.now(UTC) + timedelta(days=1, hours=2)
            windows = [AvailabilityWindow(start=start, end=start + timedelta(hours=8))]
            _req2, outcome = svc.submit_availability(request.request_id, windows)
            print(
                f"  availability submitted: {len(outcome.feasibility.feasible_slots)} "
                f"feasible slot(s) found (status now {_req2.status})"
            )
            if not outcome.feasibility.feasible_slots:
                print(
                    "  (0 feasible slots - the demo window may fall outside every "
                    "interviewer's working hours; the request is still there to "
                    "pick different real availability for during the demo.)"
                )

        print()
        print(f"Done. Log in as {args.recruiter_email} and open /requests/{request.request_id}")
        print(f"(or /candidate as {args.candidate_email}, once they've logged in) to continue the walkthrough.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
