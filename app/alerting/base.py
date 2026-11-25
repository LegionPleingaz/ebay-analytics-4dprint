"""Interface d'alerting abstraite.

Phase 1 : seule l'implementation log existe (LogAlerter). Le canal reel
(email, Slack, etc.) sera branche plus tard sans changer les appelants -
ils dependent uniquement de cette interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Alerter(ABC):
    @abstractmethod
    def alert(self, *, subject: str, message: str, severity: str = "error") -> bool:
        """Emet une alerte. severity: 'warning' | 'error' | 'critical'.

        Retourne False si l'envoi a echoue. Ne leve jamais : un probleme
        d'alerting ne doit pas masquer la panne signalee.
        """
        raise NotImplementedError
