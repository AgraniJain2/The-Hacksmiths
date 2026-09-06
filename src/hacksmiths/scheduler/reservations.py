"""Interval-overlap reservation ledger - the double-booking guard.

Workflow step 6 lock: "reserve the target interviewer's profile row at the moment
each offer is created, so no one person gets double-booked across two different
interviews' overlapping times."

So this is *not* an exact ``(id, start)`` uniqueness check. Each reservation is a
buffered ``[start, end)`` interval owned by one ``(interview_id, seat_index)``;
:meth:`is_free` returns False if any existing reservation for that interviewer
overlaps the queried interval.

In-memory for now. ``# TODO: replace with a DB row lock / calendar hold.``
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from .timeutils import ensure_utc, intervals_overlap


@dataclass(frozen=True)
class Reservation:
    interview_id: str
    seat_index: int
    start: datetime
    end: datetime


class ReservationLedger:
    def __init__(self) -> None:
        self._by_interviewer: Dict[str, List[Reservation]] = defaultdict(list)

    def is_free(self, interviewer_id: str, start: datetime, end: datetime) -> bool:
        s, e = ensure_utc(start), ensure_utc(end)
        return not any(
            intervals_overlap(r.start, r.end, s, e)
            for r in self._by_interviewer.get(interviewer_id, [])
        )

    def reserve(
        self,
        interviewer_id: str,
        interview_id: str,
        seat_index: int,
        start: datetime,
        end: datetime,
    ) -> None:
        s, e = ensure_utc(start), ensure_utc(end)
        if not self.is_free(interviewer_id, s, e):
            raise ValueError(
                f"cannot reserve {interviewer_id} for {interview_id}#{seat_index}: "
                f"overlapping reservation already held"
            )
        self._by_interviewer[interviewer_id].append(
            Reservation(interview_id=interview_id, seat_index=seat_index, start=s, end=e)
        )

    def release(self, interviewer_id: str, interview_id: str, seat_index: int) -> None:
        self._by_interviewer[interviewer_id] = [
            r
            for r in self._by_interviewer.get(interviewer_id, [])
            if not (r.interview_id == interview_id and r.seat_index == seat_index)
        ]

    def release_interview(self, interview_id: str) -> None:
        for interviewer_id in list(self._by_interviewer):
            self._by_interviewer[interviewer_id] = [
                r for r in self._by_interviewer[interviewer_id] if r.interview_id != interview_id
            ]

    def holds(self, interviewer_id: str, interview_id: str, seat_index: int) -> bool:
        return any(
            r.interview_id == interview_id and r.seat_index == seat_index
            for r in self._by_interviewer.get(interviewer_id, [])
        )
