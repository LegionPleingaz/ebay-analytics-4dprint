"""python -m app.alerting.test - envoie une alerte de test sur le canal configure."""

import sys

from app.alerting import get_alerter
from app.config import get_settings
from app.logging_config import configure_logging


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    sent = get_alerter().alert(
        subject="Alerte de test",
        message="Si vous lisez ce message, les alertes fonctionnent.",
        severity="warning",
    )
    print(f"canal={settings.alerting_backend} resultat={'OK' if sent else 'ECHEC'}")
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
