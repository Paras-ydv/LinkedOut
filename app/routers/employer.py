"""Employer session (Phase 2 stub).

Full employer signup + domain-verification is out of scope for this
phase. This exchanges a corporate email for a session token only when a
*pre-seeded, already-verified* `EmployerAccount` exists whose
`domain_hash` matches — there's no self-serve creation/verification path
yet. The plaintext email only ever exists in memory for this request; it
is hashed (same `hash_domain` construction as Tier-2 email verification)
and never persisted or logged.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jwt import create_employer_token
from app.core.security import hash_domain, normalize_email, split_email_domain
from app.models.employer import EmployerAccount
from app.schemas.employer import EmployerLoginIn, EmployerLoginOut

router = APIRouter(prefix="/employer", tags=["employer"])


@router.post("/login", response_model=EmployerLoginOut)
async def employer_login(
    body: EmployerLoginIn, db: AsyncSession = Depends(get_db)
) -> EmployerLoginOut:
    normalized = normalize_email(body.email)
    try:
        domain = split_email_domain(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    domain_hash = hash_domain(domain)

    result = await db.execute(
        select(EmployerAccount).where(
            EmployerAccount.domain_hash == domain_hash, EmployerAccount.verified.is_(True)
        )
    )
    employer_account = result.scalar_one_or_none()
    if employer_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no verified employer account for this domain",
        )

    token = create_employer_token(
        employer_account.id, employer_account.company_id, employer_account.verified
    )

    return EmployerLoginOut(
        access_token=token,
        employer_account_id=employer_account.id,
        company_id=employer_account.company_id,
    )
