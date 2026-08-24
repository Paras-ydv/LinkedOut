"""Defense-in-depth PII redaction for the stdlib `logging` module.

Audit finding (Phase 4, item 14): as of Phase 3, this codebase never
imports or calls `logging` anywhere in `app/` — a `grep -rn "logging\\.\\|
import logging"` pass across `app/` returns nothing. The only place
anything resembling PII is written to an output stream at all is the two
Phase-1 dev-only provider stubs, `ConsoleSMSProvider.send_otp` and
`ConsoleEmailProvider.send_verification_code` (see app/providers/sms.py,
app/providers/email.py), which use bare `print()` — deliberately not
`logging` — specifically so nothing gets captured by log
aggregation/retention. That's correct as designed for local dev, but it's
worth flagging plainly: a real deployment MUST swap those for a real
SMS/email provider before going live, or that stdout output (which a
process supervisor or container log driver could still capture) becomes
the leak. Nothing else in `app/` touches phone numbers, corporate emails,
verification codes, or document content in a form that could reach a log
line — see app.core.security's module docstring for the hash-and-discard
pattern that keeps it that way.

This module exists as a second, independent layer on top of that
discipline: even though nothing today should ever hand a raw
email/phone number to `logging`, if a future change accidentally did, this
filter redacts common PII shapes before the record is formatted. It's not
a substitute for the "never log PII in the first place" rule above — a
redaction regex can't catch everything a determined bug might leak — it's
a safety net for exactly the failure mode that rule is meant to prevent.
"""

import logging
import re

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# E.164-ish: optional +, 8-15 digits, allowing common separators.
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\-\s]{7,14}\d)(?!\d)")


class PIIRedactionFilter(logging.Filter):
    """Redacts email- and phone-shaped substrings from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        # Args are formatted into `record.msg` later by the logging
        # module; redact any string args too so `%s`-style logging can't
        # smuggle PII through untouched.
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact(v) if isinstance(v, str) else v for k, v in record.args.items()
                }
            else:
                record.args = tuple(_redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def _redact(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    return text


def configure_logging() -> None:
    """Attach `PIIRedactionFilter` to the root logger.

    Idempotent — safe to call more than once (e.g. once per test-app
    creation) without stacking duplicate filters.
    """
    root = logging.getLogger()
    if not any(isinstance(f, PIIRedactionFilter) for f in root.filters):
        root.addFilter(PIIRedactionFilter())
