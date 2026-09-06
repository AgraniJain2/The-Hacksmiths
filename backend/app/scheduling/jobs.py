"""Module 8's scheduled job (Phase 5 - Documentation/IMPLEMENTATION_PLAN.md):
the offer-expiry sweep and the reminder sweep, both driven by
``SchedulingService`` methods of the same name - this module is only the
"run periodically, on a fresh DB session, log the outcome" wrapper around
those; all the actual logic lives in ``service.py``/``event_dispatch.py``.

APScheduler is enough at this scale (MODULE_GUIDE.md) - a single
``BackgroundScheduler`` thread, started from ``app/main.py``'s startup event
and shut down on FastAPI shutdown. Each tick opens its own ``SessionLocal()``
(there's no request to inherit one from) and always closes it, success or
failure - a stuck/leaked connection here would eventually starve the pool for
real requests.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal

from .service import SchedulingService

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

OFFER_SWEEP_INTERVAL_MINUTES = 5
REMINDER_SWEEP_INTERVAL_MINUTES = 30


def run_offer_expiry_sweep() -> None:
    db = SessionLocal()
    try:
        touched = SchedulingService(db).sweep_expired_offers()
        if touched:
            logger.info("Offer-expiry sweep cascaded %d interview(s): %s", len(touched), touched)
    except Exception:  # noqa: BLE001 - a scheduled job must never crash the process
        logger.exception("Offer-expiry sweep failed")
    finally:
        db.close()


def run_reminder_sweep() -> None:
    db = SessionLocal()
    try:
        reminded = SchedulingService(db).sweep_reminders()
        if reminded:
            logger.info("Reminder sweep sent %d reminder(s): %s", len(reminded), reminded)
    except Exception:  # noqa: BLE001 - a scheduled job must never crash the process
        logger.exception("Reminder sweep failed")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    """Idempotent - calling this more than once (e.g. a test importing
    app.main twice) just returns the already-running scheduler rather than
    starting a second one."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_offer_expiry_sweep, "interval", minutes=OFFER_SWEEP_INTERVAL_MINUTES,
        id="offer_expiry_sweep", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_reminder_sweep, "interval", minutes=REMINDER_SWEEP_INTERVAL_MINUTES,
        id="reminder_sweep", max_instances=1, coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduled jobs started: offer-expiry every %dm, reminders every %dm",
        OFFER_SWEEP_INTERVAL_MINUTES, REMINDER_SWEEP_INTERVAL_MINUTES,
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
