from typing import Dict, List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google OAuth client
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    GOOGLE_SCOPES: str = (
        "openid email profile "
        "https://www.googleapis.com/auth/calendar "
        "https://www.googleapis.com/auth/gmail.send"
    )

    # Role assignment — no shared company domain to trust, so internal staff are
    # listed explicitly as "email:role" pairs instead of "anyone@ourdomain.com".
    # Example: "alice@gmail.com:recruiter,bob@gmail.com:interviewer"
    ALLOWED_INTERNAL_USERS: str = ""

    # Secrets
    TOKEN_ENC_KEY: str
    SESSION_JWT_SECRET: str

    # Database
    DATABASE_URL: str

    # App
    FRONTEND_URL: str = "http://localhost:5173"
    SESSION_COOKIE_NAME: str = "session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_TTL_MINUTES: int = 60

    @property
    def google_scopes_list(self) -> List[str]:
        return self.GOOGLE_SCOPES.split()

    @property
    def allowed_internal_users(self) -> Dict[str, str]:
        """Parses 'email:role,email:role' into {email_lower: role}. Malformed
        entries are skipped rather than crashing startup on a typo."""
        result: Dict[str, str] = {}
        for entry in self.ALLOWED_INTERNAL_USERS.split(","):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue
            email, role = entry.split(":", 1)
            result[email.strip().lower()] = role.strip().lower()
        return result

    class Config:
        env_file = ".env"


settings = Settings()
