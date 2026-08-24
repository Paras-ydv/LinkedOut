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
