"""Single source of truth for live market prices and bubble calculations."""

from __future__ import annotations

import math
import os
import threading
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

import pytz
import requests

TEHRAN = pytz.timezone("Asia/Tehran")

GOLD_URL = os.getenv("NERKH_GOLD_URL", "https://api.nerkh.io/v1/prices/json/gold")
NERKH_CURRENCY_URL = os.getenv("NERKH_CURRENCY_URL", "https://api.nerkh.io/v1/prices/json/currency")
NERKH_CRYPTO_URL = os.getenv("NERKH_CRYPTO_URL", "https://api.nerkh.io/v1/prices/json/crypto")
NAVASAN_URL = os.getenv("NAVASAN_URL", "https://api.navasan.tech/latest/")
DEFAULT_NERKH_TOKEN = ""

METADATA = {
    "SEKE_EMAMI": {"weight": 8.133, "purity": 900},
    "SEKE_BAHAR": {"weight": 8.133, "purity": 900},
    "SEKE_NIM": {"weight": 4.066, "purity": 900},
    "SEKE_ROB": {"weight": 2.033, "purity": 900},
    "SEKE_1G": {"weight": 1.010, "purity": 900},
    "SEKE_PRS100": {"weight": 0.100, "purity": 750},
    "SEKE_PRS200": {"weight": 0.200, "purity": 750},
    "SEKE_PRS400": {"weight": 0.400, "purity": 750},
    "SEKE_PRS500": {"weight": 0.500, "purity": 750},
    "SEKE_PRS700": {"weight": 0.700, "purity": 750},
}

PERSIAN_NAMES = {
    "OUNCE": "اونس جهانی",
    "MAZANEH": "مظنه",
    "GOLD24K": "طلای ۲۴ عیار",
    "USD": "دلار آمریکا",
    "EUR": "یورو",
    "AED": "درهم امارات",
    "GBP": "پوند انگلیس",
    "TRY": "لیر ترکیه",
    "BTC": "بیت‌کوین",
    "ETH": "اتریوم",
    "USDT": "تتر",
    "XRP": "ریپل",
    "GOLD18K": "طلای ۱۸ عیار",
    "SEKE_EMAMI": "سکه امامی",
    "SEKE_BAHAR": "سکه بهار آزادی",
    "SEKE_NIM": "نیم سکه",
    "SEKE_ROB": "ربع سکه",
    "SEKE_1G": "سکه یک گرمی",
    "SEKE_PRS100": "پارسیان ۱۰۰ سوتی",
    "SEKE_PRS200": "پارسیان ۲۰۰ سوتی",
    "SEKE_PRS400": "پارسیان ۴۰۰ سوتی",
    "SEKE_PRS500": "پارسیان ۵۰۰ سوتی",
    "SEKE_PRS700": "پارسیان ۷۰۰ سوتی",
}

GROUPS_CONFIG = [
    {"id": "global", "title": "بازار جهانی", "subtitle": "قیمت‌های بین‌المللی", "items": ["OUNCE", "MAZANEH", "GOLD24K"]},
    {"id": "gold18", "title": "طلای ۱۸ عیار", "subtitle": "قیمت هر گرم — با محاسبه حباب", "items": ["GOLD18K"]},
    {"id": "main_coins", "title": "سکه‌های اصلی", "subtitle": "سکه‌های بانک مرکزی", "items": ["SEKE_EMAMI", "SEKE_BAHAR", "SEKE_NIM", "SEKE_ROB"]},
    {
        "id": "parsian",
        "title": "پارسیان و گرمی",
        "subtitle": "سکه‌های گرمی و پارسیان",
        "items": ["SEKE_PRS100", "SEKE_PRS200", "SEKE_PRS400", "SEKE_PRS500", "SEKE_PRS700", "SEKE_1G"],
    },
    {"id": "crypto", "title": "رمزارزها", "subtitle": "قیمت لحظه‌ای رمزارزها", "items": ["BTC", "ETH", "USDT", "XRP"]},
    {"id": "currency", "title": "ارز", "subtitle": "نرخ ارز روز", "items": ["USD", "EUR", "AED", "GBP", "TRY"]},
]

