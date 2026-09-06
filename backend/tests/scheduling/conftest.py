"""Shared pytest fixtures - one per wired scenario from ``scheduler.providers.fixtures``."""

from __future__ import annotations

import pytest

from app.scheduling.providers import fixtures


@pytest.fixture
def reference_now():
    return fixtures.REFERENCE_NOW


@pytest.fixture
def normal_single():
    return fixtures.normal_single()


@pytest.fixture
def panel_scenario():
    return fixtures.panel()


@pytest.fixture
def no_feasible_slot():
    return fixtures.no_feasible_slot()


@pytest.fixture
def insufficient_pool():
    return fixtures.insufficient_pool()


@pytest.fixture
def seat_cascade_exhaustion():
    return fixtures.seat_cascade_exhaustion()


@pytest.fixture
def interviewer_cancel_refill():
    return fixtures.interviewer_cancel_refill()
