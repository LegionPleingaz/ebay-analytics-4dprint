"""Sell Fulfillment API - getOrders.

Doc: https://developer.ebay.com/api-docs/sell/fulfillment/resources/order/methods/getOrders
Scope: https://api.ebay.com/oauth/api_scope/sell.fulfillment
Filtre date: creationdate:[2026-08-01T00:00:00.000Z..2026-08-08T00:00:00.000Z]

Donne pricingSummary (priceSubtotal, deliveryCost) mais PAS les commissions
(final value fee) : celles-ci viennent de la Finances API (finances_client.py).
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.config import Settings, get_settings
from app.ebay.retry import with_ebay_retry

PAGE_LIMIT = 200


def _iso_z(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@with_ebay_retry
def _get_page(
    access_token: str, *, filter_str: str, offset: int, settings: Settings
) -> dict:
    response = httpx.get(
        f"{settings.ebay_api_base}/sell/fulfillment/v1/order",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
        },
        params={"filter": filter_str, "limit": PAGE_LIMIT, "offset": offset},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_orders(
    access_token: str,
    *,
    start: dt.datetime,
    end: dt.datetime,
    settings: Settings | None = None,
) -> list[dict]:
    settings = settings or get_settings()
    filter_str = f"creationdate:[{_iso_z(start)}..{_iso_z(end)}]"

    orders: list[dict] = []
    offset = 0
    while True:
        page = _get_page(access_token, filter_str=filter_str, offset=offset, settings=settings)
        page_orders = page.get("orders", [])
        orders.extend(page_orders)
        offset += PAGE_LIMIT
        if offset >= page.get("total", 0) or not page_orders:
            break
    return orders
