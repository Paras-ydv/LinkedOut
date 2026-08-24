"""Route-protection dependencies.

`get_current_user` verifies the bearer JWT and loads the corresponding
`User` row. `require_tier(n)` further asserts the *current DB state* of
the user's `verification_tier` is >= n — not just what the JWT claims —
so a stale access token issued at Tier 1 can't be used to skip Tier 2's
gate once the user has actually progressed (or, more importantly, a token
can't be used to claim a tier the user never reached).
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jwt import InvalidTokenError, TokenType, decode_token
from app.models.enums import VerificationTier
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)

# Ordinal rank of each tier, for ">=" comparisons.
_TIER_RANK = {
    VerificationTier.unverified: 0,
    VerificationTier.phone: 1,
    VerificationTier.email: 2,
    VerificationTier.document: 3,
}


def tier_rank(tier: VerificationTier) -> int:
    return _TIER_RANK[tier]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.access)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id: uuid.UUID = payload.sub
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

    return user


def require_tier(minimum: VerificationTier):
    """Dependency factory: 401s unless the caller's *current* tier >= minimum."""

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if tier_rank(user.verification_tier) < tier_rank(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires verification tier '{minimum.value}' or higher",
            )
        return user

    return _dependency
