"""Collecte du trafic (Sell Analytics getTrafficReport), fenetres 7j et 28j.

NB parsing : structure Report/Header/Record tiree de la specification OpenAPI
(miroir tiers). L'alignement metricValues <-> header.metrics est a confirmer sur
la premiere reponse reelle.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import CollectionRun, Listing, ListingSnapshot
from app.ebay import analytics_client
from app.logging_config import get_logger

logger = get_logger(__name__)

_METRIC_TO_COLUMN = {
    "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE": "impressions_search_results",
    "LISTING_IMPRESSION_STORE": "impressions_store",
    "LISTING_IMPRESSION_TOTAL": "impressions_total",
    "TOTAL_IMPRESSION_TOTAL": "total_impressions",
    "CLICK_THROUGH_RATE": "click_through_rate",
    "LISTING_VIEWS_TOTAL": "views_total",
    "SALES_CONVERSION_RATE": "sales_conversion_rate",
    "TRANSACTION": "transactions",
}


def _extract_item_id(record: dict) -> str | None:
    """Avec dimension=LISTING, la seule valeur de dimension est l'ID d'annonce."""
    values = record.get("dimensionValues", [])
    return str(values[0]["value"]) if values and values[0].get("value") else None


def _metric_keys(report: dict) -> list[str]:
    return [m["key"] for m in report.get("header", {}).get("metrics", [])]


def _extract_metrics(record: dict, metric_keys: list[str]) -> dict:
    """Les metricValues n'ont pas de nom : leur ordre suit celui de l'en-tete."""
    values = record.get("metricValues", [])
    if len(values) != len(metric_keys):
        raise ValueError(
            f"Rapport de trafic incoherent : {len(metric_keys)} metriques en en-tete, "
            f"{len(values)} valeurs"
        )
    metrics = {}
    for key, entry in zip(metric_keys, values):
        column = _METRIC_TO_COLUMN.get(key)
        if column:
            raw = entry.get("value") if entry.get("applicable", True) else None
            metrics[column] = float(raw) if raw not in (None, "") else None
    return metrics


def _collect_window(
    db: Session,
    run: CollectionRun,
    access_token: str,
    listings_by_item_id: dict[str, Listing],
    *,
    window: str,
    days: int,
    now: dt.datetime,
) -> dt.datetime | None:
    start = now - dt.timedelta(days=days)
    report = analytics_client.get_traffic_report(access_token, start=start, end=now)

    generated_at_raw = report.get("lastUpdatedDate")
    generated_at = None
    if generated_at_raw:
        generated_at = dt.datetime.fromisoformat(generated_at_raw.replace("Z", "+00:00"))

    records = report.get("records", [])
    metric_keys = _metric_keys(report)
    missing = set(_METRIC_TO_COLUMN) - set(metric_keys)
    if records and missing:
        # Echouer bruyamment plutot que d'enregistrer des lignes vides.
        raise ValueError(f"Metriques absentes du rapport de trafic : {sorted(missing)}")
    logger.info("collect.traffic.window", window=window, records=len(records))

    for record in records:
        item_id = _extract_item_id(record)
        listing = listings_by_item_id.get(item_id)
        if listing is None:
            logger.warning("collect.traffic.unknown_listing", item_id=item_id)
            continue

        metrics = _extract_metrics(record, metric_keys)
        stmt = pg_insert(ListingSnapshot).values(
            listing_id=listing.id,
            run_id=run.id,
            window=window,
            **metrics,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["listing_id", "run_id", "window"],
            set_={col: stmt.excluded[col] for col in metrics},
        )
        db.execute(stmt)

    return generated_at


def collect_traffic(
    db: Session,
    run: CollectionRun,
    access_token: str,
    listings_by_item_id: dict[str, Listing],
) -> None:
    now = run.started_at

    run.traffic_report_generated_at_7d = _collect_window(
        db, run, access_token, listings_by_item_id, window="7d", days=7, now=now
    )
    run.traffic_report_generated_at_28d = _collect_window(
        db, run, access_token, listings_by_item_id, window="28d", days=28, now=now
    )
    db.commit()
