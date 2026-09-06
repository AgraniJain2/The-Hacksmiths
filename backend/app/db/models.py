import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    candidate = "candidate"
    recruiter = "recruiter"
    hiring_manager = "hiring_manager"
    interviewer = "interviewer"


class UserStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    google_id = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active)
    created_at = Column(DateTime, default=datetime.utcnow)

    oauth_token = relationship(
        "OAuthToken", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class OAuthToken(Base):
    """
    One row per user holding their Google tokens, encrypted at rest.
    `scope` records what was actually granted (not what we asked for) so
    require_google_scope() can fail with a specific, actionable error instead
    of a generic 403 deep inside a Calendar/Gmail call.
    """

    __tablename__ = "oauth_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    provider = Column(String, default="google", nullable=False)
    access_token_enc = Column(Text, nullable=False)
    refresh_token_enc = Column(Text, nullable=False)
    scope = Column(String, nullable=False)
    expiry_utc = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="oauth_token")


# --- Scheduling engine tables (Module 2/2B/3/6, DATA_MODEL.md). Extended in
# Phase 2 (Documentation/IMPLEMENTATION_PLAN.md) from the original stub that
# only had id/title/status/created_by/created_at, to back the real
# app/scheduling/service.py instead of the old in-memory store.py.
#
# A few deliberate departures from DATA_MODEL.md's literal spec, all because
# the engine (app/scheduling/models.py, already built and tested) needs a
# slightly different shape than the doc assumed before this table existed for
# real - noted here so nobody "fixes" these back to the doc's wording:
#
# * `hiring_manager_email` (not a `hiring_manager_id` FK) - the engine has
#   never resolved the hiring manager to a `User` row, only ever passed the
#   raw email through. Same reasoning for `candidate_email`/`candidate_name`/
#   `created_by_email`: denormalized here rather than requiring a join to a
#   `User` row that may not exist yet (a candidate's own `User` row is only
#   created the first time they actually log in via their invite link).
# * `buffer_minutes_before`/`buffer_minutes_after` (not one `buffer_minutes`)
#   - matches `app/scheduling/models.py`'s `Round`, which has always tracked
#   the two independently.
# * `seats_json` - the engine's `Interview.seats` (each seat's offered/
#   accepted/declined-by-whom state) has no independent DB representation of
#   its own; `InterviewSlotOffer`/`InterviewParticipant` below are the
#   durable, queryable record of *why* seats are in that state (and what
#   `DbReservationLedger`/`DbInterviewerLoadProvider` actually query), but
#   reconstructing "pending vs exhausted" purely from those rows on every
#   read is unnecessary work the engine already did once - this column is
#   that answer, cached verbatim.
# * `feasibility_json` - same reasoning as `seats_json`; DATA_MODEL.md never
#   specified a table for `FeasibilityResult` because it's a pure computation
#   over other tables, not new information. Re-running it on every read would
#   be more "correct" but also needlessly re-does real work (a Calendar call,
#   once that's real in Phase 3) just to redisplay what Stage 4 already
#   decided - this column is that cache, invalidated by resubmitting
#   availability. `select_slot` still independently re-validates the chosen
#   slot_id against a fresh computation regardless of what's cached here
#   (MODULE_GUIDE.md's Module 5 edge case), so nothing trusts this blindly.
class Interview(Base):
    __tablename__ = "interviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String, nullable=False)
    status = Column(String, default="draft", nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_by_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    interview_type = Column(String, nullable=True)
    # Nullable at the DB level (not just Pydantic-default `[]`) so this ADD
    # COLUMN migration doesn't need a backfill value for the pre-Phase-2
    # "draft" stub rows already in dev.db - every row this app itself writes
    # going forward always sets it via create_request.
    required_skills = Column(JSON, nullable=True, default=list)
    required_seniority = Column(String, nullable=True)
    panelists_required = Column(Integer, nullable=True)
    hiring_manager_email = Column(String, nullable=True)

    candidate_name = Column(String, nullable=True)
    candidate_email = Column(String, nullable=True, index=True)
    candidate_timezone = Column(String, nullable=True)

    duration_minutes = Column(Integer, nullable=True)
    buffer_minutes_before = Column(Integer, nullable=True)
    buffer_minutes_after = Column(Integer, nullable=True)

    # Set once Stage 6 completes; a reschedule replaces these rather than a
    # parallel row (DATA_MODEL.md - an interview has at most one *active*
    # confirmed time).
    confirmed_start_utc = Column(DateTime, nullable=True)
    confirmed_end_utc = Column(DateTime, nullable=True)
    calendar_event_id = Column(String, nullable=True)  # set by Module 7 (not yet built)
    meeting_link = Column(String, nullable=True)

    seats_json = Column(JSON, nullable=True, default=list)
    feasibility_json = Column(JSON, nullable=True)


class InterviewerProfile(Base):
    """One row per interviewer (Module 2B) - DATA_MODEL.md.

    `name`/`email` are denormalized here (not resolved via a join to `users`)
    for the same reason as `Interview.candidate_name/email` above - the
    router already has them in hand from the authenticated user on every
    upsert, and duplicating them here means the engine's `Interviewer` model
    never needs an extra join or a guaranteed `User` row to build.
    """

    __tablename__ = "interviewer_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    skills = Column(JSON, nullable=False, default=list)
    seniority = Column(String, nullable=False)
    qualified_interview_types = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)
    timezone = Column(String, nullable=False)
    working_hours_start = Column(String, nullable=False, default="09:00")
    working_hours_end = Column(String, nullable=False, default="18:00")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CandidateAvailabilityWindow(Base):
    """Candidate-submitted free windows (Module 3) - DATA_MODEL.md."""

    __tablename__ = "candidate_availability_windows"

    id = Column(String, primary_key=True, default=gen_uuid)
    interview_id = Column(String, ForeignKey("interviews.id"), nullable=False, index=True)
    start_utc = Column(DateTime, nullable=False)
    end_utc = Column(DateTime, nullable=False)
    source_timezone = Column(String, nullable=True)


