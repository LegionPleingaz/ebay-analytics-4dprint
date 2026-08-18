"""schema initial

Revision ID: 0001
Revises:
Create Date: 2026-08-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scopes", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="oauth_tokens_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("traffic_report_generated_at_7d", sa.DateTime(timezone=True), nullable=True),
        sa.Column("traffic_report_generated_at_28d", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status in ('running','success','partial','failed')",
            name="ck_collection_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_type", "period_start", name="uq_collection_runs_type_period"),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ebay_item_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("price_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_currency", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ebay_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_listings_ebay_item_id", "listings", ["ebay_item_id"], unique=True)

    op.create_table(
        "listing_content_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("item_specifics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("price_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["collection_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "run_id", name="uq_content_snapshot_listing_run"),
    )

    op.create_table(
        "listing_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("window", sa.String(), nullable=False),
        sa.Column("impressions_search_results", sa.Integer(), nullable=True),
        sa.Column("impressions_store", sa.Integer(), nullable=True),
        sa.Column("impressions_total", sa.Integer(), nullable=True),
        sa.Column("total_impressions", sa.Integer(), nullable=True),
        sa.Column("click_through_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("views_total", sa.Integer(), nullable=True),
        sa.Column("sales_conversion_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("transactions", sa.Integer(), nullable=True),
        sa.CheckConstraint("window in ('7d','28d')", name="ck_listing_snapshot_window"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["collection_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "listing_id", "run_id", "window", name="uq_listing_snapshot_listing_run_window"
        ),
    )

    op.create_table(
        "part_families",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("vehicle", sa.String(), nullable=True),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "listing_family",
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["family_id"], ["part_families.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("listing_id", "family_id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ebay_order_id", sa.String(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_total_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_ebay_order_id", "orders", ["ebay_order_id"], unique=True)

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=True),
        sa.Column("ebay_line_item_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("delivery_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("commission_fee", sa.Numeric(10, 2), nullable=True),
        sa.Column("commission_currency", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "ebay_line_item_id", name="uq_order_items_order_line_item"
        ),
    )

    op.create_table(
        "change_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("field_changed", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=False),
        sa.Column("proposed_value", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=True),
        sa.Column("metrics_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("field_changed in ('title','price')", name="ck_proposal_field"),
        sa.CheckConstraint(
            "status in ('pending','approved','rejected','applied')", name="ck_proposal_status"
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["metrics_snapshot_id"], ["listing_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "change_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("field_changed", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=False),
        sa.Column("new_value", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("metrics_at_change_id", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluation_window", sa.String(), nullable=True),
        sa.Column("metrics_after_id", sa.Integer(), nullable=True),
        sa.Column("evaluation_verdict", sa.String(), nullable=True),
        sa.Column("evaluation_notes", sa.String(), nullable=True),
        sa.CheckConstraint("field_changed in ('title','price')", name="ck_change_log_field"),
        sa.CheckConstraint("origin in ('auto_proposal','manual')", name="ck_change_log_origin"),
        sa.CheckConstraint(
            "evaluation_verdict is null or evaluation_verdict in "
            "('improved','worsened','inconclusive')",
            name="ck_change_log_verdict",
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["change_proposals.id"]),
        sa.ForeignKeyConstraint(["metrics_at_change_id"], ["listing_snapshots.id"]),
        sa.ForeignKeyConstraint(["metrics_after_id"], ["listing_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("change_log")
    op.drop_table("change_proposals")
    op.drop_table("order_items")
    op.drop_index("ix_orders_ebay_order_id", table_name="orders")
    op.drop_table("orders")
    op.drop_table("listing_family")
    op.drop_table("part_families")
    op.drop_table("listing_snapshots")
    op.drop_table("listing_content_snapshots")
    op.drop_index("ix_listings_ebay_item_id", table_name="listings")
    op.drop_table("listings")
    op.drop_table("collection_runs")
    op.drop_table("oauth_tokens")
