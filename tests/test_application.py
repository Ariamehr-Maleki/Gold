from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import application
from test_separ_ai import SNAPSHOT


def make_client(monkeypatch):
    monkeypatch.setenv("SEPAR_AI_API_KEY", "server-secret")
    monkeypatch.setenv("SEPAR_AI_MODEL", "test-model")
    monkeypatch.setenv("SEPAR_AI_RATE_LIMIT", "20")
    monkeypatch.setattr(application.market_service, "get_snapshot", lambda *args, **kwargs: SNAPSHOT)
    monkeypatch.setattr(
        application.AIClient,
        "complete",
        lambda self, question, history, context: {
            "answer": "حباب سکه امامی ۲.۵ درصد است.",
            "mentionedAssets": ["SEKE_EMAMI"],
            "riskNotes": [],
            "followUpQuestions": [],
        },
    )
    return TestClient(application.create_app())


def test_chat_endpoint_returns_grounded_contract(monkeypatch):
    response = make_client(monkeypatch).post("/api/separ-ai/chat", json={"message": "حباب امامی چقدر است؟"})
    assert response.status_code == 200
    body = response.json()
    assert body["mentionedAssets"][0]["code"] == "SEKE_EMAMI"
    assert body["marketSnapshotTime"] == SNAPSHOT["timestamp"]
    assert "server-secret" not in response.text


def test_too_long_message(monkeypatch):
    response = make_client(monkeypatch).post("/api/separ-ai/chat", json={"message": "ا" * 1201})
    assert response.status_code == 413


def test_health_never_exposes_key(monkeypatch):
    response = make_client(monkeypatch).get("/api/separ-ai/health")
    assert response.status_code == 200
    assert response.json()["aiConfigured"] is True
    assert "server-secret" not in response.text


def test_rtl_page_and_mobile_viewport_exist():
    page = Path(application.ROOT / "frontend" / "separ-ai" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="fa" dir="rtl">' in page
    assert 'name="viewport"' in page
    assert "@media(max-width:720px)" in page
