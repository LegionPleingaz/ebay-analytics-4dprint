"""Surveillance integree a l'application web, independante de la Scheduled Task.

Le job alerte lui-meme sur ses echecs, mais il ne peut pas signaler qu'il n'a
pas tourne. Cette boucle detecte : collecte absente ou en retard, job bloque,
autorisation eBay absente, refusee ou bientot expiree, base injoignable.
Elle ne couvre pas l'arret du serveur ou du conteneur (surveillance externe).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerting import Alerter, get_alerter
from app.config import Settings, get_settings
from app.db.base import get_session_factory
from app.db.models import AlertState, CollectionRun, OAuthToken
from app.ebay.oauth import get_valid_access_token
from app.logging_config import get_logger

logger = get_logger("watchdog")

CHECK_INTERVAL = dt.timedelta(hours=6)
STARTUP_DELAY_SECONDS = 60
REPEAT_AFTER = dt.timedelta(days=3)
STALE_RUN_THRESHOLD = dt.timedelta(days=9)  # hebdomadaire + 2 jours de marge
STUCK_RUN_THRESHOLD = dt.timedelta(hours=2)
REFRESH_EXPIRY_WARNING = dt.timedelta(days=30)

# Anti-repetition quand la base est injoignable (l'etat ne peut pas y etre lu).
_database_alert_sent_at: dt.datetime | None = None


@dataclass(frozen=True)
class Problem:
    key: str
    subject: str
    message: str
    severity: str = "error"


def _aware(value: dt.datetime) -> dt.datetime:
    """SQLite (tests) perd le fuseau ; Postgres le conserve."""
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def find_problems(db: Session, now: dt.datetime) -> list[Problem]:
    problems: list[Problem] = []

    token = db.get(OAuthToken, 1)
    if token is None:
        problems.append(Problem(
            "oauth_missing", "eBay non connecte",
            "Aucun token en base : effectuer le parcours /oauth/login.", "critical"))
    else:
        expires_at = _aware(token.refresh_token_expires_at)
        if expires_at <= now:
            problems.append(Problem(
                "oauth_expired", "Autorisation eBay expiree",
                f"Expiree le {expires_at:%d/%m/%Y}. Refaire /oauth/login.", "critical"))
        elif expires_at - now <= REFRESH_EXPIRY_WARNING:
            problems.append(Problem(
                "oauth_expiring", "Autorisation eBay bientot expiree",
                f"Expire le {expires_at:%d/%m/%Y}. Refaire /oauth/login avant.", "warning"))

    last_run = db.execute(
        select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(1)
    ).scalars().first()
    if last_run is None:
        problems.append(Problem(
            "run_never", "Aucune collecte effectuee",
            "Aucun run en base. Verifier la Scheduled Task Coolify."))
    else:
        age = now - _aware(last_run.started_at)
        if age > STALE_RUN_THRESHOLD:
            problems.append(Problem(
                "run_stale", "Collecte hebdomadaire en retard",
                f"Dernier run il y a {age.days} jours (statut {last_run.status}). "
                "Verifier la Scheduled Task Coolify."))
        elif last_run.status == "running" and age > STUCK_RUN_THRESHOLD:
            problems.append(Problem(
                "run_stuck", "Collecte hebdomadaire bloquee",
                f"Le run {last_run.id} est 'running' depuis plus de 2 heures."))
        elif last_run.status == "failed":
            problems.append(Problem(
                "run_failed", "Derniere collecte en echec",
                last_run.error_message or "Voir les logs."))
    return problems


def notify(db: Session, problems: list[Problem], alerter: Alerter, now: dt.datetime) -> None:
    """Envoie les problemes nouveaux ou non rappeles depuis REPEAT_AFTER."""
    states = {s.key: s for s in db.execute(select(AlertState)).scalars()}
    active = {p.key for p in problems}

    for key, state in states.items():
        if key not in active:  # resolu : une rechute alertera immediatement
            db.delete(state)

    for problem in problems:
        state = states.get(problem.key)
        if state and now - _aware(state.last_sent_at) < REPEAT_AFTER:
            continue
        sent = alerter.alert(
            subject=problem.subject, message=problem.message, severity=problem.severity)
        if not sent:
            continue  # nouvel essai au prochain passage
        if state:
            state.last_sent_at = now
        else:
            db.add(AlertState(key=problem.key, last_sent_at=now))
    db.commit()


def check_token_refresh(db: Session, settings: Settings) -> Problem | None:
    """Rafraichit l'access token si besoin : detecte une revocation sans
    attendre la collecte suivante."""
    if db.get(OAuthToken, 1) is None:
        return None
    try:
        get_valid_access_token(db, settings)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return Problem(
            "oauth_refresh_failed", "Echec du renouvellement du token eBay",
            f"{type(exc).__name__}: {exc}"[:1000], "critical")
    return None


def run_checks(settings: Settings | None = None, alerter: Alerter | None = None) -> None:
    global _database_alert_sent_at
    settings = settings or get_settings()
    alerter = alerter or get_alerter()
    now = dt.datetime.now(dt.timezone.utc)
    try:
        with get_session_factory()() as db:
            refresh_problem = check_token_refresh(db, settings)
            problems = find_problems(db, now)
            if refresh_problem:
                problems.append(refresh_problem)
            notify(db, problems, alerter, now)
        logger.info("watchdog.checked", problems=[p.key for p in problems])
        _database_alert_sent_at = None
    except Exception as exc:  # noqa: BLE001
        logger.error("watchdog.failed", error_type=type(exc).__name__)
        if _database_alert_sent_at is None or now - _database_alert_sent_at >= REPEAT_AFTER:
            if alerter.alert(
                subject="Surveillance ebay-analytics en echec",
                message=f"{type(exc).__name__} pendant la verification (base injoignable ?). "
                        "Voir les logs.",
                severity="critical",
            ):
                _database_alert_sent_at = now


async def watchdog_loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        await asyncio.to_thread(run_checks)
        await asyncio.sleep(CHECK_INTERVAL.total_seconds())
