# Crypto Quant Alpha Scanner

A quantitative screening tool that identifies low-cap altcoins ($20M-$150M market cap) statistically primed to amplify Bitcoin's movements. Computes rolling **Beta**, **Correlation**, and **Half-Kelly position sizing** across multiple exchanges, with both a CLI and a 24/7 live web dashboard.

## The Alpha Thesis

When Bitcoin breaks out, certain small-cap altcoins historically amplify that move by 2x-5x. This scanner finds those coins by:

1. **Fetching** the universe of $20M-$150M market cap coins from CoinGecko
2. **Mapping** them to trading pairs across KuCoin, OKX, and Gate (or any ccxt exchange)
3. **Computing** 30-day rolling Beta and Correlation against BTC from 60 days of daily OHLCV data
4. **Filtering** for Beta > 1.5, Correlation > 0.7, 24h Volume > $1M, and sufficient data history
5. **Ranking** survivors by Beta descending — highest amplification potential first
6. **Sizing** each position with Half-Kelly criterion (capped at 25%) for risk management

**This is NOT a trading bot.** It never executes orders. It is a read-only scanner that surfaces statistical signals for human decision-making.

## Quick Start

```bash
# Clone and install
git clone https://github.com/bobbypolo/CryptoScanner.git
cd CryptoScanner
python -m venv .venv
.venv/Scripts/activate    # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"

# Set up CoinGecko API key (free demo key works)
echo "COINGECKO_API_KEY=your-key-here" > .env

# Run a one-shot scan (CLI)
python -m quant_scanner

# Or launch the live dashboard
python -m quant_scanner --serve --port 9000
# Open http://127.0.0.1:9000 in your browser
```

### Dry Run (No API Calls)

```bash
python -m quant_scanner --dry-run
```

Outputs a sample Rich table with mock data — useful for verifying the install works.

## Live Web Dashboard

The dashboard runs 24/7 and auto-refreshes scan results on a configurable interval.

```bash
python -m quant_scanner --serve --port 9000 --refresh-interval 120
```

**Stack:** FastAPI + Jinja2 + HTMX polling + WebSocket push updates

**Features:**
- Dark theme UI with color-coded metrics (green = strong signal, yellow = moderate, dim = weak)
- HTMX auto-polling (table every 60s, status every 10s) with WebSocket instant push on scan completion
- Manual refresh button (POST /api/refresh with 10s cooldown)
- JSON API endpoints for programmatic access
- Graceful error handling — failed scans show error status, server keeps running
- Auto-reconnecting WebSocket with exponential backoff

### Dashboard API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Full HTML dashboard |
| `/api/health` | GET | Server status, uptime, scanner state, WS client count |
| `/api/scan` | GET | JSON scan results with NaN-safe serialization |
| `/api/history` | GET | Last N scan snapshot summaries |
| `/api/refresh` | POST | Trigger immediate scan (202 Accepted) |
| `/partials/table` | GET | HTMX partial: results table |
| `/partials/status` | GET | HTMX partial: status bar |
| `/ws/updates` | WS | Real-time push notifications on scan completion |
| `/favicon.ico` | GET | 204 No Content (prevents browser log spam) |

### Health Check Response

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 3600.5,
  "scanner": {
    "status": "idle",
    "last_scan_at": "2026-02-25T14:30:00+00:00",
    "scan_count": 42,
    "coin_count": 5,
    "error": null
  },
  "websocket_clients": 2
}
```

## Multi-Exchange Support

The scanner automatically screens across multiple exchanges. If one exchange is unavailable (geo-blocked, down, rate-limited), it is skipped gracefully.

```bash
# Default: scans KuCoin, OKX, and Gate simultaneously
python -m quant_scanner --serve --port 9000

# Single exchange
python -m quant_scanner --exchange kucoin

# Custom list (comma-separated, any ccxt exchange ID)
python -m quant_scanner --exchange kucoin,okx,gate,kraken
```

**How it works:**
- Markets are loaded from all specified exchanges in parallel
- Each coin is matched to the first exchange in the list that carries it (preference order matters)
- OHLCV data is fetched per-exchange with independent rate limiting (Semaphore(10) per exchange)
- Results are merged, aligned to BTC's timestamp index, and fed through the unified math pipeline

**Tested exchanges:** KuCoin, OKX, Gate. Binance is geo-restricted in some regions (HTTP 451).

## CLI Reference

```
usage: python -m quant_scanner [OPTIONS]

