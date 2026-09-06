import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
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


# --- Minimal stubs so InviteToken has something to reference. The Interview
# Scheduling module owns and will extend this table (round_type, duration,
# participants, status transitions, etc). ---


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String, nullable=False)
    status = Column(String, default="draft", nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
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
