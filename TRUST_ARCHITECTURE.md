# Trust Architecture

This document explains the design decisions that make LinkedOut's data
trustworthy — both to the people submitting it (who need confidence they
won't be identified or retaliated against) and to the people reading it
(who need confidence the numbers aren't manipulated, laundered, or
massaged into a misleading single verdict). It's written for a technical
reader evaluating the system design, not as user-facing copy.

The short version: every design choice below trades some convenience for
a stronger, checkable guarantee. None of them are free. The point of
writing this down is to make the tradeoff explicit rather than implicit,
so it can be argued with.

## 1. The three-tier verification model

A reviewer's credibility on this platform is a function of how much they
proved about themselves, not how much they claim. Three tiers, each
gating access to a specific capability:

| Tier | What it requires | What it actually proves | What it does *not* prove |
|---|---|---|---|
| 1 — Phone | OTP sent to a phone number, verified within 5 minutes, max 3 attempts | The submitter currently controls one specific phone number | Nothing about their employment |
| 2 — Corporate email | A code sent to an email at a domain the target company has registered (`Company.corporate_email_domains`), verified within 15 minutes | The submitter currently controls an inbox at that company's email domain | That they're a *former* employee, or which specific person they are |
| 3 — Document | An uploaded offer letter / payslip / ID, queued for human moderator review | A human looked at documentary evidence and judged it consistent with employment at the company | Nothing beyond what the moderator's judgment call establishes — this is attestation, not cryptographic proof |

Each tier is a *strictly increasing* bar, and — critically — the bar
required to unlock a capability is checked against **the user's current
database row**, not against whatever a JWT claims. See
`app.core.deps.require_tier`: it decodes the token to identify *who* is
asking, then re-reads `User.verification_tier` from Postgres to decide
*what* they're allowed to do. This closes an entire class of bug where a
token minted at Tier 1 gets used to claim Tier 2 access after the token's
claims go stale, or where a user who legitimately regresses (an admin
manually reverting a fraudulent verification, say) keeps acting on an
old token's authority. The tradeoff is one extra DB read per protected
request; at this system's scale that's not a real cost, and the
alternative (trusting token claims) is the kind of shortcut that's
invisible until someone exploits it.

What Tier 2 deliberately does *not* claim: possessing an inbox at
`@acme.com` proves current access to that mailbox, not current
employment (someone could retain inbox access briefly after leaving) and
not identity (a `Company.corporate_email_domains` match doesn't
distinguish a director from an intern). This is why `Review.role_level`
and `Review.tenure_bucket` are self-reported, bucketed fields, not
verified facts — the system is honest with itself about the limits of
what Tier 2 established, and doesn't launder a self-report into a
verified claim by association with the tier.

Tier 3 is the honest ceiling of what this platform can verify without a
live employer integration: a human looking at a document and making a
judgment call. It's presented as such — `ModerationQueueItem` routes to
manual review (`app.providers.document.ManualReviewDocumentProvider`),
not an OCR/auto-verification pipeline that would imply more rigor than
exists. Overclaiming verification strength is worse than underclaiming
it, because the former fails silently (a reader trusts a claim that
isn't as solid as it looks) and the latter fails loudly (a reader
correctly discounts a claim that says what it is).

## 2. Hash-and-discard PII, end to end

The core discipline: **plaintext PII exists only for the duration of the
single request that needs it, then is discarded — never persisted, never
logged.** What survives is a deterministic HMAC-SHA256 hash, keyed by a
server-side secret pepper (`settings.pii_hash_pepper`), from which the
original value cannot be recovered.

Walking one value end to end — a phone number, at `POST /auth/otp/request`:

1. The client sends `{"phone": "+15551234567"}` in the request body.
   This is the only moment the plaintext number exists anywhere outside
   the client's own memory.
2. `app.core.security.hash_phone` normalizes it (strip formatting,
   enforce E.164) and computes `HMAC-SHA256(pepper, normalized_phone)`.
   The normalized plaintext is a local variable inside that function
   call — nothing returns it, nothing assigns it to an object with
   broader scope.
3. The *hash* — `phone_hash` — is what gets written to `OTPCode` and,
   later, `User`. It's also what every subsequent lookup (`does this
   phone already have an account?`) queries against, since the hash is
   deterministic: the same phone number always hashes to the same value,
   which is what makes exact-match lookup possible without ever storing
   the number itself.
4. The plaintext number is handed to `SMSProvider.send_otp` for
   delivery — the interface's docstring explicitly forbids the
   implementation from persisting or logging it — and then the request
   handler returns. The plaintext number is now unreachable; nothing in
   the codebase holds a second reference to it.

The same pattern applies to the OTP code itself (`hash_code`), the
corporate email and its domain (`hash_email`, `hash_domain` — note that
*only* the domain hash survives onto `User.email_domain_hash`; the local
part of the email, i.e. which specific person, is discarded entirely once
domain verification succeeds), and the Tier-3 document's file bytes
(`content_hash` is a SHA-256 of the bytes for dedup, but the bytes
themselves go to an ephemeral temp file — `tempfile.mkstemp`, never
permanent disk or S3 — that a moderator's tooling reads once and Phase
4's approve/reject endpoints explicitly delete via
`delete_ephemeral_file`, clearing `ephemeral_path` to `NULL` in the same
transaction).

Why a deterministic keyed hash instead of a random-salt slow hash
(bcrypt/argon2, the usual advice for "hashing sensitive values")? Because
the two have different jobs. A password hash's job is to make offline
cracking expensive *per password*, and it's fine that two identical
passwords hash differently (that's the point — no correlation). A
phone/email hash's job here is to make an *exact-match lookup* possible
("has this phone already registered?") without ever storing the
recoverable value — which requires the *same* input to always produce
the *same* output. A random salt would break that lookup entirely. The
pepper is what keeps this scheme resistant to offline brute-forcing
despite determinism: without it, an attacker with database access could
just hash every plausible phone number (a ~10^10 space, well within
reach) and match against `phone_hash`; with a long, secret, per-deployment
pepper never persisted alongside the hashes, that attack requires the
pepper too. This is why `AdminUser.password_hash` uses the *opposite*
construction (PBKDF2-HMAC-SHA256 with a random salt per password, 600,000
iterations per current OWASP guidance) — it's an actual password, with
actual credential-stuffing/offline-cracking risk, not a lookup key.

**Defense in depth, not just discipline.** The hash-and-discard rule
above is a coding discipline — it depends on every call site getting it
right, which is exactly the kind of invariant that erodes over time as a
codebase grows and different people touch it. `app.core.logging.py` adds
a second, independent layer: a `logging.Filter` that redacts
email-shaped and phone-shaped substrings out of any log record before
it's emitted, regardless of how the PII got there. As of this writing
the codebase doesn't use the stdlib `logging` module at all — the only
place anything PII-shaped touches an output stream is two intentionally
non-`logging` `print()` calls in the dev-only console SMS/email provider
stubs (`app/providers/sms.py`, `app/providers/email.py`), which exist
specifically so nothing gets captured by log aggregation, and which a
real deployment must swap for a real provider before going live. The
redaction filter exists for the failure mode where a future change
*does* introduce a `logging` call that accidentally includes something
it shouldn't — it's a safety net under the primary discipline, not a
substitute for it.

## 3. Why there is no composite score

Nothing in this system computes a single number — a "Toxicity Index," an
"Overall Rating," a weighted composite of anything — and this is a
product decision enforced as a literal, automated test
(`tests/test_stats.py::test_no_composite_score_keys_anywhere`,
recursively walking every key in the stats and layoff-timeline response
bodies for a list of forbidden substrings: `score`, `index`, `overall`,
`rating`, `toxicity`, `composite`), not just a design intention that
could quietly erode.

Three reasons, in order of how load-bearing they are:

**A composite score launders a value judgment into a fact.** Deciding
that "compensation complaints" should weigh 2x as much as "culture
complaints" in a single number is an editorial choice, not a
measurement. Presenting the result as one number (`73/100`) hides that
choice behind an appearance of objectivity a reader has no way to
interrogate. Component distributions
(`exit_reason_distribution: {COMPENSATION: {count, percentage}, ...}`)
force the weighting decision back onto the reader, where it belongs —
they can decide compensation matters more to them than culture does, or
the reverse, and the underlying data supports either read.

**A single score is the natural target of gaming.** If publication
turned on beating a threshold score, the incentive for a company (or a
coordinated group of reviewers) to manufacture exactly enough favorable
reviews to clear it would be immediate and measurable. A component
breakdown has no single number to game — moving `exit_reason_distribution`
in one company's favor requires actually shifting the underlying
category counts, which is a much higher bar than nudging one weighted
sum.

**A composite obscures exactly the information this platform's users
need most.** Someone deciding whether to join a company cares whether
people are leaving over compensation (fixable by negotiating harder) or
management (a signal that follows you regardless of your own leverage).
Those are different decisions with different downstream implications for
the reader, and a single blended score destroys the distinction that
matters.

## 4. The moderation-before-publish pipeline

Every `Review` and `LayoffEvent` is created `status=PENDING`, and nothing
in the codebase auto-publishes one — the only way `PENDING` becomes
`PUBLISHED` is an admin's explicit
`POST /admin/moderation-queue/{item_type}/{id}/approve`. This is checked
by an integration test spanning phases
(`tests/test_moderation.py::test_approved_review_visible_in_published_endpoints`)
that submits a review, confirms it's absent from
`GET /reviews/company/{id}`, approves it via the admin endpoint, and only
then confirms it appears.

Ahead of that human gate sits a pre-publication name-detection filter
(`app.core.moderation_filter`) that scans free-text fields (`Review.prose`,
`Review.department`, `LayoffEvent.department`) for content that looks
like it names a specific person. It's a regex/heuristic pass — capitalized
multi-word runs, filtered against a small allowlist of legitimately
Title-Case org vocabulary ("Vice President," "Human Resources") — not a
trained NER model. That's a deliberate scope decision: this filter's
entire job is to **flag for priority human review, never to auto-reject**
(a filter hit sets `Review.flagged_reason` and moves the item to the
front of the moderation queue; it does not touch `status`, which stays
`PENDING` exactly as it would on a filter pass). Because the filter never
makes the final call, its false-positive/false-negative rate is a
triage-quality concern, not a correctness-of-outcome one — a false
negative still gets caught by the same human review every other PENDING
item gets, and a false positive costs a moderator a few extra seconds
looking at content that turns out to be fine. If this filter's job *were*
to auto-reject, the regex-vs-NER tradeoff would need a much harder look;
because it isn't, a lightweight, dependency-free, fully-testable
heuristic is the right level of investment.

Every approve/reject action writes a `ModerationAuditLogEntry` — actor
admin id, item type/id, action, reason (mandatory for reject, enforced at
422 if empty), timestamp. This is the *internal* record: who made which
call and why, for the platform's own accountability, not visible to the
public.

## 5. The public takedown log as a trust mechanism

`GET /takedown-log` requires zero authentication — no bearer token, no
admin dependency — by design. This is the one place in the system where
"trust us" is replaced with "here is the record, unfiltered, for anyone
to check." Every formal takedown request the platform receives (court
order, government direction, company legal request, user report, or
internal moderation decision that rose to this level) is logged with its
requester type, whether the platform complied, and why — and that log is
append-only from the outside: there's no endpoint anywhere that deletes
or edits an existing `TakedownLogEntry`, only `POST /admin/takedown-log`
to add one.

Why this matters as a trust mechanism specifically: a platform hosting
anonymous negative employer reviews is a predictable target for
pressure — legal threats, government requests, direct company demands —
to make inconvenient content disappear quietly. The public log doesn't
prevent the platform from complying with a legitimate court order (it
should, and `complied: true` entries exist for exactly that); what it
prevents is *silent* compliance that a reader would have no way to
notice. A reader who sees a company disappear from search or a review
vanish can check whether that happened through the documented, logged
process or not — the log doesn't stop bad-faith takedowns, but it makes
them visible, which is the only lever a public product actually has
here.

`requester_detail` is free text (e.g. a case number) specifically because
some transparency is more valuable than none, but it comes with a hard
operator-discipline rule documented directly in
`app.schemas.takedown.TakedownLogEntryCreate`: it must never contain
anything that could re-identify the underlying reviewer. This is
explicitly *not* something the schema or database can enforce
mechanically — "does this string re-identify someone" isn't a checkable
property — which is a real gap acknowledged here rather than papered
over. The mitigation is entirely procedural (an admin filling this field
in is trusted not to paste identifying detail into it), and a production
deployment handling real takedown volume would want either a stricter
template for this field or a second-reviewer sign-off before publish,
neither of which exists yet.

## Operational floor beneath this architecture

None of the above matters if the system carrying it can be trivially
DOSed, has its admin credentials brute-forced, or leaks the very PII it
claims to discard. Phase 5 closes the gap between "the data model is
principled" and "the running system enforces it":

- **Rate limiting** on every public-ish write endpoint that could be
  abused for spam or phone/email enumeration
  (`/auth/otp/request`, `/auth/email/request`, `POST /reviews`,
  `POST /grievance`) — the same DB-backed sliding-window check
  (`app.core.rate_limit.enforce_rate_limit`) reused across all four
  rather than a new mechanism per endpoint, returning `429` with a
  `Retry-After` header.
- **Composite `(company_id, status)` indexes** on `reviews` and
  `layoff_events` (migration `0006`), because every query in
  `app.services.stats` filters on exactly that pair — confirmed via
  `EXPLAIN ANALYZE` against ~500 seeded rows that Postgres uses the
  composite index directly rather than bitmap-ANDing two single-column
  indexes (see `scripts/load_test_stats.py` for the load/correctness
  harness this was checked against).
- **600,000-iteration PBKDF2** for admin password hashing, matching
  current OWASP guidance (bumped up from the 260,000 used when this was
  first written in Phase 4 — a reminder that "adequate" iteration counts
  are a moving target, not a constant to set once).
- **A schema-walk test** (`tests/test_security.py::
  test_no_pii_shaped_fields_in_any_response_schema`) that inspects the
  live OpenAPI document and fails if any response field name suggests
  raw PII — mechanical enforcement of the hash-and-discard rule in
  section 2, not just a one-time manual audit.
- **CORS locked down by configuration, not code** — permissive (`*`) by
  default for local development, with `allow_credentials=False` always
  (this API uses bearer tokens, never cookies, so there is no session
  cookie for a browser to leak cross-origin) and an explicit, loud
  requirement in `.env.example` and `app/main.py`'s inline comment that
  a real deployment must set `CORS_ALLOWED_ORIGINS` to the exact
  frontend origin(s) before going live.

None of this is exotic. That's the point — a system whose trust story
depends on doing the ordinary hardening work correctly is more credible
than one that leans entirely on novel cryptography or process to make up
for skipping it.
