"""SMS delivery for one-time codes.

No provider is chosen yet, so ``console`` (the default) only logs the message:
fine on a developer machine, useless anywhere else. To add a provider, write a
class with ``send(phone, text) -> bool`` and register it in ``_PROVIDERS``.
"""
import logging
from typing import Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class SmsSender(Protocol):
    def send(self, phone: str, text: str) -> bool: ...


class ConsoleSmsSender:
    """Development stand-in: writes the message to the log instead of sending it."""

    def send(self, phone: str, text: str) -> bool:
        logger.warning("[sms:console] to=%s text=%s", phone, text)
        return True


_PROVIDERS: dict[str, type] = {"console": ConsoleSmsSender}


def get_sender() -> SmsSender:
    name = (settings.SMS_PROVIDER or "console").lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        # A typo in .env must not silently fall back to "console" in production.
        raise RuntimeError(f"SMS_PROVIDER '{name}' is not registered in services/sms.py")
    return cls()
