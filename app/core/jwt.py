"""JWT issuance/verification.

Hard constraint: the payload carries no PII. It contains only `sub` (the
user's UUID), `tier` (verification tier at issuance time), `iat`, `exp`,
and `type` (`"access"` or `"refresh"` — not PII, needed so a refresh token
can't be replayed as an access token and vice versa).
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum

from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.models.enums import VerificationTier


class TokenType(str, Enum):
    access = "access"
    refresh = "refresh"


class TokenPayload(BaseModel):
    sub: uuid.UUID
    tier: VerificationTier
    iat: datetime
    exp: datetime
    type: TokenType


class InvalidTokenError(Exception):
    pass


def _create_token(
    user_id: uuid.UUID, tier: VerificationTier, token_type: TokenType, expires_delta: timedelta
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tier": tier.value,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "type": token_type.value,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, tier: VerificationTier) -> str:
    return _create_token(
        user_id,
        tier,
        TokenType.access,
        timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )


def create_refresh_token(user_id: uuid.UUID, tier: VerificationTier) -> str:
    return _create_token(
        user_id,
        tier,
        TokenType.refresh,
        timedelta(minutes=settings.jwt_refresh_token_expire_minutes),
    )


def decode_token(token: str, *, expected_type: TokenType | None = None) -> TokenPayload:
    """Decode + verify signature/expiry. Raises `InvalidTokenError` on any failure."""
    try:
        raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        payload = TokenPayload(
            sub=raw["sub"],
            tier=raw["tier"],
            iat=datetime.fromtimestamp(raw["iat"], tz=UTC),
            exp=datetime.fromtimestamp(raw["exp"], tz=UTC),
            type=raw["type"],
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("malformed token payload") from exc

    if expected_type is not None and payload.type != expected_type:
        raise InvalidTokenError(f"expected a {expected_type.value} token")

    return payload
