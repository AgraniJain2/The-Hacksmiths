"""Provider ports + in-memory adapters.

Import interfaces from ``.interfaces`` and mocks from the ``mock_*`` modules. Real
HTTP adapters would live beside the mocks and be selected at one wiring point.
"""

from .interfaces import (
    AvailabilityRepository,
    CalendarProvider,
    CandidateRepository,
    InterviewerLoadProvider,
    InterviewerRepository,
    NotificationProvider,
    SeatNotification,
)
from .mock_availability_repository import MockAvailabilityRepository
from .mock_calendar_provider import MockCalendarProvider
from .mock_interviewer_load_provider import MockInterviewerLoadProvider
from .mock_notification_provider import (
    ManualEscalation,
    MockNotificationProvider,
    NotificationRecord,
)
from .mock_repositories import MockCandidateRepository, MockInterviewerRepository

__all__ = [
    "CalendarProvider",
    "CandidateRepository",
    "InterviewerRepository",
    "AvailabilityRepository",
    "InterviewerLoadProvider",
    "NotificationProvider",
    "SeatNotification",
    "MockCalendarProvider",
    "MockCandidateRepository",
    "MockInterviewerRepository",
    "MockAvailabilityRepository",
    "MockInterviewerLoadProvider",
    "MockNotificationProvider",
    "NotificationRecord",
    "ManualEscalation",
]
