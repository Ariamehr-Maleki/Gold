"""
آریسوگلد — ارسال قیمت به تلگرام (اجرا از GitHub Actions)
"""
import os, re, time
import requests
import pytz
import jdatetime
from datetime import datetime

# ─── Config (از GitHub Secrets) ───────────────────────────────────────────
NERKH_TOKEN  = os.environ["NERKH_TOKEN"]
NAVASAN_KEY  = os.environ["NAVASAN_KEY"]
TG_TOKEN     = os.environ["TELEGRAM_TOKEN"]
TG_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

NERKH_HEADERS = {"Authorization": f"Bearer {NERKH_TOKEN}"}
GOLD_URL      = "https://api.nerkh.io/v1/prices/json/gold"
NERKH_USD_URL = "https://api.nerkh.io/v1/prices/json/currency/USD"
TG_API        = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
TEHRAN_TZ     = pytz.timezone("Asia/Tehran")

# ─── Metadata ─────────────────────────────────────────────────────────────
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

# ─── Persian helpers ───────────────────────────────────────────────────────
_PD = "۰۱۲۳۴۵۶۷۸۹"

def to_p(s):
    return "".join(_PD[int(c)] if c.isdigit() else c for c in str(s))

def fmt_toman(n):
    if not n: return "—"
    return to_p(f"{round(n):,}".replace(",", "،"))

def fmt_usd(n):
    if not n: return "—"
    return f"{round(n):,}"

def fmt_bubble(pct):
    if pct is None: return ""
    sign = "+" if pct >= 0 else ""
    return to_p(f"{sign}{pct:.1f}") + "٪"

def jalali_now():
    now = datetime.now(TEHRAN_TZ)
    j   = jdatetime.datetime.fromgregorian(datetime=now)
    return to_p(j.strftime("%Y/%m/%d")), to_p(now.strftime("%H:%M"))

# ─── Data fetching ─────────────────────────────────────────────────────────
def _fetch_gold():
    try:
        r = requests.get(GOLD_URL, headers=NERKH_HEADERS, timeout=10)
        r.raise_for_status()
        return r.json().get("data", {}).get("prices", {})
    except Exception as e:
        print(f"خطای دریافت طلا: {e}")
        return {}

def _nerkh_usd():
    r = requests.get(NERKH_USD_URL, headers=NERKH_HEADERS, timeout=10)
    r.raise_for_status()
    current = r.json().get("data", {}).get("prices", {}).get("USD", {}).get("current")
    if not current:
        raise ValueError("nerkh USD: no current value")
    return float(str(current).replace(",", "")) - 1200

def fetch_prices():
    raw = _fetch_gold()
    usd = 0.0
    try:
        usd = _nerkh_usd()
    except Exception as e:
        print(f"USD fetch error: {e}")

    data = {}
    for k, v in raw.items():
        if v and "current" in v:
            try: data[k] = float(str(v["current"]).replace(",", ""))
            except: pass
    data["USD"] = usd
    if data.get("GOLD18K"):
        data["GOLD18K"] += 100_000
    return data

# ─── Bubble calc ───────────────────────────────────────────────────────────
def calc_bubble(code, mp, ounce, usd, g18k):
    if code in ("OUNCE","MAZANEH","GOLD24K","USD") or not mp: return None, None
    if code == "GOLD18K":
        if ounce > 0 and usd > 0:
            rv  = (ounce * usd * 0.750) / 31.10343
            pct = ((mp - rv) / rv * 100) if rv > 0 else None
            return rv, pct
        return None, None
    if code in METADATA and g18k > 0:
        rv  = METADATA[code]["weight"] * (METADATA[code]["purity"] / 750) * g18k
        pct = ((mp - rv) / rv * 100) if rv > 0 else None
        return rv, pct
    return None, None

