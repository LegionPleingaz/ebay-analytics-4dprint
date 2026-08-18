from app.alerting.base import Alerter
from app.logging_config import get_logger

logger = get_logger("alerting")


class LogAlerter(Alerter):
    """Implementation phase 1 : log structure exploitable depuis Coolify.

    Une panne silencieuse ne doit pas se decouvrir 3 semaines plus tard : ces
    logs doivent etre au minimum surveilles manuellement jusqu'a ce qu'un
    canal reel (email/Slack) soit branche sur l'interface Alerter.
    """

    def alert(self, *, subject: str, message: str, severity: str = "error") -> None:
        log_method = {
            "warning": logger.warning,
            "error": logger.error,
            "critical": logger.critical,
        }.get(severity, logger.error)
        log_method("alert", subject=subject, message=message, severity=severity)
