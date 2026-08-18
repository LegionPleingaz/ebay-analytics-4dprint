"""Sell Analytics API - getTrafficReport.

Doc: https://developer.ebay.com/api-docs/sell/analytics/resources/traffic_report/methods/getTrafficReport

- dimension=LISTING sans listing_ids est plafonne a 200 annonces (largement suffisant, ~30 annonces).
- date_range utilise la forme ISO 8601 avec offset UTC explicite, pour eviter
  toute ambiguite liee au fuseau America/Los_Angeles implicite du format court.
- La reponse contient generatedDate (ou similaire par metrique) : les donnees
  ne sont pas temps reel, on le persiste sur le run.
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.config import Settings, get_settings
from app.ebay.retry import with_ebay_retry

METRICS = [
    "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE",
    "LISTING_IMPRESSION_STORE",
    "LISTING_IMPRESSION_TOTAL",
    "TOTAL_IMPRESSION_TOTAL",
    "CLICK_THROUGH_RATE",
    "LISTING_VIEWS_TOTAL",
    "SALES_CONVERSION_RATE",
    "TRANSACTION",
]


def _iso_range(start: dt.datetime, end: dt.datetime) -> str:
    def fmt(d: dt.datetime) -> str:
        d = d.astimezone(dt.timezone.utc)
        return d.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")

    return f"[{fmt(start)}..{fmt(end)}]"


@with_ebay_retry
def get_traffic_report(
    access_token: str,
    *,
    start: dt.datetime,
    end: dt.datetime,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    response = httpx.get(
        f"{settings.ebay_api_base}/sell/analytics/v1/traffic_report",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
        },
        params={
            "dimension": "LISTING",
            "filter": f"marketplaceIds:{{{settings.ebay_marketplace_id}}},"
            f"date_range:{_iso_range(start, end)}",
            "metric": ",".join(METRICS),
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
