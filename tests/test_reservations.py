from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hacksmiths.scheduler.reservations import ReservationLedger

UTC = timezone.utc


def _dt(h, m=0):
    return datetime(2026, 9, 7, h, m, tzinfo=UTC)


def test_overlapping_interval_is_not_free():
    ledger = ReservationLedger()
    ledger.reserve("iv-1", "interview-A", 0, _dt(10), _dt(11))
    # exact, contained, straddling starts/ends all overlap
    assert not ledger.is_free("iv-1", _dt(10), _dt(11))
    assert not ledger.is_free("iv-1", _dt(10, 30), _dt(11, 30))
    assert not ledger.is_free("iv-1", _dt(9, 30), _dt(10, 30))
    # adjacent (touching at the boundary) does not overlap
    assert ledger.is_free("iv-1", _dt(11), _dt(12))
    # a different interviewer is unaffected
    assert ledger.is_free("iv-2", _dt(10), _dt(11))


def test_double_reserve_overlapping_raises():
    ledger = ReservationLedger()
    ledger.reserve("iv-1", "A", 0, _dt(10), _dt(11))
    with pytest.raises(ValueError):
        ledger.reserve("iv-1", "B", 0, _dt(10, 30), _dt(11, 30))


def test_release_by_seat_and_by_interview():
    ledger = ReservationLedger()
    ledger.reserve("iv-1", "A", 0, _dt(10), _dt(11))
    ledger.reserve("iv-1", "A", 1, _dt(13), _dt(14))
    ledger.release("iv-1", "A", 0)
    assert ledger.is_free("iv-1", _dt(10), _dt(11))
    assert not ledger.is_free("iv-1", _dt(13), _dt(14))
    ledger.release_interview("A")
    assert ledger.is_free("iv-1", _dt(13), _dt(14))


def test_holds():
    ledger = ReservationLedger()
    ledger.reserve("iv-1", "A", 2, _dt(10), _dt(11))
    assert ledger.holds("iv-1", "A", 2)
    assert not ledger.holds("iv-1", "A", 0)
