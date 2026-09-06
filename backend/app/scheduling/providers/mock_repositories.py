"""In-memory candidate / interviewer repositories for local dev and tests."""

from __future__ import annotations

from typing import Dict, Iterable, List

from ..models import Candidate, Interviewer
from .interfaces import CandidateRepository, InterviewerRepository


class MockCandidateRepository(CandidateRepository):
    def __init__(self, candidates: Iterable[Candidate] = ()) -> None:
        self._by_id: Dict[str, Candidate] = {c.candidate_id: c for c in candidates}

    def add(self, candidate: Candidate) -> None:
        self._by_id[candidate.candidate_id] = candidate

    def get_candidate(self, candidate_id: str) -> Candidate:
        try:
            return self._by_id[candidate_id]
        except KeyError:
            raise KeyError(f"unknown candidate_id: {candidate_id!r}") from None


class MockInterviewerRepository(InterviewerRepository):
    def __init__(self, interviewers: Iterable[Interviewer] = ()) -> None:
        self._by_id: Dict[str, Interviewer] = {i.interviewer_id: i for i in interviewers}

    def add(self, interviewer: Interviewer) -> None:
        self._by_id[interviewer.interviewer_id] = interviewer

    def get_interviewer(self, interviewer_id: str) -> Interviewer:
        try:
            return self._by_id[interviewer_id]
        except KeyError:
            raise KeyError(f"unknown interviewer_id: {interviewer_id!r}") from None

    def list_interviewers(self, active_only: bool = False) -> List[Interviewer]:
        values = self._by_id.values()
        if active_only:
            return [i for i in values if i.active]
        return list(values)
