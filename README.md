# Backend — Phase 0-5

Structured, verified employee-exit-data platform. Phase 0 (scaffold + DB
schema for `Company`/`User` + health check + CI), Phase 1 (three-tier auth:
phone OTP → corporate email → document upload, with JWT + `require_tier`
route protection), Phase 2 (core review flow: reviews, corroborations,
layoff events, employer responses), Phase 3 (aggregation engine: structured
per-company stats and a layoff timeline, computed on read, no composite
score anywhere), Phase 4 (moderation & compliance: pre-publication name
filter, admin moderation queue, public takedown log, grievance-officer
intake), and Phase 5 (hardening: rate limiting, hot-path indexes, a
load/correctness script for the aggregation engine, a PII-leak schema-walk
test, CORS, and stronger admin password hashing) are all built and tested.

**See [`TRUST_ARCHITECTURE.md`](./TRUST_ARCHITECTURE.md) for the actual
portfolio writeup** — the three-tier verification model, the
hash-and-discard PII pattern end to end, why there's no composite score,
the public takedown log as a trust mechanism, and the
moderation-before-publish pipeline, written for a technical reader
evaluating the system design.

## Hard constraints this project is built around

- **No plaintext PII at rest, ever.** `User` stores `phone_hash` and
  `email_domain_hash` (HMAC-SHA256 with a server-side pepper, see
  `app/core/security.py`) — never a phone number or email. OTP codes and
  email verification codes are hashed the same way before they touch the
  DB (`otp_codes.otp_hash`, `email_verification_codes.code_hash`). A raw
  phone/email/OTP/code only ever exists in memory for the request that
  needs it, and is handed to a swappable `SMSProvider`/`EmailProvider`
  stub (console-log implementation for now) — never logged, never
  persisted. `app/core/logging.py` adds a defense-in-depth PII-redaction
  filter on the stdlib `logging` module (email/phone regex redaction) in
  case a future change ever accidentally logs something it shouldn't —
  the project doesn't use `logging` at all today, so this is a safety
  net, not evidence that a leak exists.
- **No branded single score.** Nothing anywhere — including the Phase 3
  stats endpoint — aggregates to a "Toxicity Index" or similar.
  `GET /companies/{id}/stats` returns component distributions only
  (`exit_reason_distribution`, `role_level_distribution`, etc.); this is
  enforced by an automated test
  (`tests/test_stats.py::test_no_composite_score_keys_anywhere`) that
  recursively walks every response key and fails on any key containing
  "score", "index", "overall", "rating", "toxicity", or "composite".
- **No free-text company creation.** `Company` rows come from a seed
  script / admin process. There is no `POST /companies`, and
  `POST /reviews` / `POST /layoff-events` 404 if `company_id` doesn't
  already exist — no ad-hoc company creation from either endpoint.
- **Structured reviews, not essays.** `Review` is enum/bucketed fields
  (`exit_reason`, `tenure_bucket`, `role_level`) plus a hard-capped
  `prose` (500 chars) and `department` (free text, capped at 100 chars —
  a fixed enum was considered and rejected since org structures vary too
  much across companies). Both `prose` and `department` go through the
  Phase 4 pre-publication name filter before ever leaving `PENDING`.
- **Nothing auto-publishes.** Every `Review` and `LayoffEvent` is created
  `status=PENDING`. The Phase 4 name filter flags suspicious content with
  `flagged_reason` for priority moderation, but a filter *pass* doesn't
  publish anything either — only an admin's explicit
  `POST /admin/moderation-queue/{item_type}/{id}/approve` flips a row to
  `PUBLISHED` (or `/reject` to `REJECTED`), and every such action is
  written to an internal audit log (`ModerationAuditLogEntry`).
- **JWTs carry no PII.** Payload is `sub` (user id), `tier`, `iat`, `exp`,
  `type` only — see `app/core/jwt.py`. Employer and admin session tokens
  are separate token types (`employer`: `sub` = employer account id,
  `company_id`, `verified`; `admin`: `sub` = admin user id) with the same
  no-PII rule.
