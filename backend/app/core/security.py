"""
All secret-handling for the auth module lives here, deliberately in one place:
- AES-GCM encrypt/decrypt for Google tokens at rest (nothing else should touch
  the raw bytes of an access/refresh token).
- Session JWT create/verify for our own login sessions (never Google's tokens).
- Signed OAuth 'state' helpers (CSRF protection + carrying an invite_token
  safely through the Google redirect round-trip).
"""

import base64
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import JWTError, jwt

from app.core.config import settings

_aes_key = base64.b64decode(settings.TOKEN_ENC_KEY)
if len(_aes_key) != 32:
    raise RuntimeError(
        "TOKEN_ENC_KEY must decode to exactly 32 bytes (base64-encoded AES-256 key). "
        "Generate one with: python -c \"import os,base64; "
        "print(base64.b64encode(os.urandom(32)).decode())\""
    )


def encrypt_token(plaintext: str) -> str:
    aesgcm = AESGCM(_aes_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_token(ciphertext_b64: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_aes_key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def create_session_jwt(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.SESSION_TTL_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.SESSION_JWT_SECRET, algorithm="HS256")


def verify_session_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SESSION_JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        return None


_state_signer = URLSafeTimedSerializer(settings.SESSION_JWT_SECRET, salt="google-oauth-state")


def sign_state(payload: dict) -> str:
    return _state_signer.dumps(payload)


def unsign_state(token: str, max_age_seconds: int = 600) -> Optional[dict]:
    try:
        return _state_signer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def hash_invite_token(raw_token: str) -> str:
    """Invite tokens are stored hashed (like passwords) so a DB leak alone
    doesn't hand out working candidate invite links."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
