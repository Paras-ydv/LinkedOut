"""Email delivery abstraction (Tier 2 verification codes).

Same contract as `app.providers.sms.SMSProvider`: `send_verification_code`
receives plaintext transiently, in-memory, and must not persist or log it.
"""

from abc import ABC, abstractmethod


class EmailProvider(ABC):
    @abstractmethod
    async def send_verification_code(self, email: str, code: str) -> None:
        """Deliver `code` to `email`. Must not persist or log either value."""
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    """Development stub: prints to stdout instead of sending a real email."""

    async def send_verification_code(self, email: str, code: str) -> None:
        print(f"[ConsoleEmailProvider] would send verification code {code} to {email}")
