import secrets
from datetime import datetime
from typing import Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import google_oauth
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.security import create_session_jwt, hash_invite_token, sign_state, unsign_state
from app.db.models import InviteToken, OAuthToken, User, UserRole
from app.db.session import get_db

# /auth/google/* — the actual OAuth dance with Google.
google_router = APIRouter(prefix="/auth/google", tags=["auth"])
# /auth/* — session management that isn't specific to the Google round-trip.
auth_router = APIRouter(prefix="/auth", tags=["auth"])


def resolve_role_on_first_login(
    db: Session, email: str, invite_token: Optional[str]
) -> Tuple[UserRole, Optional[str]]:
    """
    Decides what role a brand-new Google identity gets. Returns (role, interview_id).

    Because every user type authenticates via Google, 'has a Google account' is not
    enough to get an account here — this is the only gate between that and a real
    role in the system. There's no shared company domain to trust, so internal staff
    are listed explicitly in ALLOWED_INTERNAL_USERS ("email:role" pairs) with their
    exact role, rather than inferred from a domain + assigned later by an admin:
      - a valid, unused, matching-email invite token -> candidate, tied to one interview
      - an email listed in ALLOWED_INTERNAL_USERS     -> its configured role
      - anything else                                  -> rejected
    """
    if invite_token:
        token_hash = hash_invite_token(invite_token)
        invite = db.query(InviteToken).filter_by(token_hash=token_hash).one_or_none()
        if not invite or invite.used_at is not None or invite.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="invalid_or_expired_invite")
        if invite.candidate_email.lower() != email.lower():
            raise HTTPException(status_code=403, detail="invite_email_mismatch")
        invite.used_at = datetime.utcnow()
        db.commit()
        return UserRole.candidate, invite.interview_id

    configured_role = settings.allowed_internal_users.get(email.lower())
    if configured_role:
        try:
            return UserRole(configured_role), None
        except ValueError:
            raise HTTPException(
                status_code=500,
                detail=f"ALLOWED_INTERNAL_USERS has an unknown role '{configured_role}' for {email}",
            )

    raise HTTPException(status_code=403, detail="signup_not_allowed")


@google_router.get("/login")
def login(invite_token: Optional[str] = None):
    """Candidates hit this with ?invite_token=... from their emailed invite link;
    internal staff hit it bare."""
    state_payload = {"nonce": secrets.token_urlsafe(16)}
    if invite_token:
        state_payload["invite_token"] = invite_token
    state = sign_state(state_payload)
    return RedirectResponse(google_oauth.get_authorization_url(state))


@google_router.get("/callback")
def callback(code: str, state: str, db: Session = Depends(get_db)):
    state_payload = unsign_state(state)
    if not state_payload:
        raise HTTPException(status_code=400, detail="invalid_or_expired_state")

    credentials = google_oauth.exchange_code(code)
    claims = google_oauth.verify_id_token(credentials.id_token)
    google_id = claims["sub"]
    email = claims["email"]
    name = claims.get("name") or email

    user = db.query(User).filter_by(google_id=google_id).one_or_none()
    if user is None:
        role, _interview_id = resolve_role_on_first_login(
            db, email, state_payload.get("invite_token")
        )
        # _interview_id linking a candidate User to their Interview belongs to the
        # Interview Scheduling module (e.g. an InterviewParticipant row) — out of
        # scope for the auth module itself.
        user = User(google_id=google_id, email=email, name=name, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)

    google_oauth.store_credentials(db, user.id, credentials)

    session_jwt = create_session_jwt(user.id, user.role.value)
    redirect = RedirectResponse(f"{settings.FRONTEND_URL}/auth/complete")
    redirect.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_jwt,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        max_age=settings.SESSION_TTL_MINUTES * 60,
    )
    return redirect


@google_router.post("/disconnect")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revokes Google's grant and removes the stored tokens. This does NOT log the
    user out of the app session — it only removes Calendar/Gmail access, so features
    needing require_google_scope() will start returning google_not_connected."""
    token_row = db.query(OAuthToken).filter_by(user_id=user.id).one_or_none()
    if token_row:
        try:
            from app.core.security import decrypt_token

            requests.post(
                google_oauth.REVOKE_URI,
                params={"token": decrypt_token(token_row.refresh_token_enc)},
                timeout=5,
            )
        except Exception:
            pass  # best-effort revoke; still remove locally so the user isn't stuck
        db.delete(token_row)
        db.commit()
    return {"status": "disconnected"}


@auth_router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token_row = db.query(OAuthToken).filter_by(user_id=user.id).one_or_none()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "google_connected": token_row is not None,
        "granted_scopes": token_row.scope.split() if token_row else [],
    }


@auth_router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "logged_out"}
