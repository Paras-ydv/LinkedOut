# Backend — Phase 0-2

Structured, verified employee-exit-data platform. Phase 0 (scaffold + DB
schema for `Company`/`User` + health check + CI), Phase 1 (three-tier auth:
phone OTP → corporate email → document upload, with JWT + `require_tier`
route protection), and Phase 2 (core review flow: reviews, corroborations,
layoff events, employer responses) are all built and tested. Moderation
(the pre-publication name filter, the queue that actually flips
`PENDING` → `PUBLISHED`/`REJECTED`, the public takedown log) is Phase 4 and
not implemented yet — see "What's deliberately NOT in Phase 0-2" below.

## Hard constraints this project is built around

- **No plaintext PII at rest, ever.** `User` stores `phone_hash` and
  `email_domain_hash` (HMAC-SHA256 with a server-side pepper, see
  `app/core/security.py`) — never a phone number or email. OTP codes and
  email verification codes are hashed the same way before they touch the
  DB (`otp_codes.otp_hash`, `email_verification_codes.code_hash`). A raw
  phone/email/OTP/code only ever exists in memory for the request that
  needs it, and is handed to a swappable `SMSProvider`/`EmailProvider`
  stub (console-log implementation for now) — never logged, never
  persisted.
- **No branded single score.** Nothing in this schema aggregates to a
  "Toxicity Index" or similar — aggregate-stat endpoints (a later phase)
  must stay component-level (e.g. "% citing management" as its own
  number).
- **No free-text company creation.** `Company` rows come from a seed
  script / admin process. There is no `POST /companies`, and
  `POST /reviews` / `POST /layoff-events` 404 if `company_id` doesn't
  already exist — no ad-hoc company creation from either endpoint.
- **Structured reviews, not essays.** `Review` is enum/bucketed fields
  (`exit_reason`, `tenure_bucket`, `role_level`) plus a hard-capped
  `prose` (500 chars) and `department` (free text, capped at 100 chars —
  a fixed enum was considered and rejected since org structures vary too
  much across companies; being free text, it needs the same
  pre-publication moderation scan as `prose` once Phase 4 lands).
- **JWTs carry no PII.** Payload is `sub` (user id), `tier`, `iat`, `exp`,
  `type` only — see `app/core/jwt.py`. Employer session tokens are a
  separate token type (`sub` = employer account id, `company_id`,
  `verified`) with the same no-PII rule.
- **Public takedown log** and the **pre-publication no-named-individuals
  filter** — not modeled yet, called out here so they aren't forgotten
  when the Phase 4 moderation work lands. Every `Review` and
  `LayoffEvent` is created `status=PENDING` today and nothing in Phases
  0-2 ever flips it; `app/routers/reviews.py` and
  `app/routers/layoff_events.py` both have `TODO(Phase 4)` comments
  marking exactly where that hook goes.

## Stack

Python 3.11+, FastAPI, PostgreSQL, SQLAlchemy 2.0 (async, via asyncpg),
Alembic, Docker Compose. Auth: `python-jose` (JWT), stdlib `hmac`/`secrets`
(hashing/OTP generation). Lint/format: Ruff. Tests: pytest + pytest-asyncio
+ httpx, run against a real Postgres (not sqlite — the schema uses native
Postgres ENUM and ARRAY types).

## Project layout

```
app/
  core/        settings, async DB engine/session, JWT, PII hashing,
               rate limiting, route-protection dependencies
  models/      SQLAlchemy models + shared enums
  providers/   swappable SMS/email/document-verification interfaces
               (console-log / manual-review stubs for now)
  schemas/     Pydantic request/response schemas
  routers/     FastAPI routers (health, auth, reviews, layoff-events,
               employer)
  main.py      FastAPI app factory/entrypoint
alembic/       migrations (async-aware env.py)
tests/         pytest suite (fixtures in conftest.py)
```

## Running it

### With Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

This starts Postgres, waits for it to be healthy, runs `alembic upgrade
head`, and starts the API with reload on `http://localhost:8000`.
`GET /health` should return `{"status": "ok", "database": "ok"}`.

### Locally, without Docker

Requires a local Postgres reachable at the URL in `.env`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # edit DATABASE_URL if your local Postgres differs

