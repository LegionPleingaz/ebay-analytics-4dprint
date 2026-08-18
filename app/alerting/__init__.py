from app.alerting.base import Alerter
from app.alerting.log_alerter import LogAlerter
from app.config import get_settings

_alerter: Alerter | None = None


def get_alerter() -> Alerter:
    global _alerter
    if _alerter is None:
        backend = get_settings().alerting_backend
        if backend == "log":
            _alerter = LogAlerter()
        else:
            raise ValueError(f"Backend d'alerting inconnu: {backend}")
    return _alerter
