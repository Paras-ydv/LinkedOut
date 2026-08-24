"""PII hashing helpers.

Hard constraint for this project: corporate emails, phone numbers, and
uploaded-document identifiers are verified and then immediately hashed —
plaintext PII is never written to the database, logs, or disk.

Phone numbers (and, later, corporate emails) need to be looked up by exact
match during auth (e.g. "does this phone already have an account?"), so we
use a deterministic keyed hash (HMAC-SHA256 with a server-side secret
pepper) rather than a random-salt slow hash like bcrypt/argon2. A slow hash
would be appropriate for password storage, but there are no passwords here,
and it would make the required unique lookup impossible without storing a
per-user salt (which itself becomes a correlatable identifier).

The pepper (`settings.pii_hash_pepper`) is what makes this resistant to
offline brute-forcing of the ~10^10 possible E.164 phone numbers: without
it, an attacker with database access could just hash every possible number
and match against `phone_hash`. It must be a long random secret, stored
outside source control, and never reused across environments.
"""

import hashlib
import hmac
import secrets

from app.core.config import settings


def _normalize_phone(phone: str) -> str:
    """Normalize a phone number to a canonical E.164-ish form before hashing.

    Strips whitespace/formatting punctuation so the same physical number
    always hashes identically regardless of how it was typed. This function
    receives plaintext only transiently, in-memory, during the OTP request
    itself — the caller must never persist or log its input.
    """
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not digits.startswith("+"):
        raise ValueError("phone must be in E.164 format, e.g. +15551234567")
    return digits


def hash_phone(phone: str) -> str:
    """Deterministically hash a phone number for storage/lookup.

    Returns a hex-encoded HMAC-SHA256 digest. The plaintext `phone` argument
    must not be persisted anywhere by the caller.
    """
    normalized = _normalize_phone(phone)
    return hmac.new(
        settings.pii_hash_pepper.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_pii(value: str) -> str:
    """General-purpose deterministic PII hash for future tiers (email, doc IDs).

    Same HMAC construction as `hash_phone`, without phone-specific
    normalization. Callers are responsible for normalizing `value` (e.g.
    lower-casing an email address) before hashing so equivalent inputs
    produce equal hashes.
    """
    return hmac.new(
        settings.pii_hash_pepper.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def normalize_email(email: str) -> str:
    """Lower-case + strip an email address before hashing/domain-splitting.

    Transient, in-memory only — the caller must never persist or log the
    plaintext result.
    """
    return email.strip().lower()


def split_email_domain(email: str) -> str:
    """Extract the domain from an already-normalized email address."""
    if "@" not in email:
        raise ValueError("not a valid email address")
    _, _, domain = email.partition("@")
    if not domain:
        raise ValueError("not a valid email address")
    return domain


def hash_email(email: str) -> str:
    """Deterministically hash a normalized corporate email (see `hash_pii`)."""
    return hash_pii(normalize_email(email))


def hash_domain(domain: str) -> str:
    """Deterministically hash an email domain (see `hash_pii`)."""
    return hash_pii(domain.strip().lower())


def hash_code(code: str) -> str:
    """Deterministically hash a short OTP/verification code (see `hash_pii`).

    Deterministic (not a slow salted hash) because the caller must be able
    to re-derive the same hash from the user-submitted code to compare
    against the stored value — the code's short space is what the pepper
    plus a server-enforced max-attempts count protect against, not the
    hash function itself.
    """
    return hash_pii(code)


def generate_numeric_code(length: int) -> str:
    """Generate a cryptographically random, zero-padded numeric code."""
    upper_bound = 10**length
    return str(secrets.randbelow(upper_bound)).zfill(length)


# --------------------------------------------------------------------------
# Admin password hashing (Phase 4)
# --------------------------------------------------------------------------
#
# Deliberately stdlib-only (no passlib/bcrypt dependency): `hashlib.pbkdf2_
# hmac` with a per-password random salt and a large iteration count is a
# reasonable, dependency-free slow hash for the small number of internal
# operator accounts this project has. Unlike `hash_phone`/`hash_pii` above
# (deterministic, keyed hashes needed for exact-match lookup of
# unrecoverable PII), this *is* password storage, so it uses a random salt
# per password and a slow, tunable-cost function — the opposite tradeoff,
# on purpose.

# 600,000 iterations, per current OWASP Password Storage Cheat Sheet
# guidance for PBKDF2-HMAC-SHA256 (the 260,000 figure used when this was
# first written in Phase 4 was already stale — OWASP raised the SHA256
# recommendation to 600k). Bumped here as part of the Phase 5 hardening
# pass. This only affects *new* hashes: `hash_password` embeds the
# iteration count it used inside the stored string
# (`pbkdf2_sha256$<iterations>$<salt>$<hash>`, see below), and
# `verify_password` reads that count back out rather than assuming the
# current constant — so this bump needs no migration and doesn't
# invalidate any `AdminUser` row hashed under the old count. A real
# deployment with existing admin accounts would want a one-time
# re-hash-on-next-successful-login step to move old rows up to the new
# count, which isn't implemented here (no login-triggered rehash) since
# this project doesn't have production admin accounts yet.
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a plaintext admin password for storage.

    Returns `pbkdf2_sha256$<iterations>$<hex salt>$<hex hash>` — the
    iteration count and salt travel with the hash so it can be verified
    (and the iteration count bumped later) without a schema change.
    """
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verify `password` against a hash from `hash_password`."""
    try:
        algorithm, iterations_str, salt_hex, digest_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)