BASE_ITEMS = {"OUNCE", "MAZANEH", "GOLD24K", "USD", "EUR", "AED", "GBP", "TRY", "BTC", "ETH", "USDT", "XRP"}


class MarketDataUnavailable(RuntimeError):
    """Raised when no valid live or cached snapshot is available."""


def _positive_number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def calculate_item(
    code: str,
    market_price: float,
    ounce: float,
    usd: float,
    gold18k: float,
) -> tuple[float | None, float | None, float | None]:
    """Return intrinsic value, absolute bubble and bubble percentage."""
    if code in BASE_ITEMS:
        return None, None, None
    if code == "GOLD18K":
        if ounce <= 0 or usd <= 0:
            return None, None, None
        real_value = (ounce * usd * 0.750) / 31.10343
    elif code in METADATA and gold18k > 0:
        meta = METADATA[code]
        real_value = meta["weight"] * (meta["purity"] / 750) * gold18k
    else:
        return None, None, None

    bubble_absolute = market_price - real_value
    bubble_percent = (bubble_absolute / real_value) * 100 if real_value > 0 else None
    return real_value, bubble_absolute, bubble_percent


class MarketService:
    """Fetch, normalize, calculate and cache the website's market snapshot."""

    def __init__(
        self,
        request_get: Callable[..., Any] = requests.get,
        clock: Callable[[], float] = time.time,
        cache_ttl_seconds: int | None = None,
        stale_after_seconds: int | None = None,
    ) -> None:
        self.request_get = request_get
        self.clock = clock
        self.cache_ttl = cache_ttl_seconds or int(os.getenv("MARKET_CACHE_TTL_SECONDS", "60"))
        self.stale_after = stale_after_seconds or int(os.getenv("MARKET_STALE_AFTER_SECONDS", "300"))
        self._cache: dict[str, Any] | None = None
        self._cache_epoch = 0.0
        self._lock = threading.Lock()

    def _fetch_nerkh(self, url: str) -> dict[str, Any]:
        token = os.getenv("NERKH_TOKEN", DEFAULT_NERKH_TOKEN).strip()
        if not token:
            raise MarketDataUnavailable("NERKH_TOKEN تنظیم نشده است.")
        response = None
        for attempt in range(3):
            response = self.request_get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=10,
            )
            if getattr(response, "status_code", 200) != 429 or attempt == 2:
                break
            retry_after = getattr(response, "headers", {}).get("Retry-After", "1")
            try:
                delay = max(1.0, min(float(retry_after), 5.0))
            except (TypeError, ValueError):
                delay = 1.0
            time.sleep(delay)
        assert response is not None
        response.raise_for_status()
        prices = response.json().get("data", {}).get("prices", {})
        if not isinstance(prices, dict):
            raise MarketDataUnavailable("ساختار پاسخ منبع طلا معتبر نیست.")
        return prices

    def _fetch_gold(self) -> dict[str, Any]:
        return self._fetch_nerkh(GOLD_URL)

    def _fetch_usd(self, nerkh_prices: dict[str, Any]) -> tuple[float, str]:
        api_key = os.getenv("NAVASAN_API_KEY", "").strip()
        if api_key:
            try:
                response = self.request_get(
                    NAVASAN_URL,
                    headers={"Accept": "application/json", "User-Agent": "Separ/1.0"},
                    params={"api_key": api_key},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                for key in ("usd_sell", "tehran_naghdi_sell", "harat_naghdi_sell"):
                    value = _positive_number(data.get(key, {}).get("value"))
                    if value is not None:
                        return value, "navasan.tech"
            except Exception:
                pass

        nerkh_usd = _positive_number(nerkh_prices.get("USD", {}).get("current"))
        if nerkh_usd is not None:
            return nerkh_usd, "nerkh.io"
        raise MarketDataUnavailable("قیمت معتبر دلار در منابع بازار یافت نشد.")

    @staticmethod
    def _normalize(gold_raw: dict[str, Any], usd_price: float) -> tuple[dict[str, float], dict[str, float | None]]:
        prices: dict[str, float] = {}
        changes: dict[str, float | None] = {}
        for code, info in gold_raw.items():
            if not isinstance(info, dict):
                continue
            current = _positive_number(info.get("current"))
            if current is None:
                continue
            prices[code] = current
            change = info.get("change_percent", info.get("change"))
            try:
                parsed_change = float(str(change).replace("%", "").replace(",", ""))
                changes[code] = parsed_change if math.isfinite(parsed_change) else None
            except (TypeError, ValueError):
                changes[code] = None
        prices["USD"] = usd_price
        changes["USD"] = None
        return prices, changes

    @staticmethod
    def _build_snapshot(
        prices: dict[str, float],
        changes: dict[str, float | None],
        now: datetime,
        usd_source: str,
    ) -> dict[str, Any]:
        ounce = prices.get("OUNCE", 0)
        usd = prices.get("USD", 0)
        gold18k = prices.get("GOLD18K", 0)
        groups: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []

        for group in GROUPS_CONFIG:
            group_items: list[dict[str, Any]] = []
            for code in group["items"]:
                market_price = prices.get(code, 0)
                real, bubble_abs, bubble_pct = calculate_item(code, market_price, ounce, usd, gold18k)
                item = {
                    "code": code,
                    "name": PERSIAN_NAMES.get(code, code),
                    "category": group["title"],
                    "market_price": market_price or None,
                    "price_change_percent": changes.get(code),
                    "real_value": round(real) if real is not None else None,
                    "bubble_absolute": round(bubble_abs) if bubble_abs is not None else None,
                    "bubble_percent": round(bubble_pct, 1) if bubble_pct is not None else None,
                    "source": usd_source if code == "USD" else "nerkh.io",
                }
                group_items.append(item)
                assets.append(item)
            groups.append({**group, "items": group_items})

        has_required = bool(ounce and usd and gold18k)
        has_prices = any(asset["market_price"] for asset in assets)
        return {
            "timestamp": now.isoformat(),
            "timestamp_display": now.strftime("%H:%M:%S"),
            "data_freshness": "fresh" if has_required else "partial",
            "data_available": has_prices,
            "sources": [
                {"id": "nerkh", "label": "Nerkh.io", "kind": "market"},
                *(
                    [{"id": "navasan", "label": "Navasan", "kind": "currency"}]
                    if usd_source == "navasan.tech"
                    else []
                ),
            ],
            "groups": groups,
            "assets": assets,
        }

    def get_snapshot(self, force_refresh: bool = False) -> dict[str, Any]:
        now_epoch = self.clock()
        with self._lock:
            if not force_refresh and self._cache and now_epoch - self._cache_epoch < self.cache_ttl:
                return deepcopy(self._cache)

            try:
                gold_raw = self._fetch_gold()
                for optional_url in (NERKH_CURRENCY_URL, NERKH_CRYPTO_URL):
                    try:
                        gold_raw.update(self._fetch_nerkh(optional_url))
                    except Exception:
                        pass
                usd_price, usd_source = self._fetch_usd(gold_raw)
                prices, changes = self._normalize(gold_raw, usd_price)
                snapshot = self._build_snapshot(prices, changes, datetime.now(TEHRAN), usd_source)
                if not snapshot["data_available"]:
                    raise MarketDataUnavailable("هیچ قیمت معتبری دریافت نشد.")
                self._cache = snapshot
                self._cache_epoch = now_epoch
                return deepcopy(snapshot)
            except Exception as exc:
                if self._cache:
                    age = max(0, int(now_epoch - self._cache_epoch))
                    cached = deepcopy(self._cache)
                    cached["data_freshness"] = "stale"
                    cached["stale_age_seconds"] = age
                    cached["warning"] = "دریافت داده تازه ناموفق بود؛ آخرین Snapshot معتبر نمایش داده می‌شود."
                    if age <= self.stale_after:
                        return cached
                if isinstance(exc, MarketDataUnavailable):
                    raise
                raise MarketDataUnavailable("دریافت داده بازار ناموفق بود.") from exc


market_service = MarketService()
