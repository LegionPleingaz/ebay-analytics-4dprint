"""Collecte des commandes (Sell Fulfillment getOrders) + commissions (Sell Finances getTransactions).

getOrders donne les montants (prix, frais de port) mais pas les commissions ;
on les recupere separement via Finances API et on les rattache par
(orderId, lineItemId).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import CollectionRun, Listing, Order, OrderItem
from app.ebay import finances_client, fulfillment_client
from app.logging_config import get_logger

logger = get_logger(__name__)


def collect_orders(
    db: Session,
    run: CollectionRun,
    access_token: str,
    *,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> None:
    orders = fulfillment_client.get_orders(access_token, start=period_start, end=period_end)
    transactions = finances_client.get_transactions(
        access_token, start=period_start, end=period_end
    )
    fees = finances_client.fees_by_order_line_item(transactions)

    logger.info("collect.orders", orders=len(orders), transactions=len(transactions))

    for order_payload in orders:
        ebay_order_id = order_payload["orderId"]
        pricing = order_payload.get("pricingSummary", {})

        stmt = pg_insert(Order).values(
            ebay_order_id=ebay_order_id,
            creation_date=order_payload["creationDate"],
            order_total_value=pricing.get("total", {}).get("value"),
            currency=pricing.get("total", {}).get("currency", "EUR"),
            status=order_payload.get("orderFulfillmentStatus"),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ebay_order_id"],
            set_={
                "order_total_value": stmt.excluded.order_total_value,
                "currency": stmt.excluded.currency,
                "status": stmt.excluded.status,
            },
        ).returning(Order.id)
        order_id = db.execute(stmt).scalar_one()

        for line_item in order_payload.get("lineItems", []):
            line_item_id = line_item["lineItemId"]
            ebay_item_id = line_item.get("legacyItemId") or line_item.get("itemId")
            listing_id = None
            if ebay_item_id:
                listing_id = db.execute(
                    select(Listing.id).where(Listing.ebay_item_id == ebay_item_id)
                ).scalar_one_or_none()

            fee = fees.get((ebay_order_id, line_item_id))

            item_stmt = pg_insert(OrderItem).values(
                order_id=order_id,
                listing_id=listing_id,
                ebay_line_item_id=line_item_id,
                quantity=int(line_item.get("quantity", 1)),
                price_value=line_item.get("lineItemCost", {}).get("value"),
                delivery_cost=line_item.get("deliveryCost", {}).get("value")
                if line_item.get("deliveryCost")
                else None,
                commission_fee=fee,
                commission_currency=line_item.get("lineItemCost", {}).get("currency", "EUR"),
            )
            item_stmt = item_stmt.on_conflict_do_nothing(
                index_elements=["order_id", "ebay_line_item_id"]
            )
            db.execute(item_stmt)

    db.commit()
