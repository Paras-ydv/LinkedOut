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
from app.core.jwt import (
    InvalidTokenError,
    TokenType,
    decode_admin_token,
    decode_employer_token,
    decode_token,
)
from app.models.admin import AdminUser
from app.models.employer import EmployerAccount
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


async def get_current_employer_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> EmployerAccount:
    """Verify an employer session token and load the corresponding EmployerAccount.

    Callers that need to gate on the account being *for a specific
    company* (e.g. responding to a review) must check
    `employer_account.company_id` themselves against whatever they're
    acting on — this dependency only proves "this is a real, currently
    verified employer account", not "for this company".
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_employer_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await db.execute(select(EmployerAccount).where(EmployerAccount.id == payload.sub))
    employer_account = result.scalar_one_or_none()
    if employer_account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="employer account not found"
        )

    if not employer_account.verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="employer account not verified"
        )

    return employer_account


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Verify an admin session token and load the corresponding AdminUser.

    Every `/admin/*` route depends on this — a non-admin bearer token (or
    no token at all) gets a 401, and a deactivated admin account gets a
    403, exactly mirroring `get_current_employer_account`.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_admin_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await db.execute(select(AdminUser).where(AdminUser.id == payload.sub))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="admin account not found"
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin account deactivated"
        )

    return admin
