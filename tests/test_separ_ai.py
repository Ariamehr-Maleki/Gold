from __future__ import annotations

import pytest

from separ_ai_service import (
    AIServiceError,
    RateLimitExceeded,
    SeparAIService,
    SlidingWindowRateLimiter,
    _validate_output,
    build_market_context,
)


SNAPSHOT = {
    "timestamp": "2026-07-27T12:00:00+03:30",
    "data_freshness": "fresh",
    "sources": [{"id": "nerkh", "label": "Nerkh.io"}],
    "assets": [
        {
            "code": "SEKE_EMAMI",
            "name": "سکه امامی",
            "category": "سکه‌های اصلی",
            "market_price": 60_000_000,
            "price_change_percent": None,
            "real_value": 58_558_000,
            "bubble_absolute": 1_442_000,
            "bubble_percent": 2.5,
            "source": "nerkh.io",
        },
        {
            "code": "GOLD18K",
            "name": "طلای ۱۸ عیار",
            "category": "طلای ۱۸ عیار",
            "market_price": 5_000_000,
            "price_change_percent": None,
            "real_value": 4_822_625,
            "bubble_absolute": 177_375,
            "bubble_percent": 3.7,
            "source": "nerkh.io",
        },
    ],
}


class Market:
    def __init__(self, snapshot=SNAPSHOT):
        self.snapshot = snapshot

    def get_snapshot(self):
        return self.snapshot


class AI:
    def complete(self, question, history, context):
        return {
            "answer": "حباب سکه امامی ۲.۵ درصد است.",
            "mentionedAssets": ["SEKE_EMAMI"],
            "riskNotes": ["نوسان بازار را در نظر بگیرید."],
            "followUpQuestions": ["افق زمانی شما چقدر است؟"],
        }


def test_context_selects_only_relevant_asset():
    context = build_market_context(SNAPSHOT, "حباب سکه امامی چقدر است؟")
    assert [item["code"] for item in context["assets"]] == ["SEKE_EMAMI"]


def test_compare_flow_uses_structured_assets():
    result = SeparAIService(Market(), AI()).chat("سکه امامی را بررسی کن", [])
    assert result["mentionedAssets"][0]["market_price"] == 60_000_000
    assert result["marketSnapshotTime"] == SNAPSHOT["timestamp"]
    assert result["comparisons"][0]["bubblePercent"] == 2.5


def test_missing_asset_returns_no_invented_number():
    context = build_market_context(SNAPSHOT, "قیمت بیت‌کوین چیست؟")
    assert context["assets"] == []


def test_stale_data_returns_explicit_safe_response_without_calling_ai():
    stale = {**SNAPSHOT, "data_freshness": "stale"}

    class FailingAI:
        def complete(self, *args):
            raise AssertionError("AI must not be called for stale data")

    result = SeparAIService(Market(stale), FailingAI()).chat("قیمت چیست؟", [])
    assert result["dataFreshness"] == "stale"
    assert result["mentionedAssets"] == []


def test_invalid_model_asset_is_rejected():
    context = build_market_context(SNAPSHOT, "امامی")
    with pytest.raises(AIServiceError):
        _validate_output({"answer": "پاسخ", "mentionedAssets": ["BTC"]}, context)


def test_hallucinated_market_number_is_rejected():
    context = build_market_context(SNAPSHOT, "امامی")
    with pytest.raises(AIServiceError):
        _validate_output({"answer": "قیمت 999999999 تومان است.", "mentionedAssets": ["SEKE_EMAMI"]}, context)


def test_rate_limit():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    limiter.check("ip", now=0)
    limiter.check("ip", now=1)
    with pytest.raises(RateLimitExceeded):
        limiter.check("ip", now=2)
