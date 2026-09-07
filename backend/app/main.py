import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.google_oauth import ReauthRequired

logger = logging.getLogger(__name__)
from app.auth.router import auth_router, google_router
from app.core.config import settings
from app.scheduling.jobs import start_scheduler, stop_scheduler
from app.scheduling.router import router as scheduling_router

app = FastAPI(title="Smart Interview Scheduler API")


@app.on_event("startup")
def _start_scheduled_jobs():
    # Module 8 (Phase 5): offer-expiry cascade + reminders - see
    # app/scheduling/jobs.py. Runs once per process; tests never trigger
    # this (they import the FastAPI app but don't run its startup events
    # through a real server lifecycle), so this never fires during pytest.
    start_scheduler()


@app.on_event("shutdown")
def _stop_scheduled_jobs():
    stop_scheduler()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,  # required so the session cookie is sent cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(google_router)
app.include_router(auth_router)
app.include_router(scheduling_router)


@app.exception_handler(ReauthRequired)
def handle_reauth_required(request: Request, exc: ReauthRequired):
    """Any feature module calling get_valid_access_token() can just raise/let this
    propagate — the frontend gets a consistent, actionable 401 instead of a 500."""
    return JSONResponse(status_code=401, content={"detail": "reauth_required", "reason": exc.reason})


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    """Catch-all for anything that isn't one of the typed exceptions above -
    without this, an unhandled exception propagates past CORSMiddleware
    (Starlette's ExceptionMiddleware, where registered handlers run, sits
    *inside* it) straight to Starlette's default ServerErrorMiddleware,
    whose response never gets a CORS header attached. The browser can't
    read that response at all and the frontend sees a bare "Failed to
    fetch" instead of the real error - which made every unrelated bug look
    like a network outage rather than a specific, traceable 500. This
    doesn't fix the underlying bug (see the specific fix that found this),
    it just makes the *next* one visible and diagnosable from the browser
    instead of indistinguishable from the backend being down."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal_server_error"})


@app.get("/health")
def health():
    return {"status": "ok"}
