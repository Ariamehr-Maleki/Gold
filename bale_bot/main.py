"""
آریسوگلد — ربات تلگرام (Bale)
ارسال قیمت‌های زنده طلا و سکه هر ساعت یکبار
ارسال جدول پارسیان هر روز ساعت ۱۲ ظهر
"""
import asyncio
import logging
import re
import time as _time
from datetime import datetime, time as dtime

import pytz
import requests
import jdatetime
from telegram import Bot
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

# ─── تنظیمات ─────────────────────────────────────────────────────────────
BOT_TOKEN  = "1229708366:QHZEJ5dYWGpl2X5lQt-awSXWOsAhUIgkqG8"
CHAT_ID    = 5315053603         # ← پس از اضافه کردن ربات به گروه، دستور /chatid را اجرا کن
BALE_BASE  = "https://tapi.bale.ai/bot"
BALE_FILE  = "https://tapi.bale.ai/file/bot"
TEHRAN_TZ  = pytz.timezone("Asia/Tehran")

# ─── لاگ ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── API credentials (same as backend) ───────────────────────────────────
NERKH_TOKEN    = "1S060h9Vp6L58-8IiINiFVNqHDyjLCT-1rW0zBZMsOU="
NERKH_HEADERS  = {"Authorization": f"Bearer {NERKH_TOKEN}"}
GOLD_URL       = "https://api.nerkh.io/v1/prices/json/gold"
NAVASAN_KEY    = "freeNbwMNzuAY2WxQKzdlxdpBOw6KH4j"
NAVASAN_URL    = "http://api.navasan.tech/latest/"
TGJU_USD_URL   = (
    "https://api.tgju.org/v1/market/indicator/summary-table-data/price_dollar_rl"
)

# ─── کش قیمت دلار (۵ دقیقه) ─────────────────────────────────────────────────
_USD_CACHE: dict = {"value": 0.0, "ts": 0.0}
_USD_TTL = 300

# ─── متادیتا سکه‌ها ──────────────────────────────────────────────────────
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

# ─── Persian helpers ──────────────────────────────────────────────────────
_PD = "۰۱۲۳۴۵۶۷۸۹"

def to_p(s: str) -> str:
    """Convert ASCII digits to Persian digits."""
    return "".join(_PD[int(c)] if c.isdigit() else c for c in str(s))

def fmt_toman(n: float) -> str:
    """Format as Persian-comma-separated Tomans."""
    if not n:
        return "—"
    return to_p(f"{round(n):,}".replace(",", "،"))

def fmt_usd(n: float) -> str:
    """Format as comma-separated USD."""
    if not n:
        return "—"
    return f"{round(n):,}"

def fmt_bubble(pct: float | None) -> str:
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    return to_p(f"{sign}{pct:.1f}") + "٪"

def jalali_now() -> tuple[str, str]:
    """Returns (date_str, time_str) in Persian."""
    now = datetime.now(TEHRAN_TZ)
    j   = jdatetime.datetime.fromgregorian(datetime=now)
    return (
        to_p(j.strftime("%Y/%m/%d")),
        to_p(now.strftime("%H:%M")),
    )

# ─── Data fetching ────────────────────────────────────────────────────────

def _fetch_gold() -> dict:
    try:
        r = requests.get(GOLD_URL, headers=NERKH_HEADERS, timeout=10)
        r.raise_for_status()
        return r.json().get("data", {}).get("prices", {})
    except Exception as e:
        log.error("خطای دریافت طلا: %s", e)
        return {}

def _tgju_usd() -> float:
    """دریافت نرخ دلار از TGJU — بدون محدودیت درخواست."""
    headers = {"User-Agent": "Mozilla/5.0 Chrome/120"}
    r = requests.get(TGJU_USD_URL, headers=headers, timeout=20)
    r.raise_for_status()
    rows = r.json().get("data", [])
    if not rows:
        raise ValueError("TGJU: no rows")
    rial = float(re.sub(r"[^0-9.]", "", str(rows[0][1])))
    return rial / 10


def _navasan_usd() -> float:
    """دریافت نرخ دلار از Navasan — فال‌بک."""
    headers = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept": "application/json"}
    r = requests.get(NAVASAN_URL, headers=headers,
                     params={"api_key": NAVASAN_KEY}, timeout=10)
    r.raise_for_status()
    d = r.json()
    for key in ("usd_sell", "tehran_naghdi_sell", "harat_naghdi_sell"):
        if key in d:
            return float(d[key]["value"])
    raise ValueError("Navasan: no USD key")


