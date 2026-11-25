import httpx
import pytest

from app.jobs.collectors import traffic


class Run:
    started_at = None


class Db:
    def commit(self):
        pass


@pytest.mark.parametrize("fails", [False, True])
def test_90_day_failure_does_not_block_other_windows(monkeypatch, fails):
    seen = []

    def fake_window(db, run, token, listings, *, window, days, now):
        seen.append((window, days))
        if fails and window == "90d":
            raise httpx.ConnectError("refus")
        return None

    monkeypatch.setattr(traffic, "_collect_window", fake_window)
    warning = traffic.collect_traffic(Db(), Run(), "t", {})

    assert seen == [("7d", 7), ("28d", 28), ("90d", 89)]
    assert (warning is not None) is fails