# ─── Message builders ──────────────────────────────────────────────────────
def build_hourly(prices):
    ounce  = prices.get("OUNCE", 0)
    usd    = prices.get("USD",   0)
    g18k   = prices.get("GOLD18K", 0)
    date_s, time_s = jalali_now()

    def coin_line(emoji, code, name):
        mp  = prices.get(code, 0)
        _, pct = calc_bubble(code, mp, ounce, usd, g18k)
        bbl = f"\n(حباب {fmt_bubble(pct)})" if pct is not None else ""
        return f"{emoji} {name}: {fmt_toman(mp)} تومان{bbl}"

    mp18  = prices.get("GOLD18K", 0)
    _, pct18 = calc_bubble("GOLD18K", mp18, ounce, usd, g18k)
    bbl18 = f"\n(حباب {fmt_bubble(pct18)})" if pct18 is not None else ""

    return "\n".join([
        f"🌐 اونس جهانی طلا: {fmt_usd(ounce)}$",
        f"💵 دلار آمریکا: {fmt_toman(usd)} تومان",
        "",
        f"🔻 طلای ۱۸ عیار: {fmt_toman(mp18)} تومان{bbl18}",
        "",
        coin_line("🔷", "SEKE_EMAMI", "سکه امامی"),
        coin_line("🔶", "SEKE_BAHAR", "سکه بهار آزادی"),
        coin_line("🔹", "SEKE_NIM",   "نیم سکه"),
        coin_line("🔸", "SEKE_ROB",   "ربع سکه"),
        "",
        f"ساعت: {time_s}",
        f"تاریخ: {date_s}",
        "🟢 آریسوگلد، خرید امن سکه و طلای آب‌شده",
    ])

def build_parsian(prices):
    ounce  = prices.get("OUNCE", 0)
    usd    = prices.get("USD",   0)
    g18k   = prices.get("GOLD18K", 0)
    date_s, time_s = jalali_now()

    items = [
        ("🟠", "SEKE_PRS100", "پارسیان ۱۰۰ سوتی"),
        ("🟠", "SEKE_PRS200", "پارسیان ۲۰۰ سوتی"),
        ("🟠", "SEKE_PRS400", "پارسیان ۴۰۰ سوتی"),
        ("🟠", "SEKE_PRS500", "پارسیان ۵۰۰ سوتی"),
        ("🟠", "SEKE_PRS700", "پارسیان ۷۰۰ سوتی"),
        ("🔹", "SEKE_1G",     "سکه یک گرمی"),
    ]
    lines = ["📊 قیمت سکه‌های پارسیان و گرمی", "━━━━━━━━━━━━━━━━━━━", ""]
    for emoji, code, name in items:
        mp      = prices.get(code, 0)
        rv, pct = calc_bubble(code, mp, ounce, usd, g18k)
        rv_txt  = f" | ارزش ذاتی: {fmt_toman(rv)}" if rv else ""
        bbl_txt = f" | حباب: {fmt_bubble(pct)}"    if pct is not None else ""
        lines.append(f"{emoji} {name}: {fmt_toman(mp)} تومان")
        if rv_txt or bbl_txt:
            lines.append(f"   └{rv_txt}{bbl_txt}")
        lines.append("")
    lines += [f"ساعت: {time_s}", f"تاریخ: {date_s}",
              "🟢 آریسوگلد، خرید امن سکه و طلای آب‌شده"]
    return "\n".join(lines)

# ─── Send ──────────────────────────────────────────────────────────────────
def send(text):
    r = requests.post(TG_API, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)
    r.raise_for_status()
    print(f"✅ Sent ({len(text)} chars)")

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(TEHRAN_TZ)
    h, m = now.hour, now.minute
    print(f"Tehran time: {h:02d}:{m:02d}")

    prices = fetch_prices()
    print(f"Prices fetched. GOLD18K={prices.get('GOLD18K')}, USD={prices.get('USD')}")

    # 12:00 or 18:30 → Parsian table (tight window to avoid catching 12:04 hourly)
    if (h == 12 and m <= 2) or (h == 18 and m >= 28):
        print("Sending Parsian table...")
        send(build_parsian(prices))
    else:
        print("Sending hourly prices...")
        send(build_hourly(prices))

if __name__ == "__main__":
    main()