- **A genuinely public, unauthenticated takedown log.** `GET
  /takedown-log` requires zero auth — no bearer token, no admin
  dependency — by design, as a trust/differentiation feature: anyone can
  verify every formal takedown request (court order, government
  direction, company legal request, user report, internal moderation)
  and whether the platform complied. Only admins can write to it
  (`POST /admin/takedown-log`).

## Stack

Python 3.11+, FastAPI, PostgreSQL, SQLAlchemy 2.0 (async, via asyncpg),
Alembic, Docker Compose. Auth: `python-jose` (JWT), stdlib `hmac`/`secrets`
(hashing/OTP generation), stdlib `hashlib.pbkdf2_hmac` (admin password
hashing — no bcrypt/passlib dependency). Name detection: a regex/heuristic
pass (`app/core/moderation_filter.py`), not an NER model — see that
module's docstring for the tradeoff and why it's an acceptable one given
the filter only ever *flags for human review*, never auto-rejects. Lint/
format: Ruff. Tests: pytest + pytest-asyncio + httpx, run against a real
Postgres (not sqlite — the schema uses native Postgres ENUM and ARRAY
types).

## Project layout

```
app/
  core/        settings, async DB engine/session, JWT, PII hashing,
               admin password hashing, rate limiting, route-protection
               dependencies, TTL cache, largest-remainder percentage
               rounding, the pre-publication name-detection filter,
               PII-redaction logging filter
  models/      SQLAlchemy models + shared enums
  providers/   swappable SMS/email/document-verification interfaces
               (console-log / manual-review stubs for now)
  schemas/     Pydantic request/response schemas
  services/    aggregation business logic (Phase 3 stats/timeline)
  routers/     FastAPI routers (health, auth, reviews, layoff-events,
               employer, companies, admin, takedown, grievance)
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

### Load/correctness testing (Phase 5)

`scripts/load_test_stats.py` is a standalone script (not part of the
pytest suite or CI) that seeds ~20 companies / ~500 reviews with
realistic, weighted-random distributions directly via the ORM, then hits
`GET /companies/{id}/stats` for each over real HTTP against a running
server, timing every call and re-verifying at that scale that every
percentage distribution still sums to exactly 100.0 and no
composite-score-shaped key appears anywhere in the response. Point it at
a disposable database — it seeds rows and does not clean up after
itself:

```bash
export DATABASE_URL=postgresql+asyncpg://linkedout:linkedout@localhost:5432/linkedout_loadtest
alembic upgrade head
uvicorn app.main:app --port 8000 &         # in another terminal / background
python scripts/load_test_stats.py
```

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
  `ModerationQueueItem` row.
- `GET /auth/me` — current user's id + tier.

### Reviews & corroborations (Phase 2, moderated per Phase 4)

- `POST /reviews` — Tier 2+ JWT. `company_id` must already exist (404 if
  not). One review per user per company (DB unique constraint, 409 on
  repeat). Created `status=PENDING`; `department`/`prose` are scanned by
  the Phase 4 name filter, which sets `flagged_reason` on a hit but never
  blocks submission.
- `GET /reviews/company/{company_id}` — paginated, `PUBLISHED` only.
- `POST /reviews/{review_id}/corroborate` — Tier 1+ JWT. One
  corroboration per user per review (unique constraint, 409 on repeat);
  can't corroborate your own review (400).
- `GET /reviews/{review_id}/corroborations` — count + paginated comments.
  No user identity in the response, ever — only comment text + timestamp.

### Layoff events (Phase 2, moderated per Phase 4)

- `POST /layoff-events` — Tier 2+ JWT, self-reported only
  (`source_type=SELF_REPORTED`). `company_id` must already exist.
  NEWS-sourced entries have no public endpoint in this phase.
  `department` goes through the same Phase 4 name filter as `Review`.
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

### Aggregation engine (Phase 3)

Computed on read (SQL `GROUP BY`/`COUNT`/`func.max`, never a Python loop
over ORM objects) with a short in-process TTL cache (60s, keyed by
`company_id`) in front:

- `GET /companies/{company_id}/stats` — 404 if the company doesn't exist.
  Below `stats_min_published_reviews` (default 5) `PUBLISHED` reviews,
  returns `{"insufficient_data": true, "minimum_required": N,
  "current_count": n}` and nothing else — both a statistical-noise guard
  and a re-identification guard. At/above the threshold: total published
  review count, `exit_reason_distribution`, `avg_tenure_bucket` (modal
  bucket + full distribution), `current_vs_former_split`,
  `corroboration_density`, `role_level_distribution`, `last_updated`.
  Percentages use the largest-remainder (Hare quota) method
  (`app/core/percentages.py`) so every distribution's percentages sum to
  exactly 100.0, never 99.9/100.1 from naive per-bucket rounding.
- `GET /companies/{company_id}/layoff-timeline` — `PUBLISHED` layoff
  events only, grouped by year (newest first), with a running total
  headcount accumulated forward through time.

### Moderation & compliance (Phase 4)

- `POST /admin/login` — email + password → admin session token. No
  self-serve admin signup; `AdminUser` rows are seeded directly, same
  posture as `EmployerAccount`.
- `GET /admin/moderation-queue` — admin only. `PENDING` reviews and
  layoff events merged into one feed, flagged items first
  (`flagged_reason is not None`), then oldest `created_at` first.
- `POST /admin/moderation-queue/{item_type}/{item_id}/approve` — admin
  only. Flips `PENDING` → `PUBLISHED`. 409 if the item isn't currently
  `PENDING`. `item_type` is `REVIEW` or `LAYOFF_EVENT`.
- `POST /admin/moderation-queue/{item_type}/{item_id}/reject` — admin
  only. Flips `PENDING` → `REJECTED`. Requires a non-empty `reason`
  (422 without one).
- Every approve/reject writes a `ModerationAuditLogEntry` (actor admin
  id, item type/id, action, reason, timestamp) — the internal audit
  trail, distinct from the public takedown log below.
- `GET /takedown-log` — **public, zero auth required.** Paginated,
  newest first. Every formal takedown request the platform has received
  and whether it complied.
- `POST /admin/takedown-log` — admin only. Creates a takedown-log entry
  (used when a rejection stems from a formal court/government/company
  legal request, distinct from routine moderation rejection).
  `requester_detail` is free text (e.g. a case number) but must never
  contain anything that could re-identify the underlying reviewer — an
  operator-discipline requirement, not something the schema enforces.
- `POST /grievance` — public, no auth. Grievance-officer intake per the
  2026 IT Rules. Auto-acknowledges immediately (`status=ACKNOWLEDGED`),
  stubs a confirmation email, and returns a tracking id.
  `sla_deadline` is 3 hours out if the complainant flags the matter as
  court/government-related, else 7 days.
- `GET /admin/grievances` — admin only. Sorted by `sla_deadline`
  ascending (most urgent first); each entry carries a `past_deadline`
  flag computed against the current time.

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

**`Review`** (Phase 2, `flagged_reason` added Phase 4) — `id, user_id,
company_id, exit_reason, tenure_bucket, department (free text, capped),
role_level, is_current_employee, prose (capped 500), status,
flagged_reason (nullable), created_at`. Unique on `(user_id, company_id)`.

**`Corroboration`** (Phase 2) — `id, review_id, user_id, comment (capped
200, optional), created_at`. Unique on `(review_id, user_id)`.

**`LayoffEvent`** (Phase 2, `flagged_reason` added Phase 4) — `id,
company_id, event_date, department, estimated_headcount, source_type,
source_url, submitted_by_user_id, status, flagged_reason (nullable),
created_at`.

**`EmployerAccount`** (Phase 2) — `id, company_id (unique), domain_hash,
verified, created_at`.

**`EmployerResponse`** (Phase 2) — `id, review_id (unique),
employer_account_id, response_text (capped 1000), created_at`.

**`AdminUser`** (Phase 4) — `id, email (unique), password_hash
(PBKDF2-HMAC-SHA256, stdlib only), is_active, created_at`. Plaintext
email is intentional here — an internal operator account, not
anonymous-reviewer PII.

**`ModerationAuditLogEntry`** (Phase 4) — `id, actor_admin_id, item_type
(REVIEW | LAYOFF_EVENT), item_id, action (APPROVE | REJECT), reason
(nullable — mandatory for REJECT at the API layer), created_at`. Internal
only, no public endpoint.

**`TakedownLogEntry`** (Phase 4) — `id, item_type, item_id,
requester_type (COURT_ORDER | GOVERNMENT_DIRECTION |
COMPANY_LEGAL_REQUEST | USER_REPORT | INTERNAL_MODERATION),
requester_detail (free text, capped, optional), complied, reason,
created_at`. The public trust log — see `GET /takedown-log`.

**`GrievanceComplaint`** (Phase 4) — `id, complainant_contact (plaintext
— legitimate business contact, not anonymous PII), subject, description,
related_item_type (nullable), related_item_id (nullable), status
(RECEIVED | ACKNOWLEDGED | RESOLVED), sla_deadline, created_at`.

### Tier-3 document moderation queue (Phase 4 follow-up)

- `GET /admin/document-queue` — admin only. Paginated, pending
  `ModerationQueueItem` entries, oldest first.
- `POST /admin/document-queue/{item_id}/approve` — admin only. Bumps the
  associated `User.verification_tier` to `document` (Tier 3 — the top of
  the ladder), writes a `ModerationAuditLogEntry`
  (`item_type=DOCUMENT`), and deletes the ephemeral document temp file
  (`ephemeral_path` cleared to `NULL`) per the Phase 1 hash-and-delete
  rule. 409 if the item isn't currently pending.
- `POST /admin/document-queue/{item_id}/reject` — admin only. Requires a
  non-empty `reason` (422 without one), same audit-log pattern, same
  ephemeral-file deletion — a rejected document gets no special
  retention either. Does not touch the user's tier.

### Hardening (Phase 5)

No new endpoints — these are cross-cutting changes to existing ones. See
`TRUST_ARCHITECTURE.md`'s "Operational floor" section for the full
reasoning.

- **Rate limiting**, reusing the exact Phase 1 DB-backed sliding-window
  pattern (`app.core.rate_limit.enforce_rate_limit`), now also covering
  `POST /reviews` (keyed on `user_id`, 5/hour by default) and
  `POST /grievance` (keyed on `complainant_contact`, 5/hour by default) —
  `/auth/otp/request` and `/auth/email/request` were already limited
  since Phase 1. All four return `429` with a `Retry-After` header.
- **Composite `(company_id, status)` indexes** on `reviews` and
  `layoff_events` (migration `0006`) — every query in
  `app.services.stats` filters on exactly that pair; confirmed via
  `EXPLAIN ANALYZE` against seeded data that Postgres uses the composite
  index directly.
- **CORS**, permissive (`*`) by default for local dev, `allow_credentials
  =False` always (bearer tokens only, no cookies), configurable via
  `CORS_ALLOWED_ORIGINS` — a real deployment must set this to the exact
  frontend origin(s).
- **Admin password hashing bumped to 600,000 PBKDF2 iterations**
  (`app.core.security`), matching current OWASP guidance (up from
  260,000 in the original Phase 4 pass — the iteration count travels
  with each stored hash, so this needed no migration).
- **A PII-leak schema-walk test**
  (`tests/test_security.py::test_no_pii_shaped_fields_in_any_response_schema`)
  that inspects the live OpenAPI document and fails if any response
  field name suggests raw phone/email/document content.
- **A load/correctness script** for the aggregation engine — see "Load/
  correctness testing" above.

## What's deliberately NOT built yet

NEWS-sourced layoff event ingestion, self-serve employer signup/domain
verification, name-based/full-text search or filtering over reviews (the
`GET /reviews/company/{company_id}` list is paginated but not
searchable), a login-triggered rehash path for `AdminUser` password
hashes created under an older PBKDF2 iteration count, and a
non-procedural safeguard against PII leaking into
`TakedownLogEntry.requester_detail` (currently an operator-discipline
rule documented in the schema, not something the DB enforces — see
`TRUST_ARCHITECTURE.md` section 5). These are candidates for a later
phase, not promised by anything built so far.
