"""Perimetre d'analyse : une annonce sans SKU n'est pas une vente professionnelle.

La collecte enregistre toutes les annonces ; la detection, les propositions et
les analyses de ventes pro ne retiennent que celles-ci. Le prefixe du SKU est
libre. Les variantes (couleurs, tailles, lots) ne sont pas suivies : un SKU sur
une variante suffit a classer l'annonce.
"""

from __future__ import annotations

from app.db.models import Listing


def is_professional(listing: Listing) -> bool:
    return bool((listing.sku or "").strip())