class InterviewSlotOffer(Base):
    """One row per attempt to assign an interviewer to one open seat, at the
    interview's fixed time (Module 6) - DATA_MODEL.md. This is also the
    durable backing for `DbReservationLedger`'s double-booking guard: the
    "lock the target interviewer's row, re-check no overlapping OFFERED/
    confirmed booking, then insert" transaction DATA_MODEL.md describes is
    exactly `DbReservationLedger.reserve()`.

    `status` values: OFFERED, ACCEPTED, DECLINED, EXPIRED, RELEASED (the last
    is this implementation's addition - used when an interview-wide release,
    e.g. a candidate cancellation, clears an offer that was never explicitly
    declined by the interviewer). Timeout-driven EXPIRED isn't produced by
    anything yet - there's no scheduled sweep until Phase 5 (Module 8).
    """

    __tablename__ = "interview_slot_offers"

    id = Column(String, primary_key=True, default=gen_uuid)
    interview_id = Column(String, ForeignKey("interviews.id"), nullable=False, index=True)
    seat_index = Column(Integer, nullable=False)
    interviewer_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    proposed_start_utc = Column(DateTime, nullable=False)
    proposed_end_utc = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="OFFERED")
    offered_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class InterviewParticipant(Base):
    """The confirmed roster only (Module 6/7) - DATA_MODEL.md. Not where
    pending offers live (that's `InterviewSlotOffer`) - this is what
    `DbInterviewerLoadProvider`'s rolling-load/last-assigned queries read
    from, and what a cancellation flips to ``cancelled`` so both queries
    self-correct with no separate decrement step.

    `seat_index` is this implementation's addition (nullable, panelist rows
    only) - DATA_MODEL.md doesn't list it, but without it there's no way to
    tell *which* of the N seats a panelist row confirms once more than one
    exists for the same interview.
    """

    __tablename__ = "interview_participants"

    id = Column(String, primary_key=True, default=gen_uuid)
    interview_id = Column(String, ForeignKey("interviews.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "hiring_manager" | "panelist"
    seat_index = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="confirmed")  # "confirmed" | "cancelled"
    created_at = Column(DateTime, default=datetime.utcnow)


class InviteToken(Base):
    """
    Signed, single-use invite that lets a candidate authenticate via Google
    against one specific interview. Required because candidates authenticate
    via Google too (project decision) — without this, any Google account
    could self-register as a candidate with no link to a real interview.
    The raw token is emailed to the candidate and never stored; only its hash
    is kept, so a DB leak doesn't hand out working invite links.
    """

    __tablename__ = "invite_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    interview_id = Column(String, ForeignKey("interviews.id"), nullable=False)
    candidate_email = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
