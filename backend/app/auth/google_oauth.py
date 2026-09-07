"""
All direct contact with Google's OAuth/identity endpoints lives here.
Nothing else in the codebase should call google-auth-oauthlib or hit
Google's token endpoint directly — that keeps refresh/revoke logic in one
auditable place (see get_valid_access_token, the choke point every future
Calendar/Gmail/Meet call must go through).
"""

import os
from datetime import datetime, timedelta

# Google rewrites the short scope aliases we request ("profile", "email") to
# their full https://www.googleapis.com/auth/userinfo.* form in the token
# response. oauthlib treats that as a scope mismatch and raises by default —
# this is expected Google behavior, not a real security issue, so relax it.
# Must be set before any oauthlib token exchange happens.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.db.models import OAuthToken

TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"


class ReauthRequired(Exception):
    """Raised whenever we can no longer produce a valid Google access token
    for a user (revoked, expired refresh token, etc). Callers should surface
    this as 'reconnect your Google account', never as a generic 500."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def build_flow() -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=settings.google_scopes_list)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def get_authorization_url(state: str) -> str:
    flow = build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",  # required to get a refresh_token at all
        prompt="consent",  # forces re-issue of refresh_token even on repeat logins
        include_granted_scopes="true",
        state=state,
    )
    return auth_url


def exchange_code(code: str) -> Credentials:
    flow = build_flow()
    flow.fetch_token(code=code)
    return flow.credentials


def verify_id_token(id_token_str: str) -> dict:
    # clock_skew_in_seconds guards against exactly what it sounds like: the
    # underlying jwt.decode() rejects a token whose iat/exp is even one
    # second ahead of *this machine's* clock relative to Google's, with zero
    # tolerance by default. A dev machine's clock doesn't need to be
    # noticeably wrong for that race to lose sometimes and win other times -
    # this is the actual cause of an intermittent (not consistent) 500 on
    # /auth/google/callback. 10s matches Google's own recommended tolerance.
    return google_id_token.verify_oauth2_token(
        id_token_str, GoogleAuthRequest(), settings.GOOGLE_CLIENT_ID, clock_skew_in_seconds=10
    )


def store_credentials(db: Session, user_id: str, credentials: Credentials) -> OAuthToken:
    expiry = credentials.expiry or (datetime.utcnow() + timedelta(seconds=3600))
    token_row = db.query(OAuthToken).filter_by(user_id=user_id).one_or_none()
    if token_row is None:
        token_row = OAuthToken(user_id=user_id)
        db.add(token_row)

    token_row.access_token_enc = encrypt_token(credentials.token)
    if credentials.refresh_token:
        # Google only returns a refresh_token on first consent (or when we force
        # prompt=consent). Never blank out an existing one on a login that didn't
        # return a fresh value.
        token_row.refresh_token_enc = encrypt_token(credentials.refresh_token)
    token_row.scope = " ".join(credentials.scopes or [])
    token_row.expiry_utc = expiry
    db.commit()
    db.refresh(token_row)
    return token_row


def get_valid_access_token(db: Session, user_id: str) -> str:
    """Single choke point for every Calendar/Gmail/Meet call: returns a live
    access token, transparently refreshing it first if it's expired or about
    to expire. Raises ReauthRequired if the user's Google connection is dead
    (revoked access, expired refresh token, etc)."""
    token_row = db.query(OAuthToken).filter_by(user_id=user_id).one_or_none()
    if token_row is None:
        raise ReauthRequired("no_google_connection")

    if token_row.expiry_utc > datetime.utcnow() + timedelta(seconds=60):
        return decrypt_token(token_row.access_token_enc)

    credentials = Credentials(
        token=None,
        refresh_token=decrypt_token(token_row.refresh_token_enc),
        token_uri=TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=token_row.scope.split(),
    )
    try:
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:  # google.auth.exceptions.RefreshError, network errors, etc.
        raise ReauthRequired("refresh_failed") from exc

    token_row.access_token_enc = encrypt_token(credentials.token)
    token_row.expiry_utc = credentials.expiry or (datetime.utcnow() + timedelta(seconds=3600))
    db.commit()
    return credentials.token