Options:
  --dry-run                  Use mock data, no API calls
  --exchange EXCHANGE        Comma-separated ccxt exchange IDs (default: kucoin,okx,gate)
  --min-mcap MIN_MCAP        Minimum market cap in USD (default: 20000000)
  --max-mcap MAX_MCAP        Maximum market cap in USD (default: 150000000)
  --min-beta MIN_BETA        Minimum Beta threshold (default: 1.5)
  --min-corr MIN_CORR        Minimum correlation threshold (default: 0.7)
  --min-volume MIN_VOLUME    Minimum 24h volume in USD (default: 1000000)
  --no-cache                 Force fresh API calls, bypass cache
  --serve                    Launch live web dashboard
  --port PORT                Dashboard port (default: 8080)
  --host HOST                Dashboard bind address (default: 127.0.0.1)
  --refresh-interval SECS    Scan refresh interval in seconds (default: 300)
```

**Examples:**

```bash
# One-shot scan with default filters
python -m quant_scanner

# Aggressive scan: lower thresholds, wider market cap range
python -m quant_scanner --min-beta 1.2 --min-corr 0.6 --min-mcap 10000000 --max-mcap 300000000

# Dashboard on all interfaces (LAN accessible)
python -m quant_scanner --serve --host 0.0.0.0 --port 8080 --refresh-interval 60

# Fresh data, no cache
python -m quant_scanner --no-cache
```

## Mathematical Model

### Beta (Market Sensitivity)

```
Beta = Cov(R_asset, R_btc) / Var(R_btc)
```

- 30-day rolling window, minimum 20 valid observations
- Beta > 1.5 means the altcoin amplifies BTC moves by 1.5x or more
- Zero-variance guard: if Var(R_btc) = 0, Beta = NaN (not infinity)

### Correlation (Directional Alignment)

```
Corr = Rolling Pearson Correlation(R_asset, R_btc)
```

- 30-day rolling window, minimum 20 valid observations
- Correlation > 0.7 means the altcoin reliably moves in the same direction as BTC
- High Beta + Low Correlation = unreliable amplification (filtered out)

### Half-Kelly Position Sizing

```
Kelly = (b * p - q) / b
Position = min(Kelly / 2, 0.25)
```

Where `p` = win rate, `q` = 1 - p, `b` = average win / average loss.

- Half-Kelly achieves ~75% of full Kelly growth rate with significantly lower max drawdown
- Capped at 25% to prevent catastrophic concentration
- Returns 0.0 if there are no wins OR no losses (can't estimate odds)

### Data Pipeline

```
CoinGecko API               ccxt (KuCoin/OKX/Gate)
     |                              |
     v                              v
Universe: $20M-$150M MC     60-day daily OHLCV candles
     |                              |
     +--------- Symbol Mapping -----+
                     |
                     v
          Timestamp Alignment (reindex to BTC, ffill limit=3)
                     |
                     v
          Simple Returns: pct_change()
                     |
                     v
          Rolling Beta, Correlation, Kelly (window=30, min_periods=20)
                     |
                     v
          Filter: Beta>1.5, Corr>0.7, Vol>$1M, data_days>=20
                     |
                     v
          Rank by Beta descending → Output
