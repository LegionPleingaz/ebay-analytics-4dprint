"""Collecte du trafic (Sell Analytics getTrafficReport), fenetres 7j et 28j.

NB parsing : la forme exacte du payload (dimensionValues/metricValues) suit la
doc eBay au moment de l'ecriture ; a reverifier contre une reponse reelle
(sandbox ou prod) avant mise en prod, la doc en ligne n'etant pas garantie
figee. Le parsing est defensif (.get()) pour ne pas casser sur un champ
inattendu plutot que de silencieusement mal calculer une metrique.
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
    for dv in record.get("dimensionValues", []):
        if dv.get("dimensionKey") == "LISTING":
            return dv.get("dimensionValue")
    return None


def _extract_metrics(record: dict) -> dict:
    values = {}
    for mv in record.get("metricValues", []):
        column = _METRIC_TO_COLUMN.get(mv.get("metricKey"))
        if column:
            raw = mv.get("value")
            values[column] = float(raw) if raw not in (None, "") else None
    return values


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

    generated_at_raw = report.get("generatedDate") or report.get("lastUpdatedDate")
    generated_at = None
    if generated_at_raw:
        generated_at = dt.datetime.fromisoformat(generated_at_raw.replace("Z", "+00:00"))

    records = report.get("records", [])
    logger.info("collect.traffic.window", window=window, records=len(records))

    for record in records:
        item_id = _extract_item_id(record)
        listing = listings_by_item_id.get(item_id)
        if listing is None:
            logger.warning("collect.traffic.unknown_listing", item_id=item_id)
            continue

        metrics = _extract_metrics(record)
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
