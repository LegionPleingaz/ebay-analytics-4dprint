"""Detection des problemes d'annonces. Logique pure, sans base de donnees.

La fenetre 7 jours n'est jamais utilisee. La visibilite se juge sur 28 jours ;
le taux de clic et l'absence de vente sur 90 jours, sauf si l'annonce a change
pendant ces 90 jours (retour a 28 jours pour ne pas melanger deux versions).
En cas de base insuffisante, aucune conclusion n'est tiree.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from app.business.cooldown import is_cooldown_active
from app.business.thresholds import Thresholds

WINDOW_DAYS = 28
LONG_WINDOW_DAYS = 90


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
    metrics: Metrics | None  # 28 jours ; None : absente du rapport de trafic
    last_change_at: dt.datetime | None
    metrics_90d: Metrics | None = None


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
    metrics: Metrics  # celles qui ont declenche l'alerte
    window_days: int
    mixes_versions: bool = False  # la periode contient l'ancienne version


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

    changed_ago = None if candidate.last_change_at is None else data_at - candidate.last_change_at
    changed_recently = changed_ago is not None and changed_ago < dt.timedelta(days=LONG_WINDOW_DAYS)
    long_metrics, long_days = m, WINDOW_DAYS
    if not changed_recently and candidate.metrics_90d is not None:
        long_metrics, long_days = candidate.metrics_90d, LONG_WINDOW_DAYS
    mixes = changed_ago is not None and changed_ago < dt.timedelta(days=WINDOW_DAYS)

    findings: list[Finding] = []
    lm = long_metrics
    if (
        lm.views is not None
        and lm.transactions is not None
        and lm.transactions == 0
        and lm.views > thresholds.no_sale_views_over
    ):
        findings.append(Finding(Kind.NO_SALE, candidate, lm, long_days, mixes))
    # eBay semble renvoyer le CTR avec 2 decimales : "< 0.01" ne retient que les
    # valeurs surement sous 1 %, au prix de quelques cas proches non signales.
    if (
        lm.impressions is not None
        and lm.impressions >= thresholds.ctr_min_impressions
        and lm.click_through_rate is not None
        and lm.click_through_rate < thresholds.ctr_min
    ):
        findings.append(Finding(Kind.LOW_CTR, candidate, lm, long_days, mixes))
    if m.impressions <= thresholds.low_impressions_max:
        findings.append(Finding(Kind.LOW_VISIBILITY, candidate, m, WINDOW_DAYS, mixes))
    return findings


def sort_key(finding: Finding) -> tuple[int, int]:
    m = finding.metrics
    weight = {
        Kind.NO_SALE: -(m.views or 0),
        Kind.LOW_CTR: -(m.impressions or 0),
        Kind.LOW_VISIBILITY: m.impressions or 0,
    }[finding.kind]
    return list(Kind).index(finding.kind), weight
