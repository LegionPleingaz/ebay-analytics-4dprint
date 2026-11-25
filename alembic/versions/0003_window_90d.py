"""fenetre de trafic 90 jours

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "ck_listing_snapshot_window"


def upgrade() -> None:
    op.drop_constraint(_NAME, "listing_snapshots", type_="check")
    op.create_check_constraint(_NAME, "listing_snapshots", "\"window\" in ('7d','28d','90d')")


def downgrade() -> None:
    # Echoue volontairement si des snapshots 90d existent : pas de suppression
    # silencieuse d'historique.
    op.drop_constraint(_NAME, "listing_snapshots", type_="check")
    op.create_check_constraint(_NAME, "listing_snapshots", "\"window\" in ('7d','28d')")
