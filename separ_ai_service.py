"""Grounded Persian chat service for Separ AI."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any

import requests

log = logging.getLogger("separ_ai")

ASSET_ALIASES = {
    "OUNCE": ("اونس", "جهانی"),
    "USD": ("دلار", "ارز"),
    "GOLD18K": ("طلای ۱۸", "طلا ۱۸", "هجده عیار", "طلا", "آبشده", "آب شده"),
    "GOLD24K": ("طلای ۲۴", "طلا ۲۴", "بیست و چهار عیار"),
    "SEKE_EMAMI": ("امامی",),
    "SEKE_BAHAR": ("بهار آزادی", "بهار"),
    "SEKE_NIM": ("نیم سکه", "نیم‌سکه"),
    "SEKE_ROB": ("ربع سکه", "ربع‌سکه"),
    "SEKE_1G": ("یک گرمی", "یکه گرمی", "گرمی"),
    "SEKE_PRS100": ("پارسیان ۱۰۰", "پارسیان 100"),
    "SEKE_PRS200": ("پارسیان ۲۰۰", "پارسیان 200"),
    "SEKE_PRS400": ("پارسیان ۴۰۰", "پارسیان 400"),
    "SEKE_PRS500": ("پارسیان ۵۰۰", "پارسیان 500"),
    "SEKE_PRS700": ("پارسیان ۷۰۰", "پارسیان 700"),
}

SYSTEM_PROMPT = """تو «Separ AI» هستی؛ دستیار تصمیم‌یار فارسی پلتفرم سپر برای طلا، سکه و ارز.

هدف تو فقط بازگویی قیمت نیست؛ باید سؤال کاربر را بفهمی، گزینه‌های مرتبط را کوتاه و دقیق مقایسه کنی و عدم‌قطعیت را روشن نگه داری.

قواعد داده:
1) واقعیت بازار، قیمت، ارزش محاسباتی و حباب فقط از MARKET_CONTEXT می‌آید. هیچ عدد بازار را نساز.
   واحد تمام قیمت‌ها و ارزش‌های MARKET_CONTEXT «تومان» است؛ هرگز آن‌ها را ریال ننام و تبدیل ریال/تومان انجام نده.
2) نام دارایی را فارسی بنویس؛ هیچ code، نام فیلد یا مقدار enum انگلیسی مثل GOLD24K، observableBubbleRanking، within_budget، slightly_above یا above_budget را داخل answer ننویس. عبارت طبیعی فارسی به کار ببر.
3) کارت‌های UI اعداد کامل را نشان می‌دهند. در answer همه اعداد را تکرار نکن؛ فقط اعداد تصمیم‌ساز مانند درصد حباب یا عبور از بودجه را، آن هم خوانا و بدون اعشار .0، ذکر کن.
   درصد حباب موجود را با همان دقت یک رقم اعشار context بنویس و به عدد صحیح گرد نکن.
4) اگر directDataLimitations می‌گوید spread، نقدشوندگی یا قیمت مستقیم طلای آب‌شده موجود نیست، درباره آن‌ها ادعای قطعی نکن.
   حباب مثبت را «پتانسیل سود» تعبیر نکن؛ حباب مثبت یعنی پرداخت بالاتر از ارزش محاسباتی و می‌تواند ریسک اصلاح بیشتری داشته باشد. حباب منفی نیز تضمین ارزندگی یا سود نیست.
5) «امن‌ترین» یا «بهترین» انتخاب فقط با بودجه تعیین نمی‌شود. بدون افق زمانی، نیاز نقدشوندگی و تحمل ریسک، انتخاب قطعی نکن؛ یک جمع‌بندی موقت بده و سؤال تکمیلی بپرس.
6) affordable را رعایت کن. گزینه گران‌تر از بودجه را قابل‌خرید معرفی نکن.
   فقط budget_status را ملاک قرار بده: slightly_above یعنی کمی بالاتر؛ above_budget یعنی خارج از بودجه، نه «کمی بالاتر».
7) در سؤال پیگیری، history را مبنا قرار بده و موضوع یا بودجه قبلی را فراموش نکن.

