from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.alerting.log_alerter import LogAlerter
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger("alerting.email")

SMTP_TIMEOUT_SECONDS = 20


class EmailAlerter(LogAlerter):
    """Alerte par e-mail (SMTP chiffre uniquement), en plus du log structure."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def alert(self, *, subject: str, message: str, severity: str = "error") -> bool:
        super().alert(subject=subject, message=message, severity=severity)
        try:
            self._send(subject, message, severity)
        except Exception as exc:  # noqa: BLE001 - cf. contrat Alerter.alert
            logger.error("alert.email_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        return True

    def _send(self, subject: str, message: str, severity: str) -> None:
        s = self.settings
        mail = EmailMessage()
        mail["From"] = s.alert_email_from
        mail["To"] = s.alert_email_to
        mail["Subject"] = f"[ebay-analytics][{severity}] {subject}"
        mail.set_content(message)

        context = ssl.create_default_context()
        if s.smtp_port == 465:
            server = smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            )
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        with server:
            if s.smtp_port != 465:
                server.starttls(context=context)  # leve si non supporte
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password.get_secret_value())
            server.send_message(mail)
