import datetime as dt

import pytest

from app.business.cooldown import (
    COOLDOWN_DAYS,
    MAX_CHANGES_PER_WEEK,
    CooldownActive,
    InvalidFieldChange,
    ProposalCheck,
    WeeklyBudgetExceeded,
    count_changes_in_last_7_days,
    get_last_change_at,
    is_cooldown_active,
    validate_field_change,
    weekly_budget_exceeded,
)
from app.db.models import ChangeLog, Listing


def test_is_cooldown_active_true_when_recent(now_utc):
    last_change = now_utc - dt.timedelta(days=5)
    assert is_cooldown_active(last_change, now_utc) is True


def test_is_cooldown_active_false_after_cooldown_period(now_utc):
    last_change = now_utc - dt.timedelta(days=COOLDOWN_DAYS + 1)
    assert is_cooldown_active(last_change, now_utc) is False


def test_is_cooldown_active_false_when_never_changed(now_utc):
    assert is_cooldown_active(None, now_utc) is False


def test_is_cooldown_active_boundary_exactly_14_days(now_utc):
    last_change = now_utc - dt.timedelta(days=COOLDOWN_DAYS)
    # exactement 14 jours : plus dans le cooldown (strictement inferieur)
    assert is_cooldown_active(last_change, now_utc) is False


@pytest.mark.parametrize("count,expected", [(0, False), (2, False), (3, True), (4, True)])
def test_weekly_budget_exceeded(count, expected):
    assert weekly_budget_exceeded(count, MAX_CHANGES_PER_WEEK) is expected


def test_validate_field_change_accepts_title_and_price():
    validate_field_change("title")
    validate_field_change("price")


def test_validate_field_change_rejects_anything_else():
    with pytest.raises(InvalidFieldChange):
        validate_field_change("description")


def test_proposal_check_raises_cooldown_active(now_utc):
    check = ProposalCheck(
        listing_id=1,
        field_changed="title",
        now=now_utc,
        last_change_at=now_utc - dt.timedelta(days=3),
        changes_in_last_7_days=0,
    )
    with pytest.raises(CooldownActive):
        check.validate()


def test_proposal_check_raises_weekly_budget_exceeded(now_utc):
    check = ProposalCheck(
        listing_id=1,
        field_changed="price",
        now=now_utc,
        last_change_at=None,
        changes_in_last_7_days=3,
    )
    with pytest.raises(WeeklyBudgetExceeded):
        check.validate()


def test_proposal_check_passes_when_no_violation(now_utc):
    check = ProposalCheck(
        listing_id=1,
        field_changed="title",
        now=now_utc,
        last_change_at=now_utc - dt.timedelta(days=20),
        changes_in_last_7_days=1,
    )
    check.validate()  # ne doit pas lever


def test_get_last_change_at_returns_most_recent(db_session, now_utc):
    listing = Listing(ebay_item_id="111", title="t")
    db_session.add(listing)
    db_session.flush()

    older = ChangeLog(
        listing_id=listing.id,
        changed_at=now_utc - dt.timedelta(days=30),
        field_changed="title",
        old_value="a",
        new_value="b",
        origin="manual",
    )
    newer = ChangeLog(
        listing_id=listing.id,
        changed_at=now_utc - dt.timedelta(days=2),
        field_changed="price",
        old_value="10",
        new_value="12",
        origin="manual",
    )
    db_session.add_all([older, newer])
    db_session.commit()

    result = get_last_change_at(db_session, listing.id)
    assert result == newer.changed_at


def test_count_changes_in_last_7_days_excludes_older_entries(db_session, now_utc):
    listing = Listing(ebay_item_id="222", title="t")
    db_session.add(listing)
    db_session.flush()

    within_window = ChangeLog(
        listing_id=listing.id,
        changed_at=now_utc - dt.timedelta(days=3),
        field_changed="title",
        old_value="a",
        new_value="b",
        origin="manual",
    )
    outside_window = ChangeLog(
        listing_id=listing.id,
        changed_at=now_utc - dt.timedelta(days=10),
        field_changed="title",
        old_value="a",
        new_value="b",
        origin="manual",
    )
    db_session.add_all([within_window, outside_window])
    db_session.commit()

    assert count_changes_in_last_7_days(db_session, now_utc) == 1