def _fetch_usd() -> float:
    """نرخ دلار به تومان — کش ۵ دقیقه + TGJU اول، Navasan فال‌بک."""
    now = _time.time()
    if _USD_CACHE["value"] and now - _USD_CACHE["ts"] < _USD_TTL:
        return _USD_CACHE["value"]

    result = 0.0
    for fn in (_tgju_usd, _navasan_usd):
        try:
            result = fn()
            if result > 0:
                break
        except Exception as e:
            log.warning("USD fetch fallback (%s): %s", fn.__name__, e)

    if result > 0:
        _USD_CACHE["value"] = result
        _USD_CACHE["ts"] = now
    return result

def fetch_prices() -> dict[str, float]:
    """Returns a flat dict of {code: price} — same logic as backend."""
    raw   = _fetch_gold()
    usd   = _fetch_usd()
    data  = {}
    for k, v in raw.items():
        if v and "current" in v:
            try:
                data[k] = float(str(v["current"]).replace(",", ""))
            except (ValueError, TypeError):
                pass
    data["USD"] = usd
    # افزودن ۱۰۰٬۰۰۰ تومان به قیمت طلای ۱۸ عیار
    if data.get("GOLD18K"):
        data["GOLD18K"] += 100_000
    return data

def calc_bubble(code: str, mp: float, ounce: float, usd: float, g18k: float
                ) -> tuple[float | None, float | None]:
    """Returns (real_value, bubble_pct) or (None, None)."""
    if code in ("OUNCE", "MAZANEH", "GOLD24K", "USD") or mp == 0:
        return None, None
    if code == "GOLD18K":
        if ounce > 0 and usd > 0:
            rv  = (ounce * usd * 0.750) / 31.10343
            pct = ((mp - rv) / rv) * 100 if rv > 0 else None
            return rv, pct
        return None, None
    if code in METADATA and g18k > 0:
        w  = METADATA[code]["weight"]
        pu = METADATA[code]["purity"]
        rv  = w * (pu / 750) * g18k
        pct = ((mp - rv) / rv) * 100 if rv > 0 else None
        return rv, pct
    return None, None

# ─── Message builders ─────────────────────────────────────────────────────

def build_hourly_message(prices: dict) -> str:
    ounce  = prices.get("OUNCE", 0)
    usd    = prices.get("USD", 0)
    g18k   = prices.get("GOLD18K", 0)
    date_s, time_s = jalali_now()

    def coin_line(emoji: str, code: str, name: str) -> str:
        mp  = prices.get(code, 0)
        _, pct = calc_bubble(code, mp, ounce, usd, g18k)
        bubble = f"\n({'حباب ' + fmt_bubble(pct) if pct is not None else ''})" if pct is not None else ""
        return f"{emoji} {name}: {fmt_toman(mp)} تومان{bubble}"

    lines = [
        f"🌐 اونس جهانی طلا: {fmt_usd(ounce)}$",
        f"💵 دلار آمریکا: {fmt_toman(usd)} تومان",
        "",
    ]

    # طلای ۱۸ عیار با حباب
    mp18   = prices.get("GOLD18K", 0)
    _, pct = calc_bubble("GOLD18K", mp18, ounce, usd, g18k)
    bubble = f"\n(حباب {fmt_bubble(pct)})" if pct is not None else ""
    lines.append(f"🔻 طلای ۱۸ عیار: {fmt_toman(mp18)} تومان{bubble}")
    lines.append("")

    lines.append(coin_line("🔷", "SEKE_EMAMI", "سکه امامی"))
    lines.append(coin_line("🔶", "SEKE_BAHAR", "سکه بهار آزادی"))
    lines.append(coin_line("🔹", "SEKE_NIM",   "نیم سکه"))
    lines.append(coin_line("🔸", "SEKE_ROB",   "ربع سکه"))
    lines.append("")
    lines.append(f"ساعت: {time_s}")
    lines.append(f"تاریخ: {date_s}")
    lines.append("🟢 آریسوگلد، خرید امن سکه و طلای آب‌شده")
    return "\n".join(lines)


