import datetime as dt

import httpx
import pytest
import respx

from app.ebay.analytics_client import get_traffic_report
from app.jobs.collectors.traffic import _extract_item_id, _extract_metrics


def test_extract_item_id_from_dimension_values():
    record = {"dimensionValues": [{"value": "110123456789", "applicable": True}]}
    assert _extract_item_id(record) == "110123456789"


def test_extract_item_id_returns_none_when_missing():
    assert _extract_item_id({"dimensionValues": []}) is None


def test_extract_metrics_follows_header_order():
    keys = ["CLICK_THROUGH_RATE", "UNKNOWN_METRIC", "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE"]
    record = {"metricValues": [{"value": 0.0231}, {"value": 999}, {"value": 42}]}
    assert _extract_metrics(record, keys) == {
        "click_through_rate": 0.0231,
        "impressions_search_results": 42.0,
    }


def test_extract_metrics_not_applicable_is_none():
    record = {"metricValues": [{"value": 0, "applicable": False}]}
    assert _extract_metrics(record, ["TRANSACTION"]) == {"transactions": None}


def test_extract_metrics_rejects_misaligned_report():
    with pytest.raises(ValueError):
        _extract_metrics({"metricValues": []}, ["TRANSACTION"])


@respx.mock
def test_get_traffic_report_sends_iso_date_range_with_offset(settings):
    route = respx.get(
        "https://api.sandbox.ebay.com/sell/analytics/v1/traffic_report"
    ).mock(return_value=httpx.Response(200, json={"records": []}))

    start = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 8, 8, tzinfo=dt.timezone.utc)
    get_traffic_report("token-abc", start=start, end=end, settings=settings)

    assert route.called
    query = str(route.calls[0].request.url)
    assert "date_range" in query
    assert "marketplace_ids" in query
    assert "2026-08-01" in query
    assert "%2B00%3A00" in query or "+00:00" in query  # offset UTC encode
    assert "dimension=LISTING" in query
