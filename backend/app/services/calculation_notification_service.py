"""Email notification for calculation completion.

Sends notification when a calculation finishes (success or failure).
Designed to work with any SMTP provider via env vars.
No-op when SMTP is not configured — safe for development.
"""
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("CALC_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("CALC_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("CALC_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("CALC_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("CALC_SMTP_FROM", "noreply@forestmanagement.gov.np")
SMTP_USE_TLS = os.environ.get("CALC_SMTP_USE_TLS", "true").lower() == "true"
NOTIFICATION_ENABLED = bool(SMTP_HOST and SMTP_USER)


def _smtp_send(msg: EmailMessage) -> bool:
    """Send an EmailMessage over SMTP. Returns True on success."""
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.warning("[notify] Failed to send email: %s", e)
        return False


def send_docx_email(
    user_email: str,
    docx_bytes: bytes,
    filename: str,
    subject: str | None = None,
    forest_name: str = "",
) -> bool:
    """Email a generated DOCX to the user.

    Best-effort by design: it is a fire-and-forget companion to the browser
    download. If SMTP is not configured, the address is wrong, or the send
    fails, it logs and returns False WITHOUT raising — so an export never
    blocks on the email (the user asked that a wrong email must still allow
    the export to proceed).
    """
    if not NOTIFICATION_ENABLED:
        logger.debug("[notify] SMTP not configured — skipping OP DOCX email")
        return False
    if not user_email:
        logger.debug("[notify] No user email — skipping OP DOCX email")
        return False

    try:
        msg = EmailMessage()
        msg.set_charset("utf-8")
        msg["From"] = SMTP_FROM
        msg["To"] = user_email
        forest_label = forest_name or "भा.वन / CF"
        msg["Subject"] = subject or f"✅ कार्ययोजना / Operational Plan — {forest_label}"
        msg.set_content(
            f"आदरणीय महोदय/महोदया,\n\n"
            f"'{forest_name or 'वन'}' को कार्ययोजना (Operational Plan) DOCX फाइल यस इमेलमा संलग्न गरिएको छ।\n"
            f"फाइल: {filename}\n\n"
            f"सादर,\nसामुदायिक वन व्यवस्थापन प्रणाली\n\n"
            f"{'-' * 48}\n\n"
            f"Dear User,\n\n"
            f"Your Operational Plan DOCX for '{forest_name or 'Forest'}' is attached.\n"
            f"File: {filename}\n\n"
            f"Regards,\nCommunity Forest Management System"
        )
        msg.add_attachment(
            docx_bytes,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
        )
    except Exception as e:
        logger.warning("[notify] Failed to build OP DOCX email: %s", e)
        return False

    ok = _smtp_send(msg)
    if ok:
        logger.info("[notify] OP DOCX email sent to %s (%s)", user_email, filename)
    return ok


def send_completion_notification(
    user_email: str,
    calculation_id: UUID,
    success: bool,
    cost_estimate: dict[str, Any] | None = None,
    forest_name: str = "",
) -> bool:
    """Send email notification. Returns True if sent, False if skipped/failed."""
    if not NOTIFICATION_ENABLED:
        logger.debug("[notify] SMTP not configured — skipping notification for %s", calculation_id)
        return False

    if not user_email:
        logger.debug("[notify] No user email — skipping")
        return False

    try:
        msg = EmailMessage()
        msg.set_charset("utf-8")
        msg["From"] = SMTP_FROM
        msg["To"] = user_email
        calc_short = str(calculation_id)[:8]

        forest_label = forest_name or calc_short
        # The recipient's language is not known at send time - the notification
        # is triggered by a background job, not a request - so the body carries
        # both, Nepali first (D5). Same shape as the OP DOCX.
        if success:
            cost_line_ne = ""
            cost_line_en = ""
            if cost_estimate:
                total = cost_estimate.get("total_cost", 0)
                currency = cost_estimate.get("currency", "USD")
                cost_line_ne = f"\n\nगणना लागत: {total:.4f} {currency}"
                cost_line_en = f"\n\nCalculation cost: {total:.4f} {currency}"

            msg["Subject"] = f"✅ गणना पूरा भयो / Calculation Complete — {forest_label}"
            msg.set_content(
                f"आदरणीय महोदय/महोदया,\n\n"
                f"'{forest_name or 'वन'}' को गणना सफलतापूर्वक पूरा भयो।\n"
                f"गणना आईडी: {calculation_id}\n"
                f"अब तपाईं नतिजा हेरेर डिभिजन वन कार्यालय समीक्षाका लागि पेस गर्न सक्नुहुन्छ।"
                f"{cost_line_ne}\n\n"
                f"सादर,\nसामुदायिक वन व्यवस्थापन प्रणाली\n\n"
                f"{'-' * 48}\n\n"
                f"Dear User,\n\n"
                f"Your calculation for '{forest_name or 'Forest'}' has completed successfully.\n"
                f"Calculation ID: {calculation_id}\n"
                f"You can now review the results and submit for DFO review.{cost_line_en}\n\n"
                f"Regards,\nCommunity Forest Management System"
            )
        else:
            msg["Subject"] = f"❌ गणना असफल भयो / Calculation Failed — {forest_label}"
            msg.set_content(
                f"आदरणीय महोदय/महोदया,\n\n"
                f"'{forest_name or 'वन'}' को गणना असफल भयो।\n"
                f"गणना आईडी: {calculation_id}\n"
                f"कृपया त्रुटिको विवरण हेरेर फेरि प्रयास गर्नुहोस्।\n\n"
                f"सादर,\nसामुदायिक वन व्यवस्थापन प्रणाली\n\n"
                f"{'-' * 48}\n\n"
                f"Dear User,\n\n"
                f"Your calculation for '{forest_name or 'Forest'}' has failed.\n"
                f"Calculation ID: {calculation_id}\n"
                f"Please review the error details and try again.\n\n"
                f"Regards,\nCommunity Forest Management System"
            )

        if _smtp_send(msg):
            logger.info("[notify] Completion email sent to %s for calc %s", user_email, calculation_id)
            return True
        return False

    except Exception as e:
        logger.warning("[notify] Failed to build email to %s: %s", user_email, e)
        return False
