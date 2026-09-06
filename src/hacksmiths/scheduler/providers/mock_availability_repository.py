"""In-memory :class:`AvailabilityRepository`."""

from __future__ import annotations

from typing import Dict, Iterable

from ..models import CandidateAvailability
from .interfaces import AvailabilityRepository


class MockAvailabilityRepository(AvailabilityRepository):
    def __init__(self, entries: Iterable[CandidateAvailability] = ()) -> None:
        self._by_request: Dict[str, CandidateAvailability] = {
            a.request_id: a for a in entries
        }

    def get_availability(self, request_id: str) -> CandidateAvailability:
        try:
            return self._by_request[request_id]
        except KeyError:
            raise KeyError(
                f"no candidate availability submitted for request {request_id!r}"
            ) from None

    def save_availability(self, availability: CandidateAvailability) -> None:
        self._by_request[availability.request_id] = availability
