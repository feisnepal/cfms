"""
Tests for calculation email notification service.
"""
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.services.calculation_notification_service import send_completion_notification


class TestSendCompletionNotification:
    def test_skips_when_smtp_not_configured(self):
        with patch("app.services.calculation_notification_service.NOTIFICATION_ENABLED", False):
            result = send_completion_notification("test@example.com", uuid4(), True)
            assert result is False

    def test_skips_when_no_email(self):
        result = send_completion_notification("", uuid4(), True)
        assert result is False

    @patch("app.services.calculation_notification_service.smtplib.SMTP")
    def test_sends_success_email(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        cid = uuid4()

        with patch("app.services.calculation_notification_service.NOTIFICATION_ENABLED", True):
            with patch("app.services.calculation_notification_service.SMTP_HOST", "smtp.test.com"):
                result = send_completion_notification("user@test.com", cid, True, {
                    "total_cost": 0.15, "currency": "USD",
                }, "Test Forest")

        assert result is True
        mock_server.send_message.assert_called_once()
        msg = mock_server.send_message.call_args[0][0]
        assert "Calculation Complete" in msg["Subject"]
        assert "Test Forest" in msg["Subject"]
        assert "0.1500 USD" in msg.get_content()

    @patch("app.services.calculation_notification_service.smtplib.SMTP")
    def test_sends_failure_email(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        cid = uuid4()

        with patch("app.services.calculation_notification_service.NOTIFICATION_ENABLED", True):
            result = send_completion_notification("user@test.com", cid, False)

        assert result is True
        msg = mock_server.send_message.call_args[0][0]
        assert "Calculation Failed" in msg["Subject"]
