"""HTTP-facing request/response shapes for app/scheduling/router.py.

Kept separate from models.py: those are the engine's own wire contract
(shared verbatim with the pure pipeline functions), these are what the
recruiter/candidate/interviewer forms actually submit - a slightly
different shape (bundling a Round's fields into the create-request call,
generating ids server-side, etc).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from .models import FeasibilityResult, Interview, InterviewRequest, Round

INTERVIEW_TYPES = ["SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR"]

# Phase 6 (CONVENTIONS.md pass): these used to be plain `str`, so a garbage
# value sailed straight into the DB and only blew up as an unhandled 500 -
# with the row already committed - the *next* time anything read it back
# (`InterviewRequest`'s own Literal fields rejected it there, just too late).
# Constraining it here instead means FastAPI now rejects it with a clean 422
# before it ever touches the database. Two different literals, not one -
# matches the split `lib/constants.js` already has: a request names one
# specific round, an interviewer declares generic "TECHNICAL" (Phase 0.2,
# `pool.py`'s `_type_ok`), never the round-specific values.
RequestInterviewType = Literal["SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR"]
InterviewerQualificationType = Literal["SCREENING", "TECHNICAL", "MANAGERIAL", "HR"]
SeniorityLevel = Literal["JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL"]


class CreateRequestBody(BaseModel):
    interview_type: RequestInterviewType
    required_skills: List[str] = Field(min_length=1)
    seniority: SeniorityLevel
    panelists_required: int = Field(ge=1, le=10)
    duration_minutes: int = Field(gt=0, default=60)
    buffer_minutes_before: int = Field(ge=0, default=15)
    buffer_minutes_after: int = Field(ge=0, default=15)
    hiring_manager_email: Optional[EmailStr] = None
    candidate_name: str = Field(min_length=1)
    candidate_email: EmailStr
    candidate_timezone: str = Field(min_length=1)


class CreateRequestResponse(BaseModel):
    request: InterviewRequest
    round: Round
    invite_link: str


class RequestDetail(BaseModel):
    request: InterviewRequest
    round: Round
    feasibility: Optional[FeasibilityResult] = None
    interview: Optional[Interview] = None


class AvailabilityWindowIn(BaseModel):
    start: datetime
    end: datetime
    source_timezone: Optional[str] = None


class SubmitAvailabilityBody(BaseModel):
    windows: List[AvailabilityWindowIn] = Field(min_length=1)


class SelectSlotBody(BaseModel):
    slot_id: str = Field(min_length=1)


class SeatResponseBody(BaseModel):
    accept: bool


class InterviewerProfileBody(BaseModel):
    skills: List[str] = Field(min_length=1)
    seniority: SeniorityLevel
    interview_types: List[InterviewerQualificationType] = Field(min_length=1)
    timezone: str = Field(min_length=1)
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    active: bool = True

    @model_validator(mode="after")
    def _working_hours_not_inverted(self) -> "InterviewerProfileBody":
        # MODULE_GUIDE.md Module 2B edge case: reject, don't silently produce
        # an inverted/empty working-hours window.
        if self.working_hours_start >= self.working_hours_end:
            raise ValueError("working_hours_start must be before working_hours_end")
        return self


class OfferOut(BaseModel):
    interview: Interview
    seat_index: int


class NotificationOut(BaseModel):
    id: str
    kind: str
    message: str
    interview_id: Optional[str]
    created_at: datetime
    read: bool
