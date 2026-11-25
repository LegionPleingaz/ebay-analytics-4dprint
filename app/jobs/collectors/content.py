"""Collecte du contenu des annonces : GetSellerList (inventaire) + GetItem (detail).

Met a jour `listings` (etat courant) et insere une ligne `listing_content_snapshots`
par annonce pour ce run (idempotent : ON CONFLICT sur (listing_id, run_id)).
"""

from __future__ import annotations

from dateutil import parser as dateutil_parser
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import CollectionRun, Listing, ListingContentSnapshot
from app.ebay import trading_client
from app.logging_config import get_logger

logger = get_logger(__name__)


def _parse_price(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def collect_content(db: Session, run: CollectionRun, access_token: str) -> dict[str, Listing]:
    """Retourne un mapping ebay_item_id -> Listing (utilise par le collecteur trafic)."""
    seller_items = trading_client.get_seller_list(access_token)
    logger.info("collect.content.seller_list", count=len(seller_items))

    listings_by_item_id: dict[str, Listing] = {}

    for row in seller_items:
        item_id = row["item_id"]
        detail = trading_client.get_item(item_id, access_token)

        listing = db.query(Listing).filter_by(ebay_item_id=item_id).one_or_none()
        if listing is None:
            listing = Listing(ebay_item_id=item_id, title=detail["title"])
            db.add(listing)

        listing.title = detail["title"]
        listing.sku = detail["sku"] or row.get("sku")
        listing.price_value = _parse_price(detail.get("price") or row.get("price"))
        listing.price_currency = row.get("currency") or "EUR"
        listing.quantity = int(detail["quantity"]) if detail.get("quantity") else None
        listing.status = row.get("status")
        if row.get("start_time"):
            listing.ebay_start_time = dateutil_parser.isoparse(row["start_time"])
        listing.last_synced_at = run.started_at

        db.flush()  # assure listing.id disponible pour le snapshot

        stmt = pg_insert(ListingContentSnapshot).values(
            listing_id=listing.id,
            run_id=run.id,
            collected_at=run.started_at,
            title=detail["title"],
            item_specifics=detail["item_specifics"],
            price_value=_parse_price(detail.get("price")),
            photo_count=detail["photo_count"],
            quantity=listing.quantity,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["listing_id", "run_id"],
            set_={
                "title": stmt.excluded.title,
                "item_specifics": stmt.excluded.item_specifics,
                "price_value": stmt.excluded.price_value,
                "photo_count": stmt.excluded.photo_count,
                "quantity": stmt.excluded.quantity,
            },
        )
        db.execute(stmt)

        listings_by_item_id[item_id] = listing

    db.commit()
    return listings_by_item_id
