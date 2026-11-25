from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OAuthToken(Base):
    """Table à une seule ligne (id=1) : un seul vendeur eBay."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (CheckConstraint("id = 1", name="oauth_tokens_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column()
    refresh_token: Mapped[str] = mapped_column()
    access_token_expires_at: Mapped[dt.datetime] = mapped_column()
    refresh_token_expires_at: Mapped[dt.datetime] = mapped_column()
    scopes: Mapped[str] = mapped_column()
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        UniqueConstraint("run_type", "period_start", name="uq_collection_runs_type_period"),
        CheckConstraint(
            "status in ('running','success','partial','failed')",
            name="ck_collection_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(default="weekly")
    period_start: Mapped[dt.date] = mapped_column()
    period_end: Mapped[dt.date] = mapped_column()
    status: Mapped[str] = mapped_column(default="running")
    started_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    traffic_report_generated_at_7d: Mapped[dt.datetime | None] = mapped_column(default=None)
    traffic_report_generated_at_28d: Mapped[dt.datetime | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)

    content_snapshots: Mapped[list["ListingContentSnapshot"]] = relationship(
        back_populates="run"
    )
    listing_snapshots: Mapped[list["ListingSnapshot"]] = relationship(back_populates="run")


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ebay_item_id: Mapped[str] = mapped_column(unique=True, index=True)
    sku: Mapped[str | None] = mapped_column(default=None)
    title: Mapped[str] = mapped_column()
    price_value: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    price_currency: Mapped[str] = mapped_column(default="EUR")
    quantity: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="active")
    ebay_start_time: Mapped[dt.datetime | None] = mapped_column(default=None)
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(default=None)

    families: Mapped[list["ListingFamily"]] = relationship(back_populates="listing")
    content_snapshots: Mapped[list["ListingContentSnapshot"]] = relationship(
        back_populates="listing"
    )
    traffic_snapshots: Mapped[list["ListingSnapshot"]] = relationship(back_populates="listing")


class ListingContentSnapshot(Base):
    """Titre, item specifics, prix, photos - a chaque collecte. Reconstitue l'etat a une date."""

    __tablename__ = "listing_content_snapshots"
    __table_args__ = (
        UniqueConstraint("listing_id", "run_id", name="uq_content_snapshot_listing_run"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"))
    collected_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    title: Mapped[str] = mapped_column()
    item_specifics: Mapped[dict] = mapped_column(JSONB, default=dict)
    price_value: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    photo_count: Mapped[int] = mapped_column(default=0)
    quantity: Mapped[int | None] = mapped_column(default=None)

    listing: Mapped["Listing"] = relationship(back_populates="content_snapshots")
    run: Mapped["CollectionRun"] = relationship(back_populates="content_snapshots")


class ListingSnapshot(Base):
    """Metriques de trafic (Sell Analytics getTrafficReport), par run et par fenetre 7j/28j."""

    __tablename__ = "listing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "listing_id", "run_id", "window", name="uq_listing_snapshot_listing_run_window"
        ),
        CheckConstraint('"window" in (\'7d\',\'28d\')', name="ck_listing_snapshot_window"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"))
    window: Mapped[str] = mapped_column()

    impressions_search_results: Mapped[int | None] = mapped_column(default=None)
    impressions_store: Mapped[int | None] = mapped_column(default=None)
    impressions_total: Mapped[int | None] = mapped_column(default=None)
    total_impressions: Mapped[int | None] = mapped_column(default=None)
    click_through_rate: Mapped[float | None] = mapped_column(Numeric(7, 4), default=None)
    views_total: Mapped[int | None] = mapped_column(default=None)
    sales_conversion_rate: Mapped[float | None] = mapped_column(Numeric(7, 4), default=None)
    transactions: Mapped[int | None] = mapped_column(default=None)

    listing: Mapped["Listing"] = relationship(back_populates="traffic_snapshots")
    run: Mapped["CollectionRun"] = relationship(back_populates="listing_snapshots")


class PartFamily(Base):
    """Alimentee manuellement par l'utilisateur - permet l'agregation par famille de piece."""

    __tablename__ = "part_families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    vehicle: Mapped[str | None] = mapped_column(default=None)
    brand: Mapped[str | None] = mapped_column(default=None)
    platform: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)

    listings: Mapped[list["ListingFamily"]] = relationship(back_populates="family")


class ListingFamily(Base):
    __tablename__ = "listing_family"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    family_id: Mapped[int] = mapped_column(
        ForeignKey("part_families.id", ondelete="CASCADE"), primary_key=True
    )

    listing: Mapped["Listing"] = relationship(back_populates="families")
    family: Mapped["PartFamily"] = relationship(back_populates="listings")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    ebay_order_id: Mapped[str] = mapped_column(unique=True, index=True)
    creation_date: Mapped[dt.datetime] = mapped_column()
    order_total_value: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    currency: Mapped[str] = mapped_column(default="EUR")
    status: Mapped[str | None] = mapped_column(default=None)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint(
            "order_id", "ebay_line_item_id", name="uq_order_items_order_line_item"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), default=None
    )
    ebay_line_item_id: Mapped[str] = mapped_column()
    quantity: Mapped[int] = mapped_column(default=1)
    price_value: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    delivery_cost: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    commission_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    commission_currency: Mapped[str] = mapped_column(default="EUR")

    order: Mapped["Order"] = relationship(back_populates="items")
    listing: Mapped["Listing | None"] = relationship()


