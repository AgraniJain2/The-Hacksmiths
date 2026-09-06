"""In-memory :class:`CalendarProvider` for local dev and tests.

Holds a static map of ``owner_id -> [busy blocks]``. ``get_free_busy`` clips the
stored blocks to the queried range, exactly as a real free/busy API would.
"""

from __future__ import annotations

from typing import Dict, List

from ..models import FreeBusyBlock, FreeBusyResponse, TimeRange
from ..timeutils import ensure_utc, intervals_overlap
from .interfaces import CalendarProvider


class MockCalendarProvider(CalendarProvider):
    def __init__(
        self,
        busy_by_owner: Dict[str, List[FreeBusyBlock]] | None = None,
        timezone_by_owner: Dict[str, str] | None = None,
        reauth_required_owners: set | None = None,
    ) -> None:
        self._busy: Dict[str, List[FreeBusyBlock]] = {
            owner: list(blocks) for owner, blocks in (busy_by_owner or {}).items()
        }
        self._tz: Dict[str, str] = dict(timezone_by_owner or {})
        # Owners who simulate a dead Google connection (Phase 3's
        # ReauthRequired) - `get_free_busy` reports it instead of a real
        # (empty) busy list, exercising the same signal a real
        # GoogleCalendarProvider sends without needing real Google auth in
        # these tests.
        self._reauth_required = set(reauth_required_owners or ())

    def set_busy(self, owner_id: str, blocks: List[FreeBusyBlock]) -> None:
        self._busy[owner_id] = list(blocks)

    def mark_reauth_required(self, owner_id: str) -> None:
        self._reauth_required.add(owner_id)

    def get_free_busy(self, owner_id, owner_type, time_range: TimeRange) -> FreeBusyResponse:
        start = ensure_utc(time_range.start)
        end = ensure_utc(time_range.end)
        if owner_id in self._reauth_required:
            return FreeBusyResponse(
                owner_id=owner_id,
                owner_type=owner_type,
                timezone=self._tz.get(owner_id, "UTC"),
                busy=[],
                queried_range=TimeRange(start=start, end=end),
                reauth_required=True,
            )
        clipped: List[FreeBusyBlock] = []
        for block in self._busy.get(owner_id, []):
            if not intervals_overlap(block.start, block.end, start, end):
                continue
            clipped.append(
                FreeBusyBlock(
                    start=max(ensure_utc(block.start), start),
                    end=min(ensure_utc(block.end), end),
                )
            )
        clipped.sort(key=lambda b: b.start)
        return FreeBusyResponse(
            owner_id=owner_id,
            owner_type=owner_type,
            timezone=self._tz.get(owner_id, "UTC"),
            busy=clipped,
            queried_range=TimeRange(start=start, end=end),
        )
