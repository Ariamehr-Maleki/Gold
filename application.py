"""Shared FastAPI application for local and Vercel deployments."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent


def _load_local_env() -> None:
    """Load the ignored local .env without adding a runtime dependency."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


_load_local_env()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from market_service import MarketDataUnavailable, market_service
from separ_ai_service import (
    AIClient,
    AIServiceError,
    RateLimitExceeded,
    SeparAIService,
    SlidingWindowRateLimiter,
)

log = logging.getLogger("separ")
FRONTEND = ROOT / "frontend"
MAX_MESSAGE_LENGTH = int(os.getenv("SEPAR_AI_MAX_MESSAGE_LENGTH", "1200"))


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ConversationMessage] = Field(default_factory=list)


def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _clean_message(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="پیام خالی است.")
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=413, detail=f"طول پیام باید حداکثر {MAX_MESSAGE_LENGTH} نویسه باشد.")
    return cleaned


def _clean_history_message(value: str, role: str) -> str:
    """History can contain our own longer answers; it must not fail user-input validation."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()
    limit = MAX_MESSAGE_LENGTH if role == "user" else 4000
    return cleaned[:limit]


def create_app(serve_frontend: bool = False) -> FastAPI:
    app = FastAPI(title="سپر و Separ AI")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    ai_client = AIClient()
    chat_service = SeparAIService(market_service, ai_client)
    limiter = SlidingWindowRateLimiter(
        limit=int(os.getenv("SEPAR_AI_RATE_LIMIT", "12")),
        window_seconds=int(os.getenv("SEPAR_AI_RATE_WINDOW_SECONDS", "60")),
    )

    @app.get("/api/prices")
    def get_prices():
        try:
            snapshot = market_service.get_snapshot()
            return {key: snapshot[key] for key in ("timestamp", "timestamp_display", "data_freshness", "sources", "groups")}
        except MarketDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/separ-ai/health")
    def separ_ai_health():
        return {
            "status": "ok" if ai_client.configured else "configuration_required",
            "aiConfigured": ai_client.configured,
            "marketSource": "internal-market-service",
        }

    @app.post("/api/separ-ai/chat")
    def separ_ai_chat(payload: ChatRequest, request: Request):
        forwarded = request.headers.get("x-forwarded-for", "") if os.getenv("TRUST_PROXY_HEADERS") == "1" else ""
        client_key = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
        try:
            limiter.check(client_key)
            message = _clean_message(payload.message)
            history = [
                {"role": item.role, "content": _clean_history_message(item.content, item.role)}
                for item in payload.history[-8:]
                if item.content.strip()
            ]
            return chat_service.chat(message, history)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except MarketDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AIServiceError as exc:
            log.warning("Separ AI request failed: %s", exc)
            status = 503 if not ai_client.configured else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    if serve_frontend and FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/")
        def serve_index():
            return FileResponse(FRONTEND / "index.html")

        @app.get("/separ-ai")
        @app.get("/separ-ai/")
        def serve_separ_ai():
            return FileResponse(FRONTEND / "separ-ai" / "index.html")

    return app
