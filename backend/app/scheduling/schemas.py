"""HTTP-facing request/response shapes for app/scheduling/router.py.

Kept separate from models.py: those are the engine's own wire contract
(shared verbatim with the pure pipeline functions), these are what the
recruiter/candidate/interviewer forms actually submit - a slightly
different shape (bundling a Round's fields into the create-request call,
generating ids server-side, etc).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .models import FeasibilityResult, Interview, InterviewRequest, Round

INTERVIEW_TYPES = ["SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR"]


class CreateRequestBody(BaseModel):
    interview_type: str
    required_skills: List[str] = Field(min_length=1)
    seniority: str
    panelists_required: int = Field(ge=1, le=10)
    duration_minutes: int = Field(gt=0, default=60)
    buffer_minutes_before: int = Field(ge=0, default=15)
    buffer_minutes_after: int = Field(ge=0, default=15)
    hiring_manager_email: Optional[EmailStr] = None
    candidate_name: str
    candidate_email: EmailStr
    candidate_timezone: str


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
    slot_id: str


class SeatResponseBody(BaseModel):
    accept: bool


class InterviewerProfileBody(BaseModel):
    skills: List[str] = Field(min_length=1)
    seniority: str
    interview_types: List[str] = Field(min_length=1)
    timezone: str
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    active: bool = True


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
