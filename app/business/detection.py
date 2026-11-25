"""Detection des problemes d'annonces. Logique pure, sans base de donnees.

Toutes les regles s'appuient sur la fenetre 28 jours, jamais sur 7 jours.
En cas de base insuffisante, aucune conclusion n'est tiree.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from app.business.cooldown import is_cooldown_active
from app.business.thresholds import Thresholds

WINDOW_DAYS = 28


@dataclass(frozen=True)
class Metrics:
    impressions: int | None
    views: int | None
    click_through_rate: float | None
    transactions: int | None


@dataclass(frozen=True)
class Candidate:
    item_id: str
    title: str
    start_time: dt.datetime | None
    quantity: int | None
    specifics_count: int
    metrics: Metrics | None  # None : absente du rapport de trafic
    last_change_at: dt.datetime | None


class Kind(str, Enum):
    # L'ordre de declaration est l'ordre de priorite.
    NO_SALE = "no_sale"
    LOW_CTR = "low_ctr"
    LOW_VISIBILITY = "low_visibility"


class Skip(str, Enum):
    OUT_OF_STOCK = "en rupture de stock"
    TOO_RECENT = "en ligne depuis moins de 28 jours"
    NO_DATA = "pas de données de trafic sur 28 jours"
    COOLDOWN = "modifiée il y a moins de 14 jours"


@dataclass(frozen=True)
class Finding:
    kind: Kind
    candidate: Candidate


def evaluate(
    candidate: Candidate,
    thresholds: Thresholds,
    *,
    data_at: dt.datetime,
    now: dt.datetime,
) -> Skip | list[Finding]:
    """`data_at` : date de la collecte ; `now` : date du rapport (cooldown)."""
    if candidate.quantity == 0:
        return Skip.OUT_OF_STOCK
    if is_cooldown_active(candidate.last_change_at, now):
        return Skip.COOLDOWN
    if candidate.start_time and data_at - candidate.start_time < dt.timedelta(days=WINDOW_DAYS):
        return Skip.TOO_RECENT

    m = candidate.metrics
    if m is None or m.impressions is None:
        return Skip.NO_DATA

    kinds: list[Kind] = []
    if (
        m.views is not None
        and m.transactions is not None
        and m.transactions == 0
        and m.views > thresholds.no_sale_views_over
    ):
        kinds.append(Kind.NO_SALE)
    # eBay semble renvoyer le CTR avec 2 decimales : "< 0.01" ne retient que les
    # valeurs surement sous 1 %, au prix de quelques cas proches non signales.
    if (
        m.impressions >= thresholds.ctr_min_impressions
        and m.click_through_rate is not None
        and m.click_through_rate < thresholds.ctr_min
    ):
        kinds.append(Kind.LOW_CTR)
    if m.impressions <= thresholds.low_impressions_max:
        kinds.append(Kind.LOW_VISIBILITY)
    return [Finding(kind, candidate) for kind in kinds]


def sort_key(finding: Finding) -> tuple[int, int]:
    m = finding.candidate.metrics
    assert m is not None
    weight = {
        Kind.NO_SALE: -(m.views or 0),
        Kind.LOW_CTR: -(m.impressions or 0),
        Kind.LOW_VISIBILITY: m.impressions or 0,
    }[finding.kind]
    return list(Kind).index(finding.kind), weight
