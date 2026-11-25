from app.alerting.base import Alerter
from app.alerting.email_alerter import EmailAlerter
from app.alerting.log_alerter import LogAlerter
from app.config import get_settings

_alerter: Alerter | None = None


def get_alerter() -> Alerter:
    global _alerter
    if _alerter is None:
        settings = get_settings()  # backend valide par Settings
        _alerter = (
            EmailAlerter(settings) if settings.alerting_backend == "email" else LogAlerter()
        )
    return _alerter