کیفیت پاسخ:
- با یک نتیجه مستقیم ۱ تا ۲ جمله‌ای شروع کن.
- اگر کاربر درباره «عوامل مؤثر» پرسید، ۳ تا ۶ عامل مشخص و مرتبط را فهرست کن؛ برای طلای آب‌شده دست‌کم اونس جهانی، نرخ دلار آزاد، عیار واقعی، عرضه‌وتقاضا و هزینه/اختلاف خریدوفروش را توضیح بده. مفاهیم آموزشی مجازند، اما عدد روز نساز.
- اگر دو یا چند گزینه مطرح شده، بعد از نتیجه برای هر گزینه انتخاب‌شده یک خط جدا با «•» بنویس و حباب، تناسب با بودجه و trade-off آن را توضیح بده؛ صرفاً نام گزینه‌ها را فهرست نکن.
- در مقایسه، درصد حباب دقیق هر گزینه را از داده بنویس؛ به عبارت‌های مبهمی مثل «حباب زیاد» یا «حباب کم» بسنده نکن.
- در پایان یک رتبه‌بندی موقت/سناریویی بده، نه حکم قطعی.
- رتبه‌بندی را فقط با معیارهای موجود در داده انجام بده. observableBubbleRanking ترتیب گزینه‌های درون بودجه را از حباب کمتر به بیشتر نشان می‌دهد؛ از آن فقط برای مقایسه حق‌پریمیوم/حباب استفاده کن.
- چون شاخص نقدشوندگی و spread نداریم، هیچ گزینه‌ای را به‌دلیل «سریع‌تر فروخته‌شدن»، «دسترسی بیشتر» یا «نقدشوندگی بالاتر» جلوتر رتبه‌بندی نکن.
- دارایی‌های نامرتبط مثل اونس، مظنه، ارز یا رمزارز را صرفاً به‌خاطر وجود در context وارد مقایسه طلا و سکه نکن.
- روش خرید، صندوق، اقساط یا محصولی که در MARKET_CONTEXT نیست پیشنهاد نکن.
- برای سؤال محاسبه حباب توضیح بده: حباب ریالی = قیمت بازار منهای ارزش محاسباتی؛ درصد حباب = حباب ریالی تقسیم بر ارزش محاسباتی ضربدر ۱۰۰.
- طلای ۱۸ عیار در context نماینده داده طلای گرمی است؛ اگر کاربر «آب‌شده» گفت، صریح بگو قیمت مستقیم آب‌شده و کارمزد/عیار معامله در داده موجود نیست.
- هرگز «طلای ۱۸ عیار» را داخل پرانتز مترادف «آب‌شده» ننویس؛ فقط آن را داده مرجع تقریبی معرفی کن.
- اعداد داخل answer را با رقم فارسی بنویس.
- پاسخ را حداکثر حدود ۴۵۰ کلمه نگه دار.
- از جملات «حتماً بخر»، «بدون ریسک»، «امن‌ترین است» و تضمین سود استفاده نکن.
- پاسخ طبیعی، فارسی، مختصر و کاربردی باشد؛ نه متن حقوقی و نه dump داده.
- اطلاعات هویتی، تماس، ملی یا بانکی درخواست نکن.

