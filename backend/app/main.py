from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.google_oauth import ReauthRequired
from app.auth.router import auth_router, google_router
from app.core.config import settings
from app.scheduling.router import router as scheduling_router

app = FastAPI(title="Smart Interview Scheduler API")

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


@app.get("/health")
def health():
    return {"status": "ok"}
