from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.alerting.log_alerter import LogAlerter
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger("alerting.email")

SMTP_TIMEOUT_SECONDS = 20


def send_email(settings: Settings, subject: str, body: str) -> None:
    """Envoi SMTP chiffre. Leve en cas d'echec."""
    mail = EmailMessage()
    mail["From"] = settings.alert_email_from
    mail["To"] = settings.alert_email_to
    mail["Subject"] = subject
    mail.set_content(body)

    context = ssl.create_default_context()
    implicit_tls = settings.smtp_port == 465
    if implicit_tls:
        server = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS, context=context
        )
    else:
        server = smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        )
    with server:
        if not implicit_tls:
            server.starttls(context=context)  # leve si non supporte
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        server.send_message(mail)


class EmailAlerter(LogAlerter):
    """Alerte par e-mail (SMTP chiffre uniquement), en plus du log structure."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def alert(self, *, subject: str, message: str, severity: str = "error") -> bool:
        super().alert(subject=subject, message=message, severity=severity)
        try:
            send_email(self.settings, f"[ebay-analytics][{severity}] {subject}", message)
        except Exception as exc:  # noqa: BLE001 - cf. contrat Alerter.alert
            logger.error("alert.email_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        return True
