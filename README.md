# Separ — داشبورد بازار سپر و Separ AI

داشبورد فارسی و RTL قیمت طلا، سکه و ارز با محاسبه حباب و دستیار گفت‌وگومحور مبتنی بر همان داده واقعی بازار.

## معماری

```text
Nerkh.io + Navasan
        │
        ▼
market_service.py ── normalize / calculate / cache / freshness
        │
        ├── GET /api/prices ───────────────► داشبورد فعلی
        │
        └── Market Context Builder
                    │
                    ▼
         POST /api/separ-ai/chat ──────────► /separ-ai
                    │
             AI API (server-side)
```

`market_service.py` تنها Source of Truth وب برای دریافت قیمت، نرمال‌سازی و محاسبه حباب است. Separ AI منبع قیمت یا فرمول موازی ندارد و فقط Snapshot اعتبارسنجی‌شده همین سرویس را مصرف می‌کند.

## فایل‌های اصلی

- `market_service.py`: منبع واحد قیمت، محاسبه حباب، cache و freshness
- `separ_ai_service.py`: ساخت Market Context، فراخوانی AI و اعتبارسنجی خروجی
- `application.py`: Routeها، Rate Limit، sanitization و health check
- `backend/main.py`: اجرای Local
- `api/index.py`: ورودی Vercel
- `frontend/index.html`: داشبورد فعلی
- `frontend/separ-ai/index.html`: رابط Chat فارسی و Responsive
- `tests/`: تست‌های Unit و Integration
- `docs/SEPAR_AI.md`: سند فنی مستقل

## Environment variables

فایل `.env.example` فهرست کامل متغیرها را دارد. موارد ضروری:

| متغیر | کاربرد |
|---|---|
| `NERKH_TOKEN` | دریافت طلا و سکه |
| `NAVASAN_API_KEY` | دریافت دلار |
| `SEPAR_AI_API_KEY` | کلید Server-side سرویس AI |
| `SEPAR_AI_MODEL` | نام مدل Chat |
| `SEPAR_AI_BASE_URL` | آدرس OpenAI-compatible API |
| `ALLOWED_ORIGINS` | Originهای مجاز، جداشده با ویرگول |

هیچ Secretی نباید با پیشوند عمومی یا در Frontend قرار گیرد.

## اجرای Local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
set NERKH_TOKEN=...
set NAVASAN_API_KEY=...
set SEPAR_AI_API_KEY=...
set SEPAR_AI_MODEL=...
python backend/main.py
```

- داشبورد: `http://localhost:8000/`
- دستیار سپر: `http://localhost:8000/separ-ai`
- API قیمت: `GET http://localhost:8000/api/prices`
- Chat: `POST http://localhost:8000/api/separ-ai/chat`
- Health: `GET http://localhost:8000/api/separ-ai/health`

## تست

```bash
pip install -r requirements-dev.txt
pytest -q
```

تست‌ها به API واقعی بازار یا AI متصل نمی‌شوند؛ Adapterها mock می‌شوند اما وجود Mock price در مسیر Production ممنوع و تست شده است.

## Deployment

پروژه برای Vercel تنظیم شده است:

1. Repository را به Vercel متصل کنید.
2. متغیرهای `.env.example` را در Project Settings اضافه کنید.
3. Build را Deploy کنید؛ `vercel.json` درخواست‌های `/api/*` را به FastAPI و `/separ-ai` را به صفحه Chat هدایت می‌کند.
4. بعد از Deploy، `/api/separ-ai/health`، `/api/prices` و `/separ-ai` را بررسی کنید.

برای Production، `ALLOWED_ORIGINS=https://arisocoin.com` و `TRUST_PROXY_HEADERS=1` تنظیم شود. کلیدهای قبلی که زمانی داخل Repository بوده‌اند باید در سرویس‌دهنده‌ها rotate شوند.

## امنیت و محدودیت‌ها

- کلید AI و کلیدهای بازار فقط Server-side هستند.
- طول پیام، تعداد پیام‌های تاریخچه، timeout و Rate Limit محدود است.
- کل Database یا Snapshot کامل به مدل ارسال نمی‌شود؛ فقط دارایی‌های مرتبط و حداکثر ۱۶ مورد ارسال می‌شود.
- خروجی مدل Schema-check می‌شود و عدد بزرگ خارج از Snapshot رد می‌شود.
- Snapshot قدیمی صریحاً اعلام می‌شود و در آن حالت تحلیل عددی تولید نمی‌شود.
- لاگ‌ها متن پیام، اطلاعات هویتی یا Secret را ذخیره نمی‌کنند.
