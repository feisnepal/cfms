"""Emails for sign-up verification and password reset.

Uses the SMTP settings the notification service already reads (``CALC_SMTP_*``).
With none configured the link is logged instead, so a developer can follow it.
"""
import logging
from email.message import EmailMessage

from app.core.config import settings
from app.services import calculation_notification_service as smtp

logger = logging.getLogger(__name__)


def _send(to: str, subject: str, body: str) -> bool:
    if not smtp.NOTIFICATION_ENABLED:
        logger.warning("[mail:console] to=%s subject=%s\n%s", to, subject, body)
        return True
    msg = EmailMessage()
    msg["From"] = smtp.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")
    return smtp._smtp_send(msg)


def _link(path: str, token: str) -> str:
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}{path}?token={token}"


def send_verify_email(to: str, token: str) -> bool:
    return _send(
        to, "Verify your email / इमेल प्रमाणित गर्नुहोस्",
        "Open this link to verify your email (valid "
        f"{settings.AUTH_TOKEN_TTL_MINUTES} minutes):\n{_link('/verify-email', token)}\n\n"
        f"आफ्नो इमेल प्रमाणित गर्न यो लिङ्क खोल्नुहोस्:\n{_link('/verify-email', token)}\n",
    )


def send_reset_email(to: str, token: str) -> bool:
    return _send(
        to, "Reset your password / पासवर्ड रिसेट",
        "Open this link to choose a new password (valid "
        f"{settings.AUTH_TOKEN_TTL_MINUTES} minutes). If you did not ask for this, ignore it.\n"
        f"{_link('/reset-password', token)}\n\n"
        f"नयाँ पासवर्ड राख्न यो लिङ्क खोल्नुहोस्। तपाईंले माग्नुभएको होइन भने बेवास्ता गर्नुहोस्।\n"
        f"{_link('/reset-password', token)}\n",
    )


def send_password_changed_notice(to: str) -> bool:
    return _send(
        to, "Your password was changed / पासवर्ड परिवर्तन भयो",
        "Your password was changed. If this was not you, contact an administrator.\n"
        "तपाईंको पासवर्ड परिवर्तन गरियो। तपाईं होइन भने प्रशासकलाई सम्पर्क गर्नुहोस्।\n",
    )
