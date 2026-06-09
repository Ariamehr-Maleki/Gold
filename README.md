# Iranian Gold & Coin Price Dashboard — داشبورد قیمت طلا و سکه

A real-time, RTL Persian dashboard for Iranian gold and coin prices with bubble-calculation analytics.

## Features

- Live prices from **Nerkh.io** (gold/coins) and **Navasan** (USD)
- Intrinsic value & bubble % calculation for all coins and 18K gold
- Color-coded bubble badges (green ≤ 5%, amber 5–15%, red > 15%)
- Auto-refresh every 60 seconds with countdown timer
- Sort coins by bubble % (ascending)
- Flash animation on price changes
- Light / dark mode toggle
- Fully responsive — 2-column card grid (iOS "Chand?!" style)

## File Structure

```
backend/
├── main.py                 # FastAPI server + /api/prices endpoint
├── requirements.txt        # Python dependencies (this folder only)
└── GOLD_DASHBOARD_README.md

frontend/
└── index.html              # Standalone HTML/CSS/JS dashboard
```

## Quick Start

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the server

```bash
python main.py
```

The server starts on **http://localhost:8000**

| URL | Description |
|-----|-------------|
| http://localhost:8000/ | Dashboard UI |
| http://localhost:8000/api/prices | JSON API |

### 3. Open the dashboard

Navigate to **http://localhost:8000** in your browser.

> You can also open `frontend/index.html` directly — it auto-connects to `http://localhost:8000/api/prices` when opened from disk.

---

## API Response Format

`GET /api/prices`

```json
{
  "timestamp": "2024-01-19T13:23:00+03:30",
  "timestamp_display": "13:23:00",
  "groups": [
    {
      "id": "main_coins",
      "title": "سکه‌های اصلی",
      "subtitle": "سکه‌های بانک مرکزی",
      "items": [
        {
          "code": "SEKE_EMAMI",
          "name": "سکه امامی",
          "market_price": 150000000,
          "real_value": 140000000,
          "bubble_absolute": 10000000,
          "bubble_percent": 7.1
        }
      ]
    }
  ]
}
```

## Bubble Calculation Logic

| Item | Formula |
|------|---------|
| `GOLD18K` | `(ounce_usd × usd_toman × 0.750) / 31.10343` |
| Coins — purity 900 | `weight × (900/750) × gold18k_market_price` |
| Coins — purity 750 | `weight × (750/750) × gold18k_market_price` |
| `bubble_percent` | `((market − real) / real) × 100` |

Bubble color thresholds:

| Range | Color |
|-------|-------|
| ≤ 5%  | 🟢 Green |
| 5–15% | 🟡 Amber |
| > 15% | 🔴 Red |

## Data Sources

| Source | Data | Endpoint |
|--------|------|----------|
| [Nerkh.io](https://nerkh.io) | Gold, coins (all types) | `api.nerkh.io/v1/prices/json/gold` |
| [Navasan](https://navasan.tech) | USD exchange rate | `api.navasan.tech/latest/` |

## Notes

- All prices are in **Iranian Tomans (تومان)**
- Timestamps use **Tehran timezone** (`Asia/Tehran`, UTC+3:30)
- API credentials are embedded for development — rotate them before deploying publicly