def build_parsian_message(prices: dict) -> str:
    ounce  = prices.get("OUNCE", 0)
    usd    = prices.get("USD", 0)
    g18k   = prices.get("GOLD18K", 0)
    date_s, time_s = jalali_now()

    parsian_items = [
        ("🟠", "SEKE_PRS100", "پارسیان ۱۰۰ سوتی"),
        ("🟠", "SEKE_PRS200", "پارسیان ۲۰۰ سوتی"),
        ("🟠", "SEKE_PRS400", "پارسیان ۴۰۰ سوتی"),
        ("🟠", "SEKE_PRS500", "پارسیان ۵۰۰ سوتی"),
        ("🟠", "SEKE_PRS700", "پارسیان ۷۰۰ سوتی"),
        ("🔹", "SEKE_1G",     "سکه یک گرمی"),
    ]

    lines = [
        "📊 قیمت سکه‌های پارسیان و گرمی",
        "━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for emoji, code, name in parsian_items:
        mp      = prices.get(code, 0)
        rv, pct = calc_bubble(code, mp, ounce, usd, g18k)
        rv_txt  = f" | ارزش ذاتی: {fmt_toman(rv)}" if rv else ""
        bbl_txt = f" | حباب: {fmt_bubble(pct)}"   if pct is not None else ""
        lines.append(f"{emoji} {name}: {fmt_toman(mp)} تومان")
        if rv_txt or bbl_txt:
            lines.append(f"   └{rv_txt}{bbl_txt}")
        lines.append("")

    lines.append(f"ساعت: {time_s}")
    lines.append(f"تاریخ: {date_s}")
    lines.append("🟢 آریسوگلد، خرید امن سکه و طلای آب‌شده")
    return "\n".join(lines)

# ─── Job callbacks ────────────────────────────────────────────────────────

async def job_hourly(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not CHAT_ID:
        log.warning("CHAT_ID تنظیم نشده — پیام ارسال نشد.")
        return
    try:
        prices = await asyncio.to_thread(fetch_prices)
        text   = build_hourly_message(prices)
        await context.bot.send_message(chat_id=CHAT_ID, text=text)
        log.info("پیام ساعتی ارسال شد.")
    except Exception as e:
        log.error("خطا در ارسال پیام ساعتی: %s", e)


async def job_parsian(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not CHAT_ID:
        log.warning("CHAT_ID تنظیم نشده — پیام ارسال نشد.")
        return
    try:
        prices = await asyncio.to_thread(fetch_prices)
        text   = build_parsian_message(prices)
        await context.bot.send_message(chat_id=CHAT_ID, text=text)
        log.info("جدول پارسیان ارسال شد.")
    except Exception as e:
        log.error("خطا در ارسال جدول پارسیان: %s", e)

# ─── Commands ─────────────────────────────────────────────────────────────

async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat  = update.effective_chat
    lines = [
        "🍀 <b>آریسوگلد</b> — ربات قیمت طلا و سکه",
        "",
        f"🆔 شناسه این چت: <code>{chat.id}</code>",
        "",
        "برای فعال‌سازی ارسال خودکار، مقدار <code>CHAT_ID</code> را در فایل <code>bot/main.py</code> با این عدد جایگزین کن.",
    ]
    await update.message.reply_html("\n".join(lines))


async def cmd_chatid(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def cmd_now(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال دستی قیمت‌ها در هر زمان."""
    await update.message.reply_text("⏳ در حال دریافت قیمت‌ها...")
    try:
        prices = await asyncio.to_thread(fetch_prices)
        text   = build_hourly_message(prices)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")


async def cmd_parsian(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال دستی جدول پارسیان."""
    await update.message.reply_text("⏳ در حال دریافت قیمت‌ها...")
    try:
        prices = await asyncio.to_thread(fetch_prices)
        text   = build_parsian_message(prices)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

# ─── App factory ──────────────────────────────────────────────────────────

def make_app(first_hourly: int = 3600):
    """Build and configure the Application. first_hourly controls when the
    first hourly job fires (seconds). Pass 30 for standalone, 3600 for
    combined mode (startup message is sent manually instead)."""
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .base_url(BALE_BASE)
        .base_file_url(BALE_FILE)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("chatid",  cmd_chatid))
    app.add_handler(CommandHandler("now",     cmd_now))
    app.add_handler(CommandHandler("parsian", cmd_parsian))

    jq = app.job_queue
    jq.run_repeating(job_hourly, interval=3600, first=first_hourly)
    jq.run_daily(job_parsian, time=dtime(hour=12, minute=0, tzinfo=TEHRAN_TZ))

    return app

# ─── Main (standalone) ────────────────────────────────────────────────────

def main() -> None:
    app = make_app(first_hourly=30)
    log.info("ربات آریسوگلد در حال اجرا است...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
