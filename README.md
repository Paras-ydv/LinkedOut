# Backend — Phase 0 scaffold

Structured, verified employee-exit-data platform. This is Phase 0: project
scaffold, DB schema for `Company`/`User`, health check, and CI. No auth
flows, no review submission, no moderation yet — those come in later
phases.

## Hard constraints this scaffold is built around

These aren't implemented as features yet, but the schema and structure are
already shaped so implementing them later doesn't require rework:

- **No plaintext PII at rest.** `User` stores `phone_hash` (HMAC-SHA256,
  see `app/core/security.py`) — never a phone number. There is no `email`
  or document column anywhere. Corporate email / document verification in
  later phases follows the same verify-then-hash-then-discard pattern.
- **No branded single score.** Nothing in this schema aggregates to a
  "Toxicity Index" or similar — future aggregate-stat endpoints must stay
  component-level (e.g. "% citing management" as its own number).
- **No free-text company creation.** `Company` rows come from a seed
  script / admin process. There is no `POST /companies` in this scaffold,
  and none should be added for end users.
- **Structured reviews, not essays** — not yet modeled in Phase 0, but the
  `Company`/`User` shape here assumes reviews will reference `company_id`
  + `user_id` with enum/bucketed fields, not a Review model with a free
  text body.
- **Public takedown log** and **no-named-individuals filter** — also not
  yet modeled; called out here so they're not forgotten when the
  moderation and review-submission phases land.

## Stack

Python 3.11+, FastAPI, PostgreSQL, SQLAlchemy 2.0 (async, via asyncpg),
Alembic, Docker Compose. Lint/format: Ruff. Tests: pytest + pytest-asyncio
+ httpx, run against a real Postgres (not sqlite — the schema uses native
Postgres ENUM and ARRAY types).

## Project layout

```
app/
  core/       settings, async DB engine/session, PII hashing helpers
  models/     SQLAlchemy models (Company, User) + shared enums
  schemas/    Pydantic read/response schemas
  routers/    FastAPI routers (health, ...)
  main.py     FastAPI app factory/entrypoint
alembic/      migrations (async-aware env.py)
tests/        pytest suite (fixtures in conftest.py)
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

## Database models (Phase 0)

**`Company`** — seeded only, no user-facing create endpoint.
`id, name, slug, industry, corporate_email_domains, employee_size_bucket,
hq_location, logo_url, description, created_at, updated_at`.
`corporate_email_domains` is used server-side in a later phase to match a
verified corporate email to a company; it's excluded from
`CompanyRead` since it isn't user-facing.

**`User`** — `id, phone_hash, verification_tier, created_at`.
`verification_tier` is one of `unverified | phone | email | document`,
matching the tier-1/2/3 auth ladder (phone OTP → corporate email →
document upload). No other columns — adding a plaintext PII column here
would violate the hashing constraint above.

## What's deliberately NOT in Phase 0

Auth endpoints (OTP send/verify, JWT issuance), the `Review` model and its
enums (`exit_reason`, tenure bucket, department, capped prose), the
pre-publication named-individual filter, the public takedown-log table,
and aggregate-stat endpoints. Phase 0 is scaffold + schema + CI only, per
the brief.
