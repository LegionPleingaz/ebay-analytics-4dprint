"""Sell Finances API - getTransactions.

Doc: https://developer.ebay.com/api-docs/sell/finances/resources/transaction/methods/getTransactions
Scope: https://api.ebay.com/oauth/api_scope/sell.finances

Fournit les commissions (FINAL_VALUE_FEE_FIXED_PER_ORDER et similaires) par
orderId/orderLineItemId, absentes de la reponse getOrders du Fulfillment API.
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
        f"{settings.ebay_api_base}/sell/finances/v1/transaction",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
        },
        params={"filter": filter_str, "limit": PAGE_LIMIT, "offset": offset},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_transactions(
    access_token: str,
    *,
    start: dt.datetime,
    end: dt.datetime,
    settings: Settings | None = None,
) -> list[dict]:
    settings = settings or get_settings()
    filter_str = (
        f"transactionDate:[{_iso_z(start)}..{_iso_z(end)}],transactionType:{{SALE}}"
    )

    transactions: list[dict] = []
    offset = 0
    while True:
        page = _get_page(access_token, filter_str=filter_str, offset=offset, settings=settings)
        page_txns = page.get("transactions", [])
        transactions.extend(page_txns)
        offset += PAGE_LIMIT
        if offset >= page.get("total", 0) or not page_txns:
            break
    return transactions


def fees_by_order_line_item(transactions: list[dict]) -> dict[tuple[str, str], float]:
    """Agrege les fees (valeur absolue) par (orderId, lineItemId)."""
    totals: dict[tuple[str, str], float] = {}
    for txn in transactions:
        order_id = txn.get("orderId")
        for line_item in txn.get("orderLineItems", []):
            line_item_id = line_item.get("lineItemId")
            fee_total = sum(
                abs(float(m.get("amount", {}).get("value", 0)))
                for m in line_item.get("marketplaceFees", [])
            )
            if order_id and line_item_id:
                key = (order_id, line_item_id)
                totals[key] = totals.get(key, 0.0) + fee_total
    return totals
