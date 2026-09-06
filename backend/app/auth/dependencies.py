from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_session_jwt
from app.db.models import OAuthToken, User
from app.db.session import get_db

# Short names used in route decorators -> the actual Google scope URL they require.
SCOPE_URLS = {
    "calendar": "https://www.googleapis.com/auth/calendar",
    "gmail": "https://www.googleapis.com/auth/gmail.send",
}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")

    payload = verify_session_jwt(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    user = db.query(User).filter_by(id=payload["sub"]).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    return user


def require_google_scope(scope_name: str):
    """
    Dependency factory: guards a route so a missing/insufficient Google
    connection fails fast with a specific, frontend-actionable reason
    ('google_not_connected' / 'google_scope_missing:<scope>') instead of
    failing deep inside a Calendar/Gmail API call.

    Usage: @router.post("/book", dependencies=[Depends(require_google_scope("calendar"))])
    """
    scope_url = SCOPE_URLS[scope_name]

    def _dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        token_row = db.query(OAuthToken).filter_by(user_id=user.id).one_or_none()
        if not token_row:
            raise HTTPException(status_code=403, detail="google_not_connected")
        if scope_url not in (token_row.scope or "").split():
            raise HTTPException(status_code=403, detail=f"google_scope_missing:{scope_name}")
        return user

    return _dependency
