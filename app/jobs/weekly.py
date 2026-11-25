"""python -m app.jobs.weekly - collecte hebdomadaire (trafic + contenu + commandes).

Declenche par une Scheduled Task Coolify qui execute cette commande dans le
conteneur FastAPI deja demarre en permanence (le job n'est pas concu comme un
process autonome qui termine le container).

Idempotent : rejouable sur la meme periode sans creer de doublons - les
collecteurs font des upserts sur les contraintes d'unicite des tables de
snapshot (listing_id, run_id[, window]) / (order_id, ebay_line_item_id).
"""

from __future__ import annotations

import datetime as dt
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerting import get_alerter
from app.config import Settings, get_settings
from app.db.base import get_session_factory
from app.db.models import CollectionRun
from app.ebay.oauth import OAuthError, get_valid_access_token
from app.jobs.collectors.content import collect_content
from app.jobs.collectors.orders import collect_orders
from app.jobs.collectors.traffic import collect_traffic
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# Fenetre glissante : un run le lundi matin doit couvrir les semaines passees
# (et rattraper un run manque). Les upserts evitent les doublons.
ORDERS_LOOKBACK = dt.timedelta(days=90)


def _iso_week_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _get_or_create_run(db: Session, period_start: dt.date, period_end: dt.date, now: dt.datetime) -> CollectionRun:
    run = db.execute(
        select(CollectionRun).where(
            CollectionRun.run_type == "weekly", CollectionRun.period_start == period_start
        )
    ).scalar_one_or_none()
    if run is None:
        run = CollectionRun(
            run_type="weekly",
            period_start=period_start,
            period_end=period_end,
            status="running",
            started_at=now,
        )
        db.add(run)
    else:
        # Rejoue de la meme semaine : on reset l'etat mais on garde le meme id
        # (les upserts des collecteurs geren la re-collecte sans doublon).
        run.status = "running"
        run.started_at = now
        run.error_message = None
    db.commit()
    db.refresh(run)
    return run


def _mark_failed(db: Session, period_start: dt.date, error_message: str) -> None:
    db.rollback()
    run = db.execute(
        select(CollectionRun).where(
            CollectionRun.run_type == "weekly", CollectionRun.period_start == period_start
        )
    ).scalar_one_or_none()
    if run is not None:
        run.status = "failed"
        run.error_message = error_message[:2000]
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()


def run_weekly_job(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    alerter = get_alerter()

    db = get_session_factory()()
    now = dt.datetime.now(settings.tzinfo)
    period_start = _iso_week_monday(now.date())
    period_end = period_start + dt.timedelta(days=6)

    try:
        run = _get_or_create_run(db, period_start, period_end, now)
        logger.info("weekly_job.start", run_id=run.id, period_start=str(period_start))

        access_token = get_valid_access_token(db, settings)

        listings_by_item_id = collect_content(db, run, access_token)
        traffic_warning = collect_traffic(db, run, access_token, listings_by_item_id)
        orders_warning = collect_orders(
            db,
            run,
            access_token,
            period_start=now - ORDERS_LOOKBACK,
            period_end=now,
        )

        warning = "\n".join(filter(None, (traffic_warning, orders_warning))) or None
        run.status = "partial" if warning else "success"
        run.error_message = warning[:2000] if warning else None
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        if warning:
            alerter.alert(
                subject="Collecte hebdomadaire eBay : partielle",
                message=warning,
                severity="warning",
            )
        logger.info("weekly_job.done", run_id=run.id, status=run.status)
        return 0

    except OAuthError as exc:
        logger.error("weekly_job.oauth_failed", error=str(exc))
        alerter.alert(
            subject="Collecte hebdomadaire eBay : echec OAuth",
            message=str(exc),
            severity="critical",
        )
        _mark_failed(db, period_start, str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - job CLI : catch large pour alerter + exit non-zero
        logger.error("weekly_job.failed", error=str(exc))
        alerter.alert(
            subject="Collecte hebdomadaire eBay : echec",
            message=str(exc),
            severity="error",
        )
        _mark_failed(db, period_start, str(exc))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run_weekly_job())
