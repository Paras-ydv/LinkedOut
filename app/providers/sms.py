"""SMS delivery abstraction.

`send_otp` receives the plaintext phone number and OTP code transiently,
in-memory, for exactly this call — implementations must not persist or log
either. The router never logs the plaintext phone/code either; this
interface boundary is where the real (Twilio/MSG91/etc.) implementation
plugs in later without touching auth logic.
"""

from abc import ABC, abstractmethod


class SMSProvider(ABC):
    @abstractmethod
    async def send_otp(self, phone: str, code: str) -> None:
        """Deliver `code` to `phone`. Must not persist or log either value."""
        raise NotImplementedError


class ConsoleSMSProvider(SMSProvider):
    """Development stub: prints to stdout instead of sending a real SMS.

    Intentionally does NOT use the `logging` module — log aggregation would
    persist the plaintext phone/OTP indefinitely, which is exactly what
    this project forbids. A real provider implementation should be equally
    careful about what its underlying SDK logs.
    """

    async def send_otp(self, phone: str, code: str) -> None:
        print(f"[ConsoleSMSProvider] would send OTP {code} to {phone}")
