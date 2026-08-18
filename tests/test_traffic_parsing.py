import datetime as dt

import httpx
import respx

from app.ebay.analytics_client import get_traffic_report
from app.jobs.collectors.traffic import _extract_item_id, _extract_metrics


def test_extract_item_id_from_dimension_values():
    record = {"dimensionValues": [{"dimensionKey": "LISTING", "dimensionValue": "110123456789"}]}
    assert _extract_item_id(record) == "110123456789"


def test_extract_item_id_returns_none_when_missing():
    assert _extract_item_id({"dimensionValues": []}) is None


def test_extract_metrics_maps_known_keys_and_converts_to_float():
    record = {
        "metricValues": [
            {"metricKey": "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE", "value": "42"},
            {"metricKey": "CLICK_THROUGH_RATE", "value": "0.0231"},
            {"metricKey": "UNKNOWN_METRIC", "value": "999"},
        ]
    }
    metrics = _extract_metrics(record)
    assert metrics["impressions_search_results"] == 42.0
    assert metrics["click_through_rate"] == 0.0231
    assert "UNKNOWN_METRIC" not in metrics


def test_extract_metrics_handles_empty_value():
    record = {"metricValues": [{"metricKey": "TRANSACTION", "value": ""}]}
    assert _extract_metrics(record)["transactions"] is None


@respx.mock
def test_get_traffic_report_sends_iso_date_range_with_offset(settings):
    route = respx.get(
        "https://api.sandbox.ebay.com/sell/analytics/v1/traffic_report"
    ).mock(return_value=httpx.Response(200, json={"records": []}))

    start = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 8, 8, tzinfo=dt.timezone.utc)
    get_traffic_report("token-abc", start=start, end=end, settings=settings)

    assert route.called
    request = route.calls[0].request
    query = str(request.url)
    assert "date_range" in query
    assert "2026-08-01" in query
    assert "%2B00%3A00" in query or "+00:00" in query  # offset UTC encode
    assert "dimension=LISTING" in query
