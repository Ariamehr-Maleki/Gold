from __future__ import annotations

import os

import pytest

from market_service import MarketDataUnavailable, MarketService, calculate_item


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("NERKH_TOKEN", "test-token")
    monkeypatch.setenv("NAVASAN_API_KEY", "test-key")


def fake_get(url, **kwargs):
    if "nerkh" in url:
        return Response(
            {
                "data": {
                    "prices": {
                        "OUNCE": {"current": "2,000"},
                        "GOLD18K": {"current": "5,000,000"},
                        "SEKE_EMAMI": {"current": "60,000,000"},
                        "SEKE_BAHAR": {"current": "55,000,000"},
                    }
                }
            }
        )
    return Response({"usd_sell": {"value": "100000"}})


def test_snapshot_uses_real_source_adapter_and_calculates_bubble():
    service = MarketService(request_get=fake_get, clock=lambda: 100)
    snapshot = service.get_snapshot()
    emami = next(item for item in snapshot["assets"] if item["code"] == "SEKE_EMAMI")
    assert snapshot["data_freshness"] == "fresh"
    assert emami["market_price"] == 60_000_000
    assert emami["real_value"] == round(8.133 * (900 / 750) * 5_000_000)
    assert isinstance(emami["bubble_percent"], float)


def test_stale_snapshot_is_explicit_when_refresh_fails():
    state = {"fails": False, "now": 100}

    def request(url, **kwargs):
        if state["fails"]:
            raise OSError("network down")
        return fake_get(url, **kwargs)

    service = MarketService(request_get=request, clock=lambda: state["now"], cache_ttl_seconds=1)
    initial = service.get_snapshot()
    state.update(fails=True, now=102)
    stale = service.get_snapshot()
    assert initial["data_freshness"] == "fresh"
    assert stale["data_freshness"] == "stale"
    assert stale["stale_age_seconds"] == 2


def test_missing_credentials_never_fall_back_to_mock(monkeypatch):
    monkeypatch.delenv("NERKH_TOKEN")
    monkeypatch.delenv("NAVASAN_API_KEY")
    service = MarketService(request_get=fake_get)
    with pytest.raises(MarketDataUnavailable):
        service.get_snapshot()


def test_calculation_rejects_missing_inputs():
    assert calculate_item("GOLD18K", 1, 0, 0, 0) == (None, None, None)
    assert calculate_item("UNKNOWN", 1, 1, 1, 1) == (None, None, None)


def test_production_modules_contain_no_embedded_provider_secret():
    root = os.path.dirname(os.path.dirname(__file__))
    for relative in ("market_service.py", "application.py", "separ_ai_service.py", "api/index.py", "backend/main.py"):
        text = open(os.path.join(root, relative), encoding="utf-8").read()
        assert "6cGxNnNX" not in text
        assert "freeNbwMN" not in text