alembic upgrade head
uvicorn app.main:app --reload
```

### Tests

Tests need their own database (never point them at your dev DB — the
fixtures create and drop the full schema per test). `conftest.py` refuses
to run unless `DATABASE_URL` contains the string `test`, as a guardrail.

```bash
createdb linkedout_test   # or: docker exec -it <db-container> createdb -U linkedout linkedout_test
DATABASE_URL=postgresql+asyncpg://linkedout:linkedout@localhost:5432/linkedout_test pytest
```

### Lint / format

```bash
ruff check .
ruff format .
```

Both run in CI (`.github/workflows/ci.yml`), along with `alembic upgrade
head` against a Postgres service container and the full test suite.

## API

### Auth & verification (Phase 1)

Three-tier ladder — each tier's endpoints require the JWT from the
previous tier (`require_tier` checks the caller's *current DB row*, not
just what an older token claims, so progress can't be faked or skipped):

- `POST /auth/otp/request` — phone → OTP sent via `SMSProvider`. 5 min
  expiry, rate-limited per `phone_hash`.
- `POST /auth/otp/verify` — phone + OTP → Tier 1 JWT. Max 3 attempts.
- `POST /auth/email/request` — Tier 1 JWT required. Corporate email →
  verification code via `EmailProvider`. 15 min expiry.
- `POST /auth/email/verify` — Tier 1 JWT + email + code → Tier 2 JWT.
  Plaintext email is discarded after verification; only `domain_hash`
  survives, onto `User.email_domain_hash`.
- `POST /auth/document/upload` — Tier 2 JWT required. File bytes go to
  the `DocumentVerificationProvider` (manual-review stub), which writes
  to an ephemeral temp path — never permanent disk/S3 — and queues a
  `ModerationQueueItem` row. Tier 3 promotion + file deletion happens via
  an admin approval endpoint in Phase 4 (not built yet).
- `GET /auth/me` — current user's id + tier.

### Reviews & corroborations (Phase 2)

- `POST /reviews` — Tier 2+ JWT. `company_id` must already exist (404 if
  not). One review per user per company (DB unique constraint, 409 on
  repeat). Created `status=PENDING`.
- `GET /reviews/company/{company_id}` — paginated, `PUBLISHED` only.
- `POST /reviews/{review_id}/corroborate` — Tier 1+ JWT. One
  corroboration per user per review (unique constraint, 409 on repeat);
  can't corroborate your own review (400).
- `GET /reviews/{review_id}/corroborations` — count + paginated comments.
  No user identity in the response, ever — only comment text + timestamp.

### Layoff events (Phase 2)

- `POST /layoff-events` — Tier 2+ JWT, self-reported only
  (`source_type=SELF_REPORTED`). `company_id` must already exist.
  NEWS-sourced entries have no public endpoint in this phase.
- `GET /layoff-events/company/{company_id}` — paginated, `PUBLISHED`
  only, sorted by `event_date desc`.

### Employer response (Phase 2)

- `POST /employer/login` — Phase 2 stub: exchanges a corporate email for
  an employer session token, but only if a *pre-seeded, already-verified*
  `EmployerAccount` exists whose `domain_hash` matches. No self-serve
  employer signup/verification yet.
- `POST /reviews/{review_id}/response` — verified employer session token
  required; the token's `company_id` must match the review's
  `company_id` (403 otherwise — an employer can only respond to reviews
  about their own company). One response per review (unique constraint).
  **No DELETE route exists for responses anywhere in this project** —
  once posted, permanent.

## Database models

**`Company`** (Phase 0) — seeded only, no user-facing create endpoint.
`id, name, slug, industry, corporate_email_domains, employee_size_bucket,
hq_location, logo_url, description, created_at, updated_at`.

**`User`** (Phase 0-1) — `id, phone_hash, email_domain_hash,
verification_tier, created_at`. `verification_tier` is one of
`unverified | phone | email | document`. No plaintext PII column exists
or should ever be added here.

**`OTPCode`** / **`EmailVerificationCode`** (Phase 1) — hash-only OTP/code
storage (`phone_hash`/`email_hash`/`domain_hash`/`otp_hash`/`code_hash`),
`attempts`, `expires_at`, `consumed_at`.

**`ModerationQueueItem`** (Phase 1) — Tier-3 document review queue:
`user_id, doc_type, content_hash (SHA-256 dedup key), ephemeral_path,
status, created_at, reviewed_at`. Never a plaintext document at rest.

**`Review`** (Phase 2) — `id, user_id, company_id, exit_reason,
tenure_bucket, department (free text, capped), role_level,
is_current_employee, prose (capped 500), status, created_at`. Unique on
`(user_id, company_id)`.

**`Corroboration`** (Phase 2) — `id, review_id, user_id, comment (capped
200, optional), created_at`. Unique on `(review_id, user_id)`.

**`LayoffEvent`** (Phase 2) — `id, company_id, event_date, department,
estimated_headcount, source_type, source_url, submitted_by_user_id,
status, created_at`.

**`EmployerAccount`** (Phase 2) — `id, company_id (unique), domain_hash,
verified, created_at`.

**`EmployerResponse`** (Phase 2) — `id, review_id (unique),
employer_account_id, response_text (capped 1000), created_at`.

## What's deliberately NOT in Phases 0-2

The pre-publication named-individual filter, the moderation queue that
actually reviews/flips `PENDING` → `PUBLISHED`/`REJECTED` for reviews and
layoff events, the Tier-3 document approval admin endpoint, the public
takedown-log table, NEWS-sourced layoff event ingestion, self-serve
employer signup/domain verification, and aggregate-stat endpoints. These
are Phase 4 (and beyond) per the brief.
