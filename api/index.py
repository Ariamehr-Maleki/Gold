from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import pytz

app = FastAPI(title="داشبورد قیمت طلا و سکه")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API credentials ────────────────────────────────────────────────────────
TOKEN = "JP5zKH45Y9eRnNMrgEwG4KI3LRqax1KciYgdvejyJ3c="
GOLD_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
GOLD_URL = "https://api.nerkh.io/v1/prices/json/gold"

NAVASAN_API_KEY = "freeNbwMNzuAY2WxQKzdlxdpBOw6KH4j"
NAVASAN_URL = "http://api.navasan.tech/latest/"

# ─── Coin metadata ──────────────────────────────────────────────────────────
METADATA = {
    "SEKE_EMAMI":  {"weight": 8.133, "purity": 900},
    "SEKE_BAHAR":  {"weight": 8.133, "purity": 900},
    "SEKE_NIM":    {"weight": 4.066, "purity": 900},
    "SEKE_ROB":    {"weight": 2.033, "purity": 900},
    "SEKE_1G":     {"weight": 1.010, "purity": 900},
    "SEKE_PRS100": {"weight": 0.100, "purity": 750},
    "SEKE_PRS200": {"weight": 0.200, "purity": 750},
    "SEKE_PRS400": {"weight": 0.400, "purity": 750},
    "SEKE_PRS500": {"weight": 0.500, "purity": 750},
    "SEKE_PRS700": {"weight": 0.700, "purity": 750},
}

PERSIAN_NAMES = {
    "OUNCE":       "اونس جهانی",
    "MAZANEH":     "مظنه",
    "GOLD24K":     "طلای ۲۴ عیار",
    "USD":         "دلار آمریکا",
    "GOLD18K":     "طلای ۱۸ عیار",
    "SEKE_EMAMI":  "سکه امامی",
    "SEKE_BAHAR":  "سکه بهار آزادی",
    "SEKE_NIM":    "نیم سکه",
    "SEKE_ROB":    "ربع سکه",
    "SEKE_1G":     "سکه یک گرمی",
    "SEKE_PRS100": "پارسیان ۱۰۰ سوتی",
    "SEKE_PRS200": "پارسیان ۲۰۰ سوتی",
    "SEKE_PRS400": "پارسیان ۴۰۰ سوتی",
    "SEKE_PRS500": "پارسیان ۵۰۰ سوتی",
    "SEKE_PRS700": "پارسیان ۷۰۰ سوتی",
}

GROUPS_CONFIG = [
    {
        "id": "global",
        "title": "بازار جهانی",
        "subtitle": "قیمت‌های بین‌المللی",
        "items": ["OUNCE", "MAZANEH", "GOLD24K"],
    },
    {
        "id": "currency",
        "title": "ارز",
        "subtitle": "نرخ ارز روز",
        "items": ["USD"],
    },
    {
        "id": "gold18",
        "title": "طلای ۱۸ عیار",
        "subtitle": "قیمت هر گرم — با محاسبه حباب",
        "items": ["GOLD18K"],
    },
    {
        "id": "main_coins",
        "title": "سکه‌های اصلی",
        "subtitle": "سکه‌های بانک مرکزی",
        "items": ["SEKE_EMAMI", "SEKE_BAHAR", "SEKE_NIM", "SEKE_ROB"],
    },
    {
        "id": "parsian",
        "title": "پارسیان و گرمی",
        "subtitle": "سکه‌های گرمی و پارسیان",
        "items": ["SEKE_PRS100", "SEKE_PRS200", "SEKE_PRS400", "SEKE_PRS500", "SEKE_PRS700", "SEKE_1G"],
    },
]

BASE_ITEMS = {"OUNCE", "MAZANEH", "GOLD24K", "USD"}


# ─── Data fetchers ───────────────────────────────────────────────────────────

def fetch_gold_data() -> dict:
    try:
        response = requests.get(GOLD_URL, headers=GOLD_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json().get("data", {}).get("prices", {})
    except requests.exceptions.RequestException as e:
        print(f"Error fetching gold data: {e}")
        return {}


def fetch_usd_data() -> float:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    params = {"api_key": NAVASAN_API_KEY}
    try:
        response = requests.get(NAVASAN_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        for key in ("usd_sell", "tehran_naghdi_sell", "harat_naghdi_sell"):
            if key in data:
                return float(data[key]["value"])
        return 0
    except requests.exceptions.RequestException as e:
        print(f"Error fetching USD data: {e}")
        return 0


# ─── Price calculation ───────────────────────────────────────────────────────

def calculate_item(code: str, market_price: float, ounce: float, usd: float, gold18k: float):
    if code in BASE_ITEMS:
        return None, None, None

    if code == "GOLD18K":
        if ounce > 0 and usd > 0:
            real_value = (ounce * usd * 1.000 * 0.750) / 31.10343
            bubble_abs = market_price - real_value
            bubble_pct = (bubble_abs / real_value) * 100 if real_value > 0 else None
            return real_value, bubble_abs, bubble_pct
        return None, None, None

    if code in METADATA and gold18k > 0:
        weight = METADATA[code]["weight"]
        purity = METADATA[code]["purity"]
        real_value = weight * (purity / 750) * gold18k
        bubble_abs = market_price - real_value
        bubble_pct = (bubble_abs / real_value) * 100 if real_value > 0 else None
        return real_value, bubble_abs, bubble_pct

    return None, None, None


# ─── API endpoint ─────────────────────────────────────────────────────────────

@app.get("/api/prices")
def get_prices():
    gold_raw = fetch_gold_data()
    usd_price = fetch_usd_data()

    live_data: dict = {}
    for key, info in gold_raw.items():
        if info and "current" in info:
            try:
                live_data[key] = float(str(info["current"]).replace(",", ""))
            except (ValueError, TypeError):
                pass

    live_data["USD"] = usd_price

    ounce = live_data.get("OUNCE", 0)
    usd = live_data.get("USD", 0)
    gold18k = live_data.get("GOLD18K", 0)

    tehran = pytz.timezone("Asia/Tehran")
    now = datetime.now(tehran)

    groups_out = []
    for grp in GROUPS_CONFIG:
        items_out = []
        for code in grp["items"]:
            mp = live_data.get(code, 0)
            rv, ba, bp = calculate_item(code, mp, ounce, usd, gold18k)
            items_out.append({
                "code": code,
                "name": PERSIAN_NAMES.get(code, code),
                "market_price": mp or None,
                "real_value": round(rv) if rv is not None else None,
                "bubble_absolute": round(ba) if ba is not None else None,
                "bubble_percent": round(bp, 1) if bp is not None else None,
            })
        groups_out.append({
            "id": grp["id"],
            "title": grp["title"],
            "subtitle": grp["subtitle"],
            "items": items_out,
        })

    return {
        "timestamp": now.isoformat(),
        "timestamp_display": now.strftime("%H:%M:%S"),
        "groups": groups_out,
    }
