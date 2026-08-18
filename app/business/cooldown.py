"""Regles metier qui conditionnent la validite des mesures (cf. brief).

Ces regles ne sont pas des preferences : les violer rend les mesures
d'effet inexploitables. La logique pure (testable sans DB) est separee des
requetes SQL pour faciliter les tests unitaires.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChangeLog

COOLDOWN_DAYS = 14
MAX_CHANGES_PER_WEEK = 3
VALID_FIELDS = ("title", "price")


class RuleViolation(Exception):
    pass


class CooldownActive(RuleViolation):
    pass


class WeeklyBudgetExceeded(RuleViolation):
    pass


class InvalidFieldChange(RuleViolation):
    pass


# --- Logique pure, testable sans base de donnees ---------------------------


def is_cooldown_active(
    last_change_at: dt.datetime | None,
    now: dt.datetime,
    cooldown_days: int = COOLDOWN_DAYS,
) -> bool:
    """Une annonce modifiee il y a moins de `cooldown_days` ne peut pas etre reproposee."""
    if last_change_at is None:
        return False
    return (now - last_change_at) < dt.timedelta(days=cooldown_days)


def weekly_budget_exceeded(
    changes_in_last_7_days: int, max_per_week: int = MAX_CHANGES_PER_WEEK
) -> bool:
    """Trois modifications maximum par semaine sur l'ensemble du catalogue.

    Fenetre glissante de 7 jours (pas semaine calendaire), coherente avec les
    fenetres de mesure utilisees ailleurs dans le systeme.
    """
    return changes_in_last_7_days >= max_per_week


def validate_field_change(field_changed: str) -> None:
    """Jamais titre et prix modifies ensemble : un change_log ne porte qu'un seul champ."""
    if field_changed not in VALID_FIELDS:
        raise InvalidFieldChange(
            f"field_changed doit etre l'un de {VALID_FIELDS}, recu {field_changed!r}"
        )


@dataclass
class ProposalCheck:
    listing_id: int
    field_changed: str
    now: dt.datetime
    last_change_at: dt.datetime | None
    changes_in_last_7_days: int

    def validate(self) -> None:
        validate_field_change(self.field_changed)
        if is_cooldown_active(self.last_change_at, self.now):
            raise CooldownActive(
                f"listing {self.listing_id}: derniere modification le "
                f"{self.last_change_at}, cooldown {COOLDOWN_DAYS}j actif"
            )
        if weekly_budget_exceeded(self.changes_in_last_7_days):
            raise WeeklyBudgetExceeded(
                f"budget hebdomadaire atteint ({self.changes_in_last_7_days}/"
                f"{MAX_CHANGES_PER_WEEK}) : aucune nouvelle modification cette semaine"
            )


# --- Requetes DB -------------------------------------------------------------


def get_last_change_at(db: Session, listing_id: int) -> dt.datetime | None:
    stmt = (
        select(ChangeLog)
        .where(ChangeLog.listing_id == listing_id)
        .order_by(ChangeLog.changed_at.desc())
        .limit(1)
    )
    last = db.execute(stmt).scalars().first()
    return last.changed_at if last else None


def count_changes_in_last_7_days(db: Session, now: dt.datetime) -> int:
    window_start = now - dt.timedelta(days=7)
    stmt = select(ChangeLog).where(ChangeLog.changed_at >= window_start, ChangeLog.changed_at <= now)
    return len(db.execute(stmt).scalars().all())


def validate_proposal(db: Session, listing_id: int, field_changed: str, now: dt.datetime) -> None:
    check = ProposalCheck(
        listing_id=listing_id,
        field_changed=field_changed,
        now=now,
        last_change_at=get_last_change_at(db, listing_id),
        changes_in_last_7_days=count_changes_in_last_7_days(db, now),
    )
    check.validate()