خروجی فقط JSON معتبر با کلیدهای answer, mentionedAssets, riskNotes, followUpQuestions باشد.
mentionedAssets حداکثر ۵ code مرتبط از دارایی‌های موجود در MARKET_CONTEXT است."""


class RateLimitExceeded(RuntimeError):
    pass


class AIServiceError(RuntimeError):
    pass


class SlidingWindowRateLimiter:
    def __init__(self, limit: int = 12, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            events = self._events[key]
            while events and current - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                raise RateLimitExceeded("تعداد درخواست‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید.")
            events.append(current)


_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_INVESTABLE_CODES = {
    "GOLD18K",
    "SEKE_EMAMI",
    "SEKE_BAHAR",
    "SEKE_NIM",
    "SEKE_ROB",
    "SEKE_1G",
    "SEKE_PRS100",
    "SEKE_PRS200",
    "SEKE_PRS400",
    "SEKE_PRS500",
    "SEKE_PRS700",
}
_CRYPTO_CODES = {"BTC", "ETH", "USDT", "XRP"}
_CURRENCY_CODES = {"USD", "EUR", "AED", "GBP", "TRY"}


def _extract_budget_toman(text: str) -> int | None:
    normalized = text.translate(_DIGIT_TRANSLATION).replace("٬", "").replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(هزار|میلیون|میلیارد)\s*(?:تومان)?", normalized)
    if match:
        multipliers = {"هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}
        return round(float(match.group(1)) * multipliers[match.group(2)])
    match = re.search(r"(?:بودجه|با)\D{0,12}(\d{7,})\s*تومان", normalized)
    return int(match.group(1)) if match else None


def build_market_context(snapshot: dict[str, Any], question: str) -> dict[str, Any]:
    budget = _extract_budget_toman(question)
    if snapshot.get("data_freshness") == "stale":
        selected = []
    else:
        lowered = question.casefold()
        codes = {
            code
            for code, aliases in ASSET_ALIASES.items()
            if any(alias.casefold() in lowered for alias in aliases)
        }
        if "پارسیان" in lowered:
            codes.update(code for code in ASSET_ALIASES if code.startswith("SEKE_PRS"))
        all_assets = snapshot.get("assets", [])
        if any(word in lowered for word in ("رمزارز", "کریپتو", "بیت‌کوین", "اتریوم", "تتر")):
            codes.update(_CRYPTO_CODES)
        if "سکه" in lowered and not any(code.startswith("SEKE_") for code in codes):
            codes.update(code for code in _INVESTABLE_CODES if code.startswith("SEKE_"))
        if any(word in lowered for word in ("نرخ ارز", "ارزها", "دلار و", "یورو", "درهم")):
            codes.update(_CURRENCY_CODES)

        if codes:
            selected = [item for item in all_assets if item.get("code") in codes]
        else:
            # Generic decision questions should receive investable gold/coin
            # options, not global indicators, currencies or crypto.
            selected = [item for item in all_assets if item.get("code") in _INVESTABLE_CODES]

    validated_assets = []
    for item in selected[:16]:
        clean = {"code": item.get("code"), "name": item.get("name"), "category": item.get("category"), "source": item.get("source")}
        for field in ("market_price", "price_change_percent", "real_value", "bubble_absolute", "bubble_percent"):
            value = item.get(field)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise AIServiceError("داده عددی بازار معتبر نیست.")
            clean[field] = value
        price = clean.get("market_price")
        clean["affordable"] = bool(budget and price and price <= budget) if budget else None
        if budget and price:
            if price <= budget:
                clean["budget_status"] = "within_budget"
            elif price <= budget * 1.10:
                clean["budget_status"] = "slightly_above"
            else:
                clean["budget_status"] = "above_budget"
        if budget and price and item.get("code", "").startswith("SEKE_"):
            clean["whole_units_within_budget"] = int(budget // price)
        validated_assets.append(clean)

    return {
        "snapshotTime": snapshot.get("timestamp"),
        "dataFreshness": snapshot.get("data_freshness", "unavailable"),
        "warning": snapshot.get("warning"),
        "userBudgetToman": budget,
        "currencyUnit": "تومان",
        "observableBubbleRanking": [
            {
                "code": item["code"],
                "name": item["name"],
                "bubble_percent": item["bubble_percent"],
            }
            for item in sorted(
                (
                    item
                    for item in validated_assets
                    if item.get("bubble_percent") is not None
                    and (not budget or item.get("budget_status") == "within_budget")
                ),
                key=lambda item: item["bubble_percent"],
            )[:8]
        ],
        "responseIntent": (
            "education_and_calculation"
            if "عوامل" in question.casefold()
            and any(word in question.casefold() for word in ("چطور", "محاسبه", "به دست"))
            else
            "calculation_and_comparison"
            if any(word in question.casefold() for word in ("چطور", "محاسبه", "به دست")) and len(validated_assets) > 1
            else "comparison"
            if len(validated_assets) > 1
            else "single_asset_analysis"
        ),
        "directDataLimitations": [
            "قیمت خرید و فروش و spread فروشنده در Snapshot موجود نیست.",
            "شاخص مستقیم نقدشوندگی در Snapshot موجود نیست.",
            "قیمت مستقیم طلای آب‌شده، عیار انگ و کارمزد معامله در Snapshot موجود نیست؛ GOLD18K فقط نماینده طلای گرمی ۱۸ عیار است.",
        ],
        "assets": validated_assets,
        "sources": snapshot.get("sources", []),
    }


class AIClient:
    def __init__(self, post=requests.post) -> None:
        self.post = post

    @property
    def configured(self) -> bool:
        return bool(os.getenv("SEPAR_AI_API_KEY", "").strip() and os.getenv("SEPAR_AI_MODEL", "").strip())

    def complete(self, question: str, history: list[dict[str, str]], context: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv("SEPAR_AI_API_KEY", "").strip()
        model = os.getenv("SEPAR_AI_MODEL", "").strip()
        if not api_key or not model:
            raise AIServiceError("سرویس هوش مصنوعی تنظیم نشده است.")

        base_url = os.getenv("SEPAR_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        timeout = float(os.getenv("SEPAR_AI_TIMEOUT_SECONDS", "60"))
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history[-8:])
        messages.append(
            {
                "role": "user",
                "content": f"MARKET_CONTEXT:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n\nUSER_QUESTION:\n{question}",
            }
        )
        try:
            response = self.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "reasoning_effort": "minimal",
                    "max_completion_tokens": 1400,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIServiceError("پاسخ سرویس هوش مصنوعی قابل دریافت یا اعتبارسنجی نبود.") from exc


def _validate_output(raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("answer"), str):
        raise AIServiceError("ساختار خروجی مدل معتبر نیست.")
    allowed_codes = {item["code"] for item in context["assets"]}
    mentioned = raw.get("mentionedAssets", [])
    if not isinstance(mentioned, list) or any(code not in allowed_codes for code in mentioned):
        raise AIServiceError("مدل به دارایی خارج از داده معتبر اشاره کرده است.")

    answer = raw["answer"].strip()
    if not answer or len(answer) > 4000:
        raise AIServiceError("متن خروجی مدل معتبر نیست.")
    if context.get("responseIntent") == "education_and_calculation":
        required_topics = ("اونس", "دلار", "عیار", "عرضه", "تقاضا")
        if len(answer) < 250 or sum(topic in answer for topic in required_topics) < 4:
            raise AIServiceError("پاسخ آموزشی مدل کامل نیست.")

    # Reject unsupported price/percentage claims. Educational constants such as
    # weight, purity, horizons and formula values are not market-price claims.
    translate = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    allowed_prices = [
        float(value)
        for item in context["assets"]
        for value in (item.get("market_price"), item.get("real_value"), item.get("bubble_absolute"))
        if value is not None
    ]
    if context.get("userBudgetToman"):
        allowed_prices.append(float(context["userBudgetToman"]))
    allowed_percentages = [
        float(value)
        for item in context["assets"]
        for value in (item.get("price_change_percent"), item.get("bubble_percent"))
        if value is not None
    ]
    allowed_percentages.append(100.0)  # Formula: bubble / intrinsic value × 100.
    normalized_answer = answer.translate(translate).replace("٬", ",")
    numeric_claims = re.findall(
        r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(تومان|ریال|درصد|٪|%)",
        normalized_answer,
    )
    for number, unit in numeric_claims:
        try:
            value = float(re.sub(r"[,\s]", "", number))
        except ValueError:
            raise AIServiceError("خروجی مدل شامل عدد نامعتبر است.")
        allowed = allowed_percentages if unit in ("درصد", "٪", "%") else allowed_prices
        tolerance = 0.55 if unit in ("درصد", "٪", "%") else 1.0
        if not any(abs(value - candidate) <= tolerance for candidate in allowed):
            raise AIServiceError("خروجی مدل شامل عددی خارج از Snapshot معتبر است.")

    risk_notes = raw.get("riskNotes", [])
    follow_ups = raw.get("followUpQuestions", [])
    if isinstance(risk_notes, str):
        risk_notes = [risk_notes]
    if isinstance(follow_ups, str):
        follow_ups = [follow_ups]
    if not isinstance(risk_notes, list) or not all(isinstance(item, str) for item in risk_notes):
        risk_notes = []
    if not isinstance(follow_ups, list) or not all(isinstance(item, str) for item in follow_ups):
        follow_ups = []
    to_persian = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

    def localize_numbers(text: str) -> str:
        for technical, natural in {
            "observableBubbleRanking": "ترتیب حباب مشاهده‌شده",
            "slightly_above": "کمی بالاتر از بودجه",
            "within_budget": "درون بودجه",
            "above_budget": "خارج از بودجه",
        }.items():
            text = text.replace(technical, natural)
        localized = text.translate(to_persian)
        return re.sub(r"(?<=[۰-۹])\.(?=[۰-۹])", "٫", localized)

    return {
        "answer": localize_numbers(answer),
        "mentionedAssets": mentioned[:5],
        "riskNotes": [localize_numbers(item) for item in risk_notes[:4]],
        "followUpQuestions": [localize_numbers(item) for item in follow_ups[:3]],
    }


def _safe_fallback(context: dict[str, Any], question: str) -> dict[str, Any]:
    """Produce a useful grounded answer even when the model response is rejected."""
    candidates = [item for item in context["assets"] if item.get("market_price")]
    budget = context.get("userBudgetToman")
    status_text = {
        "within_budget": "درون بودجه",
        "slightly_above": "کمی بالاتر از بودجه",
        "above_budget": "خارج از بودجه",
    }

    def fa_number(value: float | int, decimals: int = 0) -> str:
        rendered = f"{value:,.{decimals}f}".replace(",", "٬").replace(".", "٫")
        return rendered.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    lines: list[str] = []
    if context.get("responseIntent") == "education_and_calculation":
        lines.extend(
            [
                "نرخ طلای آب‌شده ۱۸ عیار عمدتاً از این عوامل اثر می‌گیرد:",
                "• اونس جهانی طلا: تغییر قیمت جهانی، پایه ارزش طلای داخل را جابه‌جا می‌کند.",
                "• نرخ دلار آزاد: چون ارزش جهانی طلا دلاری است، رشد دلار معمولاً ارزش ریالی طلا را بالا می‌برد.",
                "• عیار واقعی: آب‌شده باید براساس عیار ثبت‌شده روی انگ محاسبه شود؛ ۱۸ عیار معادل خلوص ۷۵۰ است.",
                "• عرضه و تقاضای بازار داخل: کمبود عرضه یا افزایش تقاضای کوتاه‌مدت می‌تواند قیمت معامله را از ارزش محاسباتی دور کند.",
                "• اختلاف خریدوفروش و هزینه معامله: کارمزد، سود فروشنده و فاصله قیمت خرید و فروش بر مبلغ نهایی اثر می‌گذارند.",
            ]
        )
    if context.get("responseIntent") == "calculation_and_comparison":
        lines.append(
            "حباب ریالی از «قیمت بازار منهای ارزش محاسباتی» به‌دست می‌آید؛ "
            "درصد حباب هم برابر است با حباب ریالی تقسیم بر ارزش محاسباتی، ضربدر ۱۰۰."
        )
    elif context.get("responseIntent") == "education_and_calculation":
        lines.append(
            "حباب ریالی = قیمت بازار منهای ارزش محاسباتی؛ درصد حباب = حباب ریالی تقسیم بر ارزش محاسباتی، ضربدر ۱۰۰. "
            "برای آب‌شده، ارزش محاسباتی باید با اونس جهانی، دلار و عیار واقعی همان قطعه ساخته شود."
        )
    if budget:
        lines.append(f"بودجه شما {fa_number(budget)} تومان است و گزینه گران‌تر را قابل‌خرید حساب نکرده‌ام.")

    parsian = [item for item in candidates if item["code"].startswith("SEKE_PRS")]
    individual = [item for item in candidates if not item["code"].startswith("SEKE_PRS")]
    for item in individual:
        bubble = item.get("bubble_percent")
        bubble_text = f"حباب {fa_number(bubble, 1)}٪" if bubble is not None else "حباب قابل‌محاسبه نیست"
        detail = f"؛ {status_text[item['budget_status']]}" if item.get("budget_status") in status_text else ""
        if item["code"] == "GOLD18K" and ("آبشده" in question or "آب شده" in question):
            detail += "؛ این فقط داده مرجع طلای ۱۸ عیار است و قیمت مستقیم آب‌شده و کارمزد آن در داده موجود نیست"
        lines.append(f"• {item['name']}: {bubble_text}{detail}.")

    if parsian:
        parsian_with_bubble = [item for item in parsian if item.get("bubble_percent") is not None]
        if parsian_with_bubble:
            low = min(item["bubble_percent"] for item in parsian_with_bubble)
            high = max(item["bubble_percent"] for item in parsian_with_bubble)
            range_text = fa_number(low, 1) if low == high else f"{fa_number(low, 1)} تا {fa_number(high, 1)}"
            budget_text = "؛ نمونه‌های نمایش‌داده‌شده درون بودجه‌اند" if budget else ""
            lines.append(f"• پارسیان: حباب نمونه‌های موجود {range_text}٪ است{budget_text}.")

    affordable_ranked = sorted(
        (
            item for item in candidates
            if item.get("bubble_percent") is not None
            and (not budget or item.get("budget_status") == "within_budget")
        ),
        key=lambda item: item["bubble_percent"],
    )
    if affordable_ranked:
        rank_names: list[str] = []
        for item in affordable_ranked:
            label = "پارسیان" if item["code"].startswith("SEKE_PRS") else item["name"]
            if label not in rank_names:
                rank_names.append(label)
        lines.append(
            "جمع‌بندی موقت فقط از نظر حباب کمتر: "
            + " ← ".join(rank_names[:5])
            + ". این رتبه‌بندی درباره نقدشوندگی یا کیفیت فروشنده داوری نمی‌کند."
        )

    selected: list[dict[str, Any]] = []
    for item in individual + sorted(parsian, key=lambda row: row.get("bubble_percent") or math.inf):
        if len(selected) == 5:
            break
        selected.append(item)
    if not lines:
        lines.append("داده کافی برای مقایسه مسئولانه گزینه‌ها در دسترس نیست؛ لطفاً کمی بعد دوباره تلاش کنید.")
    return {
        "answer": "\n".join(lines),
        "mentionedAssets": [item["code"] for item in selected],
        "riskNotes": [
            "قیمت خرید و فروش واقعی فروشنده، اختلاف خرید و فروش و شاخص نقدشوندگی لحظه‌ای در داده موجود نیست."
        ],
        "followUpQuestions": ["افق زمانی و میزان تحمل نوسان شما چقدر است؟"],
    }


class SeparAIService:
    def __init__(self, market_service: Any, ai_client: AIClient | None = None) -> None:
        self.market_service = market_service
        self.ai_client = ai_client or AIClient()

    def chat(self, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
        snapshot = self.market_service.get_snapshot()
        recent_user_context = " ".join(
            item.get("content", "")
            for item in history[-6:]
            if item.get("role") == "user"
        )
        context_query = f"{recent_user_context}\n{question}".strip()
        context = build_market_context(snapshot, question)
        if context.get("userBudgetToman") is None:
            previous_budget = _extract_budget_toman(context_query)
            if previous_budget:
                context["userBudgetToman"] = previous_budget
                for item in context["assets"]:
                    price = item.get("market_price")
                    item["affordable"] = bool(price and price <= previous_budget)
                    if price:
                        if price <= previous_budget:
                            item["budget_status"] = "within_budget"
                        elif price <= previous_budget * 1.10:
                            item["budget_status"] = "slightly_above"
                        else:
                            item["budget_status"] = "above_budget"
                    if price and item.get("code", "").startswith("SEKE_"):
                        item["whole_units_within_budget"] = int(previous_budget // price)
                context["observableBubbleRanking"] = [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "bubble_percent": item["bubble_percent"],
                    }
                    for item in sorted(
                        (
                            item
                            for item in context["assets"]
                            if item.get("bubble_percent") is not None
                            and item.get("budget_status") == "within_budget"
                        ),
                        key=lambda item: item["bubble_percent"],
                    )[:8]
                ]
        if context["dataFreshness"] == "stale" or not context["assets"]:
            return {
                "answer": "داده بازار در حال حاضر قدیمی یا ناکافی است؛ برای جلوگیری از ارائه عدد نادرست، تحلیل عددی انجام نمی‌دهم.",
                "mentionedAssets": [],
                "marketSnapshotTime": context["snapshotTime"],
                "dataFreshness": context["dataFreshness"],
                "comparisons": [],
                "riskNotes": ["پس از تازه‌شدن داده دوباره تلاش کنید."],
                "followUpQuestions": [],
                "sources": context["sources"],
            }

        try:
            validated = _validate_output(self.ai_client.complete(question, history, context), context)
        except AIServiceError:
            correction = (
                question
                + "\nپاسخ را بدون هیچ قیمت یا درصد تازه بنویس. فقط اعداد موجود در MARKET_CONTEXT مجازند."
            )
            try:
                validated = _validate_output(self.ai_client.complete(correction, history, context), context)
            except AIServiceError:
                validated = _safe_fallback(context, question)
        assets_by_code = {item["code"]: item for item in context["assets"]}
        mentioned_assets = [assets_by_code[code] for code in validated["mentionedAssets"]]
        comparisons = sorted(
            [
                {"code": item["code"], "name": item["name"], "bubblePercent": item["bubble_percent"]}
                for item in mentioned_assets
                if item["bubble_percent"] is not None
            ],
            key=lambda item: item["bubblePercent"],
        )
        return {
            **validated,
            "mentionedAssets": mentioned_assets,
            "marketSnapshotTime": context["snapshotTime"],
            "dataFreshness": context["dataFreshness"],
            "comparisons": comparisons,
            "sources": context["sources"],
        }
