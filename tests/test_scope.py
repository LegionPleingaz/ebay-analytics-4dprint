import pytest

from app.business.scope import is_professional
from app.db.models import Listing


@pytest.mark.parametrize("sku,expected", [("4DP-X", True), (None, False), ("", False), ("  ", False)])
def test_listing_is_professional_only_with_sku(sku, expected):
    assert is_professional(Listing(sku=sku)) is expected