class ChangeProposal(Base):
    """Anticipee pour la phase 2 (moteur de proposition) - table vide en phase 1."""

    __tablename__ = "change_proposals"
    __table_args__ = (
        CheckConstraint("field_changed in ('title','price')", name="ck_proposal_field"),
        CheckConstraint(
            "status in ('pending','approved','rejected','applied')", name="ck_proposal_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    field_changed: Mapped[str] = mapped_column()
    old_value: Mapped[str] = mapped_column()
    proposed_value: Mapped[str] = mapped_column()
    rationale: Mapped[str | None] = mapped_column(default=None)
    metrics_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("listing_snapshots.id"), default=None
    )
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class ChangeLog(Base):
    """Coeur du systeme : journal immuable des modifications reellement appliquees."""

    __tablename__ = "change_log"
    __table_args__ = (
        CheckConstraint("field_changed in ('title','price')", name="ck_change_log_field"),
        CheckConstraint(
            "origin in ('auto_proposal','manual')", name="ck_change_log_origin"
        ),
        CheckConstraint(
            "evaluation_verdict is null or evaluation_verdict in "
            "('improved','worsened','inconclusive')",
            name="ck_change_log_verdict",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("change_proposals.id"), default=None
    )
    changed_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    field_changed: Mapped[str] = mapped_column()
    old_value: Mapped[str] = mapped_column()
    new_value: Mapped[str] = mapped_column()
    origin: Mapped[str] = mapped_column()

    metrics_at_change_id: Mapped[int | None] = mapped_column(
        ForeignKey("listing_snapshots.id"), default=None
    )
    evaluated_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    evaluation_window: Mapped[str | None] = mapped_column(default=None)
    metrics_after_id: Mapped[int | None] = mapped_column(
        ForeignKey("listing_snapshots.id"), default=None
    )
    evaluation_verdict: Mapped[str | None] = mapped_column(default=None)
    evaluation_notes: Mapped[str | None] = mapped_column(default=None)


class AlertState(Base):
    """Dernier envoi de chaque alerte de surveillance, pour ne pas la repeter
    a chaque verification ni apres chaque redeploiement."""

    __tablename__ = "alert_state"

    key: Mapped[str] = mapped_column(primary_key=True)
    last_sent_at: Mapped[dt.datetime] = mapped_column()
