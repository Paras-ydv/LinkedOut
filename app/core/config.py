"""Application settings, loaded from environment variables / .env.

No secrets are committed to source control. See `.env.example` for the
full list of variables a deployment must supply.
"""

from functools import lru_cache

from pydantic import Field, field_validator
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

    # --- Aggregation engine (Phase 3) ---
    # Below this many PUBLISHED reviews, /companies/{id}/stats returns
    # {"insufficient_data": true, ...} instead of percentages — a handful
    # of reviews is both statistically meaningless and a re-identification
    # risk (looks like it's targeting one whistleblower). Configurable,
    # per the brief; 5 is the starting value.
    stats_min_published_reviews: int = 5
    # In-process TTL cache for the (currently computed-on-read) stats and
    # layoff-timeline endpoints. Short on purpose — this establishes the
    # caching pattern ahead of Phase 5 hardening, it isn't needed for
    # correctness at this data scale.
    stats_cache_ttl_seconds: int = 60

    # --- Rate limiting (Phase 5) ---
    # Same DB-backed sliding-window pattern as the Phase 1 OTP/email limits
    # above (see app.core.rate_limit.enforce_rate_limit) — no new infra,
    # just reused against the tables these endpoints already write to.
    # `POST /reviews`: keyed on the submitting user's id, counted against
    # `Review.created_at`. Deliberately generous relative to
    # `otp_rate_limit_max_requests` — legitimate users may genuinely have
    # reviews for several employers, this is an abuse/spam ceiling, not a
    # realistic-usage one.
    review_rate_limit_max_requests: int = 5
    review_rate_limit_window_minutes: int = 60
    # `POST /grievance`: public, unauthenticated, so keyed on
    # `complainant_contact` (already stored in plaintext per Phase 4 — see
    # app.models.grievance — so keying on it directly adds no new PII
    # exposure) against `GrievanceComplaint.created_at`.
    grievance_rate_limit_max_requests: int = 5
    grievance_rate_limit_window_minutes: int = 60

    # --- CORS (Phase 5) ---
    # Permissive by default for local dev/portfolio demo purposes only.
    # A real deployment MUST override this to the exact origin(s) the
    # frontend is served from — see the docstring on `cors_allowed_origins`
    # below and TRUST_ARCHITECTURE.md for the full reasoning. Comma-
    # separated list in the env var, e.g.
    # `CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com`.
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["*"])

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

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
