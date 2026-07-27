# معماری فنی Separ AI

## هدف

`/separ-ai` رابط فارسی و RTL تحلیل بازار سپر است. پاسخ‌های عددی آن باید فقط به Snapshot واقعی موتور قیمت و حباب پروژه متصل باشند.

## جریان درخواست

```text
Browser
  │ POST {message, history[-8:]}
  ▼
application.py
  ├─ sanitize + max length
  ├─ per-client sliding-window rate limit
  └─ SeparAIService
        ├─ MarketService.get_snapshot()
        ├─ reject stale/unavailable numeric analysis
        ├─ select relevant assets (max 16)
        ├─ validate all numeric fields
        ├─ AIClient.complete() with controlled system prompt
        └─ validate JSON, asset codes and numeric grounding
  ▼
Structured response
  ├─ answer
  ├─ mentionedAssets
  ├─ marketSnapshotTime / dataFreshness
  ├─ comparisons / riskNotes / followUpQuestions
  └─ sources
```

## Endpointها

### `POST /api/separ-ai/chat`

Request:

```json
{
  "message": "حباب سکه امامی چقدر است؟",
  "history": [{"role": "user", "content": "وضعیت بازار چیست؟"}]
}
```

تاریخچه به ۸ پیام آخر و هر پیام به `SEPAR_AI_MAX_MESSAGE_LENGTH` محدود است. خروجی شامل کارت‌های ساختاریافته است؛ Frontend هیچ عددی را از متن آزاد مدل parse نمی‌کند.

### `GET /api/separ-ai/health`

تنها آماده‌بودن تنظیمات AI و نام منبع داخلی را اعلام می‌کند و هیچ Secretی برنمی‌گرداند.

### `GET /api/prices`

قرارداد داشبورد فعلی را حفظ می‌کند و دو فیلد `data_freshness` و `sources` به آن افزوده شده است.

## Freshness و خطا

- `fresh`: هر سه ورودی کلیدی اونس، دلار و طلای ۱۸ عیار موجودند.
- `partial`: بخشی از Snapshot موجود است؛ UI می‌تواند داده موجود را نشان دهد.
- `stale`: refresh شکست خورده و cache قبلی موجود است؛ Chat تحلیل عددی نمی‌سازد.
- بدون cache معتبر: API با HTTP 503 پاسخ می‌دهد.
- AI timeout/configuration error: پاسخ 503؛ خروجی نامعتبر مدل: پاسخ 502.
- Rate limit: پاسخ 429 و امکان تلاش مجدد در UI.

## ملاحظات امنیتی

- Prompt دستورهای کاربر را داده تلقی می‌کند و دستورهای متعارض را نادیده می‌گیرد.
- Market Context محدود و ساختاریافته است و کل داده پروژه به مدل ارسال نمی‌شود.
- codeهای `mentionedAssets` باید در context موجود باشند.
- ادعای عددی بزرگ که در Snapshot دیده نمی‌شود رد می‌شود.
- هیچ فرمان تولیدشده توسط مدل اجرا نمی‌شود.
- IP فقط برای Rate Limit در حافظه استفاده می‌شود و لاگ نمی‌شود.

## تست و انتشار

`pytest -q` تست‌های دریافت واقعی از Adapter اصلی، نبود Mock در Production، stale/missing data، مقایسه، validation حباب، Secret exposure، Rate Limit، طول پیام، خطای مدل، RTL و Mobile را اجرا می‌کند.

در Vercel، Environment variableها را تنظیم و سپس `/api/separ-ai/health` و یک درخواست Chat را smoke-test کنید. در صورت استفاده از reverse proxy دیگر، فقط وقتی headerها توسط proxy قابل اعتماد بازنویسی می‌شوند `TRUST_PROXY_HEADERS=1` فعال شود.