```

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                      cli.py                          │
│  argparse → --dry-run | --serve | one-shot scan      │
└───────┬──────────────────────┬───────────────────────┘
        │                      │
   [--serve]              [one-shot]
        │                      │
        v                      v
┌──────────────┐    ┌──────────────────────┐
│  server.py   │    │  screener_engine.py  │
│  FastAPI     │───>│  run_screen()        │
│  + scheduler │    │  ├─ fetch_universe() │
│  + WebSocket │    │  ├─ map_symbols()    │
│  + HTMX UI   │    │  ├─ fetch_ohlcv()   │
└──────────────┘    │  ├─ compute_metrics()│
                    │  └─ apply_filters()  │
                    └───────┬──────────┬───┘
                            │          │
                            v          v
                    ┌──────────┐ ┌────────────┐
                    │ingestion │ │math_engine │
                    │_engine   │ │            │
                    │          │ │ Beta       │
                    │CoinGecko │ │ Correlation│
                    │ccxt async│ │ Kelly      │
                    │caching   │ │            │
                    └──────────┘ └────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Raw aiohttp over pycoingecko | pycoingecko is unmaintained; raw aiohttp enables native async + custom rate limiting |
| 3-layer rate limiting | ccxt builtin + Semaphore(10) + exponential backoff handles all edge cases |
| JSON disk cache | No database needed; human-readable; zero infrastructure; 12h CoinGecko / 6h OHLCV TTL |
| Simple returns over log returns | Aggregates correctly across portfolios; difference negligible for daily crypto |
| Half-Kelly over full Kelly | Full Kelly assumes perfect estimation; half-Kelly is more robust with estimated parameters |
| ThreadedResolver for DNS | aiodns (C-ARES) fails on certain Windows configurations; stdlib resolver works everywhere |
| Multi-exchange with fallback | Binance geo-blocks some regions; scanning multiple exchanges gives broader coverage |

## Project Structure

```
CryptoScanner/
├── src/quant_scanner/
│   ├── __init__.py            # Version, aiohttp DNS patch
│   ├── __main__.py            # python -m entry point
│   ├── cli.py                 # CLI argument parsing + entry points
│   ├── ingestion_engine.py    # CoinGecko API, ccxt OHLCV, caching, symbol mapping
│   ├── math_engine.py         # Beta, Correlation, Kelly calculations
│   ├── screener_engine.py     # Filter pipeline + multi-exchange orchestration
│   ├── dashboard.py           # Rich terminal table renderer
│   ├── server.py              # FastAPI app, routes, Jinja2, lifespan
│   ├── scan_store.py          # Coroutine-safe in-memory data store
│   ├── scheduler.py           # Background scan loop with drift correction
│   ├── ws_manager.py          # WebSocket connection manager
│   ├── templates/
│   │   ├── index.html         # Main dashboard page (HTMX + WS)
│   │   └── partials/
│   │       ├── table.html     # Scan results table partial
│   │       └── status.html    # Status bar partial
│   └── static/
│       ├── style.css          # Dark theme CSS
│       ├── charts.js          # Chart placeholder
│       └── vendor/            # Local HTMX/Charts fallbacks
├── tests/
│   ├── conftest.py
│   ├── test_cli.py            # CLI argument tests (10)
│   ├── test_ingestion.py      # Ingestion engine tests (9)
│   ├── test_math.py           # Math engine tests (12)
│   ├── test_screener.py       # Screener filter tests (17)
│   ├── test_scaffold.py       # Async infrastructure test (1)
│   ├── test_server.py         # Server route tests (22)
│   ├── test_scan_store.py     # Data store tests (11)
│   ├── test_scheduler.py      # Scheduler tests (8)
│   ├── test_ws_manager.py     # WebSocket manager tests (7)
│   └── test_integration_dashboard.py  # End-to-end integration tests (7)
├── cache/                     # Auto-created JSON cache directory
├── pyproject.toml
├── pytest.ini
├── .env                       # CoinGecko API key (not committed)
└── .gitignore
```

## Testing

All 111 tests run with zero network calls (everything mocked).

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test module
python -m pytest tests/test_math.py -v

# Quick summary
python -m pytest tests/ -q
```

**Test breakdown:**
- Math engine: 12 tests (Beta, Correlation, Kelly edge cases)
- Ingestion: 9 tests (filtering, caching, symbol mapping, alignment)
- Screener: 17 tests (filter pipeline, merge metadata, end-to-end)
- CLI: 10 tests (argument parsing, flag defaults)
- Server routes: 22 tests (all HTTP endpoints, Jinja2 filters, NaN safety)
- ScanStore: 11 tests (thread safety, copy semantics, NaN→None serialization)
- Scheduler: 8 tests (lifecycle, error recovery, trigger mechanism)
- WebSocket: 7 tests (connect, disconnect, broadcast, fault tolerance)
- Integration: 7 tests (full lifecycle, error recovery, concurrent requests)

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `COINGECKO_API_KEY` | Recommended | CoinGecko Demo API key. Works without it on the free tier but with lower rate limits. |

### Caching

The scanner uses JSON disk cache to avoid redundant API calls:

- **CoinGecko universe:** cached for 12 hours in `cache/coingecko_coins.json`
- **OHLCV data:** cached per-symbol for 6 hours in `cache/ohlcv/SYMBOL_USDT.json`
- Use `--no-cache` to bypass and force fresh API calls

### Screening Thresholds

All thresholds are configurable via CLI flags:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Market cap range | $20M - $150M | CoinGecko universe filter |
| Beta | > 1.5 | Minimum market sensitivity to BTC |
| Correlation | > 0.7 | Minimum directional alignment with BTC |
| 24h Volume | > $1M | Minimum trading volume (liquidity filter) |
| Data days | >= 20 | Minimum valid data points (non-configurable, hardcoded) |
| Circulating supply | > 70% | Filters low-float coins (NaN values pass) |

## Requirements

- Python >= 3.11
- Windows, macOS, or Linux
- Internet connection for API access
- Free CoinGecko API key (recommended)

## License

Private repository. All rights reserved.
