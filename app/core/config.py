"""Application settings, loaded from environment variables / .env.

No secrets are committed to source control. See `.env.example` for the
full list of variables a deployment must supply.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "LinkedOut API"
    environment: str = Field(default="development")  # development | staging | production
    debug: bool = False

    # --- Database ---
    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = Field(
        default="postgresql+asyncpg://linkedout:linkedout@db:5432/linkedout",
    )

    # --- Auth / JWT ---
    jwt_secret: str = Field(
        default="dev-only-insecure-secret-change-me",
        description="HMAC signing key for JWTs. MUST be overridden in every real deployment.",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24h
    jwt_refresh_token_expire_minutes: int = 60 * 24 * 30  # 30d

    # --- OTP (Tier 1: phone) ---
    otp_length: int = 6
    otp_expire_minutes: int = 5
    otp_max_attempts: int = 3
    # Rate limit: at most `otp_rate_limit_max_requests` OTP requests per
    # phone_hash within `otp_rate_limit_window_minutes`.
    otp_rate_limit_max_requests: int = 5
    otp_rate_limit_window_minutes: int = 60

    # --- Email verification (Tier 2) ---
    email_code_length: int = 6
    email_code_expire_minutes: int = 15
    email_rate_limit_max_requests: int = 5
    email_rate_limit_window_minutes: int = 60

    # --- PII hashing ---
    # HMAC pepper used to deterministically hash phone numbers (and, in later
    # phases, corporate emails / document identifiers) before they ever touch
    # the database. Plaintext PII is never persisted or logged.
    pii_hash_pepper: str = Field(
        default="dev-only-insecure-pepper-change-me",
        description=(
            "Secret pepper for HMAC-SHA256 hashing of PII. "
            "MUST be overridden in every real deployment."
        ),
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (safe: env vars don't change mid-process)."""
    return Settings()


settings = get_settings()
