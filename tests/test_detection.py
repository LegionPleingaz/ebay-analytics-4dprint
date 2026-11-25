import dataclasses
import datetime as dt

import pytest

from app.business.detection import Candidate, Kind, Metrics, Skip, Thresholds, evaluate
from app.db.models import CollectionRun, Listing, ListingContentSnapshot, ListingSnapshot
from app.reports.monthly import NoData, build_report, generate

NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.timezone.utc)
OLD = NOW - dt.timedelta(days=100)


def candidate(**changes) -> Candidate:
    base = Candidate(
        item_id="1", title="Piece", start_time=OLD, quantity=5, specifics_count=3,
        metrics=Metrics(impressions=300, views=20, click_through_rate=0.03, transactions=2),
        last_change_at=None,
    )
    return dataclasses.replace(base, **changes)


def run_rules(c):
    result = evaluate(c, Thresholds(), data_at=NOW, now=NOW)
    return result if isinstance(result, Skip) else [f.kind for f in result]


@pytest.mark.parametrize("impressions,views,ctr,sales,expected", [
    (300, 20, 0.03, 2, []),
    (50, 2, 0.04, 0, [Kind.LOW_VISIBILITY]),
    (51, 2, 0.04, 0, []),
    (500, 3, 0.0, 1, [Kind.LOW_CTR]),
    (499, 3, 0.0, 1, []),       # base insuffisante pour juger le CTR
    (900, 9, 0.01, 1, []),      # 1 % n'est pas "< 1 %"
    (300, 51, 0.04, 0, [Kind.NO_SALE]),
    (300, 50, 0.04, 0, []),     # il faut PLUS de 50 vues
    (600, 80, 0.0, 0, [Kind.NO_SALE, Kind.LOW_CTR]),
])
def test_thresholds(impressions, views, ctr, sales, expected):
    assert run_rules(candidate(metrics=Metrics(impressions, views, ctr, sales))) == expected


@pytest.mark.parametrize("changes,expected", [
    ({"quantity": 0}, Skip.OUT_OF_STOCK),
    ({"last_change_at": NOW - dt.timedelta(days=13)}, Skip.COOLDOWN),
    ({"start_time": NOW - dt.timedelta(days=27)}, Skip.TOO_RECENT),
    ({"metrics": None}, Skip.NO_DATA),
    ({"metrics": Metrics(None, None, None, None)}, Skip.NO_DATA),
])
def test_insufficient_or_blocked_is_not_evaluated(changes, expected):
    assert run_rules(candidate(**changes)) == expected


@pytest.fixture()
def report_db(db_session):
    return db_session


def add_run(db, run_id, at):
    db.add(CollectionRun(id=run_id, period_start=at.date(), period_end=at.date(),
                         status="partial", started_at=at))


def add_listing(db, listing_id, sku, title, run_id, at, *, window="28d", views=80):
    if db.get(Listing, listing_id) is None:
        db.add(Listing(id=listing_id, ebay_item_id=str(1000 + listing_id), title=title,
                       sku=sku, ebay_start_time=OLD))
    db.add(ListingContentSnapshot(listing_id=listing_id, run_id=run_id, collected_at=at,
                                  title=title, item_specifics={}, price_value=10, quantity=3))
    db.add(ListingSnapshot(listing_id=listing_id, run_id=run_id, window=window,
                           impressions_total=300, views_total=views,
                           click_through_rate=0.03, transactions=0))


def test_report_keeps_only_pro_listings_seen_by_latest_run(report_db, settings):
    previous = NOW - dt.timedelta(days=7)
    add_run(report_db, 1, previous)
    add_run(report_db, 2, NOW)
    add_listing(report_db, 1, "4DP-A", "Vue", 2, NOW)
    add_listing(report_db, 2, None, "Livre", 2, NOW)
    add_listing(report_db, 3, "4DP-B", "Terminee", 1, previous)
    add_listing(report_db, 4, "4DP-C", "Trafic 7j seulement", 2, NOW, window="7d")
    report_db.commit()

    report = build_report(report_db, Thresholds(), NOW)

    assert report.pro_count == 2
    assert [f.candidate.title for f in report.findings] == ["Vue"]
    # la fenetre 7 jours n'est jamais utilisee
    assert [c.title for c in report.skipped[Skip.NO_DATA]] == ["Trafic 7j seulement"]
    text = generate(report_db, settings, NOW)
    assert "https://www.ebay.fr/itm/1001" in text
    assert "Livre" not in text


def test_title_changed_on_ebay_triggers_cooldown(report_db):
    previous = NOW - dt.timedelta(days=7)
    add_run(report_db, 1, previous)
    add_run(report_db, 2, NOW)
    add_listing(report_db, 1, "4DP-A", "Ancien titre", 1, previous)
    add_listing(report_db, 1, "4DP-A", "Nouveau titre", 2, NOW)
    report_db.commit()

    report = build_report(report_db, Thresholds(), NOW)

    assert report.findings == []
    assert list(report.skipped) == [Skip.COOLDOWN]


def test_report_without_finished_run_raises(report_db):
    with pytest.raises(NoData):
        build_report(report_db, Thresholds(), NOW)


QUIET = Metrics(impressions=200, views=10, click_through_rate=0.02, transactions=1)
LONG_BAD = Metrics(impressions=600, views=60, click_through_rate=0.0, transactions=0)


def findings(**changes):
    return evaluate(candidate(metrics=QUIET, **changes), Thresholds(), data_at=NOW, now=NOW)


def test_ctr_and_no_sale_use_90_days():
    result = findings(metrics_90d=LONG_BAD)
    assert [(f.kind, f.window_days) for f in result] == [(Kind.NO_SALE, 90), (Kind.LOW_CTR, 90)]


def test_low_visibility_stays_on_28_days():
    few = Metrics(impressions=10, views=0, click_through_rate=0.0, transactions=0)
    result = evaluate(candidate(metrics=few, metrics_90d=LONG_BAD), Thresholds(), data_at=NOW, now=NOW)
    visibility = [f for f in result if f.kind is Kind.LOW_VISIBILITY]
    assert [(f.window_days, f.metrics) for f in visibility] == [(28, few)]


@pytest.mark.parametrize("days_ago,mixes", [(20, True), (40, False)])
def test_recent_change_falls_back_to_28_days(days_ago, mixes):
    changed = NOW - dt.timedelta(days=days_ago)
    assert findings(metrics_90d=LONG_BAD, last_change_at=changed) == []
    bad_28 = candidate(metrics=LONG_BAD, metrics_90d=QUIET, last_change_at=changed)
    result = evaluate(bad_28, Thresholds(), data_at=NOW, now=NOW)
    assert [(f.window_days, f.mixes_versions) for f in result] == [(28, mixes), (28, mixes)]


def test_change_older_than_90_days_uses_long_window():
    result = findings(metrics_90d=LONG_BAD, last_change_at=NOW - dt.timedelta(days=91))
    assert {f.window_days for f in result} == {90}


def test_report_reads_90_day_snapshot_and_warns_when_absent(report_db, settings):
    add_run(report_db, 1, NOW)
    add_listing(report_db, 1, "4DP-A", "Piece", 1, NOW, views=10)
    report_db.commit()
    assert "pas de trafic 90 jours" in generate(report_db, settings, NOW)

    report_db.add(ListingSnapshot(listing_id=1, run_id=1, window="90d", impressions_total=900,
                                  views_total=70, click_through_rate=0.02, transactions=0))
    report_db.commit()
    text = generate(report_db, settings, NOW)
    assert "sur 90 jours : impressions 900" in text
    assert "pas de trafic 90 jours" not in text
