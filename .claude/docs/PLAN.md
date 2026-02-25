# Crypto Quant Alpha Scanner — Master Build Plan

> **Version:** 1.0-FINAL
> **Date:** 2026-02-25
> **Status:** Ready for execution
> **Estimated LOC:** ~1,400 implementation + ~600 tests

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack & Dependencies](#3-tech-stack--dependencies)
4. [Module Specifications](#4-module-specifications)
5. [Data Flow](#5-data-flow)
6. [Mathematical Specifications](#6-mathematical-specifications)
7. [API Contracts & Rate Limits](#7-api-contracts--rate-limits)
8. [Known Landmines & Mitigations](#8-known-landmines--mitigations)
9. [Testing Strategy](#9-testing-strategy)
10. [Build Sequence (prd.json)](#10-build-sequence-prdjson)
11. [Acceptance Gate Details](#11-acceptance-gate-details)
12. [Out of Scope](#12-out-of-scope)
13. [Future Roadmap](#13-future-roadmap)

---

## 1. System Overview

### What It Is

A localized, read-only Python application that scans the crypto market for
low-cap altcoins ($20M–$150M market cap) that are mathematically primed to
amplify Bitcoin's movements. It outputs color-coded buy-signals to the terminal.

### What It Is NOT

- NOT a trading bot — it never executes orders
- NOT a real-time streaming system — it runs on-demand, one-shot scans
- NOT a database-backed application — no persistence between runs (optional cache only)

### The Core Thesis

When Bitcoin breaks out, certain small-cap altcoins historically amplify that
move by 2x–5x. This scanner finds those coins by computing their statistical
Beta and Correlation to BTC over a rolling 30-day window, then filtering for
coins with strong fundamentals (sufficient liquidity, healthy tokenomics).

### The 3 Questions It Answers

1. **Which coins move hardest when BTC moves?** → Beta > 1.5
2. **Which coins move in the same direction as BTC?** → Correlation > 0.7
3. **Which of those coins can I actually trade?** → Volume > $1M/day, MC $20M–$150M

---

## 2. Architecture

### Directory Structure

```
F:\TradingScanner\
├── src/
│   └── quant_scanner/
│       ├── __init__.py              # Package marker + version
│       ├── __main__.py              # Entry: python -m quant_scanner
│       ├── cli.py                   # argparse CLI definition
│       ├── ingestion_engine.py      # CoinGecko universe + ccxt OHLCV
│       ├── math_engine.py           # Beta, Correlation, Kelly Criterion
│       ├── screener_engine.py       # Filter pipeline combining above
│       └── dashboard.py             # rich terminal output
├── tests/
│   ├── conftest.py                  # Shared fixtures, mock data generators
│   ├── test_ingestion.py            # Universe filtering + OHLCV format tests
│   ├── test_math.py                 # Beta/Correlation mathematical proofs
│   ├── test_screener.py             # End-to-end screening logic
│   └── test_cli.py                  # CLI flag parsing + dry-run test
├── cache/                           # Git-ignored, auto-created at runtime
│   ├── coingecko_universe.json      # Cached CoinGecko /coins/markets
│   └── ohlcv/                       # Cached OHLCV per symbol
│       ├── BTC_USDT.json
│       └── ...
├── pyproject.toml                   # Single source of truth for deps + config
├── pytest.ini                       # SOLE pytest config (do NOT duplicate in pyproject.toml)
├── .env.example                     # Template for API keys
├── .gitignore                       # Excludes cache/, .env, __pycache__
└── README.md                        # (only if user requests)
```

### Module Dependency Graph

```
cli.py
  └── screener_engine.py
        ├── ingestion_engine.py
        │     ├── aiohttp (CoinGecko)
        │     ├── ccxt.async_support (OHLCV)
        │     └── aiolimiter (rate limiting)
        └── math_engine.py
              ├── pandas (rolling stats)
              └── numpy (covariance, variance)
  └── dashboard.py
        └── rich (Table, Console, Text)
```

### Data Flow (Single Scan Execution)

```
[CoinGecko API] ──(aiohttp)──> fetch_universe()
     │                              │
     │                    Filter: $20M < MC < $150M
     │                    Exclude: stablecoins, wrapped
     │                              │
     │                    Symbol mapping: "render" → "RENDER/USDT"
     │                    Cross-ref: exchange.load_markets()
     │                              │
     ▼                              ▼
[Exchange API] ──(ccxt async)──> fetch_historical_data()
     │                              │
     │                    60 days daily OHLCV + BTC/USDT baseline
     │                    Align timestamps via DatetimeIndex reindex
     │                              │
     ▼                              ▼
                          calculate_metrics()
                              │
                    Beta = Cov(R_alt, R_btc) / Var(R_btc)
                    Correlation = rolling(30).corr()
                    Kelly = half-Kelly with 25% cap
                              │
                              ▼
                          screen_universe()
                              │
                    Beta > 1.5, Corr > 0.7, Vol > $1M
                    Supply > 70% circulating (if data available)
                    Rank by Beta descending
                              │
                              ▼
                        render_dashboard()
                              │
                    rich.table.Table to terminal
```

---

## 3. Tech Stack & Dependencies

### Runtime Dependencies

| Package | Version | Purpose | Why This One |
|---------|---------|---------|-------------|
| `ccxt` | >=4.0 | Unified exchange API, async OHLCV | Industry standard, 100+ exchanges, built-in rate limiter |
| `aiohttp` | >=3.9 | Async HTTP client for CoinGecko | Lighter than requests, native async, no wrapper library needed |
| `aiolimiter` | >=1.1 | Leaky-bucket rate limiter | Clean asyncio integration, prevents CoinGecko 429s |
| `pandas` | >=2.1 | DataFrames, rolling stats | `.rolling().cov()`, `.rolling().corr()` — the math backbone |
| `numpy` | >=1.26 | Numerical ops | `np.cov()`, `np.nan`, variance calculations |
| `rich` | >=13.0 | Terminal dashboard | Color-coded tables, no curses/ncurses complexity |
| `python-dotenv` | >=1.0 | .env loading | Secure API key management |

### Dev Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=8.0 | Test framework |
| `pytest-asyncio` | >=0.23 | Async test support |
| `pytest-mock` | >=3.12 | Mock fixtures |

### Why NOT These

| Rejected | Reason |
|----------|--------|
| `pycoingecko` | Unmaintained since Nov 2024, Snyk flags as inactive |
| `click` / `typer` | Overkill for 4 flags; argparse is stdlib, zero deps |
| `sqlalchemy` / any DB | No persistence needed; JSON cache suffices |
| `websockets` | No real-time streaming; on-demand scan only |

---

## 4. Module Specifications

### 4.1 `ingestion_engine.py`

#### Public Interface

```python
async def fetch_universe(
    min_mcap: float = 20_000_000,
    max_mcap: float = 150_000_000,
    use_cache: bool = True,
    cache_ttl_hours: int = 12,
) -> list[dict]:
    """
    Fetch top 1000 coins from CoinGecko, filter by market cap,
    exclude stablecoins and wrapped tokens.

    IMPORTANT: CoinGecko can return market_cap=null for some coins.
    These must be filtered out BEFORE the numeric comparison to avoid TypeError.

    Cache writes use os.makedirs("cache", exist_ok=True) to auto-create dir.
    Uses load_dotenv() for COINGECKO_API_KEY; falls back to public tier if absent.

    Returns list of dicts with keys:
        id, symbol, name, market_cap, fully_diluted_valuation,
        circulating_supply, total_supply, total_volume
    """

async def fetch_historical_data(
    symbols: list[str],
    exchange_id: str = "binance",
    timeframe: str = "1d",
    days: int = 60,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for given symbols + BTC/USDT baseline.

    CRITICAL: Uses datetime.now(timezone.utc) for 'since' timestamp, NOT
    datetime.now() which gives local time on Windows and causes off-by-hours.

    CRITICAL: Must call await exchange.close() in a try/finally block to
    prevent ResourceWarning: unclosed client session.

    Returns dict mapping symbol (e.g., "RENDER/USDT") to DataFrame:
        index: DatetimeIndex (UTC)
        columns: open, high, low, close, volume

    BTC/USDT is always included under key "BTC/USDT".
    All DataFrames are aligned to BTC's DatetimeIndex.
    """

def map_coingecko_to_ccxt(
    cg_coins: list[dict],
    exchange_markets: dict,
) -> list[dict]:
    """
    Convert CoinGecko symbols to CCXT trading pair format.
    Cross-reference against exchange markets.
    Drop symbols that don't exist on the exchange.

    Mapping logic:
        cg_coin["symbol"] -> upper() -> append "/USDT"
        Verify "{SYMBOL}/USDT" exists in exchange_markets
        Handle duplicates: prefer the coin with higher MC rank
    """
```

#### Exclusion Lists (Hardcoded Constants)

```python
STABLECOINS = frozenset({
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDP",
    "GUSD", "LUSD", "SUSD", "USDD", "PYUSD", "FDUSD", "EURC",
})

WRAPPED_TOKENS = frozenset({
    "WBTC", "WETH", "WBNB", "STETH", "WSTETH", "CBETH",
    "RETH", "MSOL", "BNSOL", "JITOSOL",
})
```

#### Caching Strategy

- **CoinGecko universe:** Saved to `cache/coingecko_universe.json` with a
  `fetched_at` timestamp. Valid for `cache_ttl_hours` (default 12h).
  On cache hit, skip API call entirely.
- **OHLCV data:** Saved per symbol to `cache/ohlcv/{SYMBOL}_USDT.json` with
  `fetched_at`. Valid for 6 hours. Format: list of
  `[timestamp, open, high, low, close, volume]`.
- **Cache directory:** Auto-created at runtime via `os.makedirs(path, exist_ok=True)`
  BEFORE every cache write. This is mandatory — without it, the first write
  crashes with FileNotFoundError. Git-ignored.
- **Cache bypass:** `use_cache=False` forces fresh API calls.

#### Rate Limiting Strategy (3-Layer Defense)

```
Layer 1: ccxt enableRateLimit=True          (per-exchange auto-throttle)
Layer 2: asyncio.Semaphore(10)              (max 10 concurrent OHLCV fetches)
Layer 3: aiolimiter.AsyncLimiter(25, 60)    (CoinGecko: 25 req/60s)
         + exponential backoff with jitter   (retry on 429/5xx, max 5 attempts)
```

#### Symbol Mapping — The Critical Path

This is the #1 source of silent failures in crypto data pipelines.

**Problem:** CoinGecko returns `{"symbol": "render", "id": "render-token"}`.
CCXT expects `"RENDER/USDT"`. Multiple CoinGecko coins can share the symbol
`"AI"` or `"ONE"`.

**Solution:**

1. For each CoinGecko coin, construct candidate pair: `coin["symbol"].upper() + "/USDT"`
2. Call `exchange.load_markets()` once (cached internally by ccxt)
3. Check if candidate pair exists in `exchange.markets`
4. If multiple CoinGecko coins map to the same pair, keep the one with higher
   `market_cap_rank` (lower rank number = higher cap)
5. Log dropped coins (no match on exchange) for debugging

#### Timestamp Alignment

**Problem:** Altcoin X might have no candle on Feb 14 (exchange maintenance),
but BTC does. If DataFrames are different lengths, `rolling().cov()` produces
wrong results silently.

**Solution:**

1. BTC/USDT DataFrame is the "master index"
2. All altcoin DataFrames are reindexed to BTC's DatetimeIndex:
   ```python
   alt_df = alt_df.reindex(btc_df.index)
   ```
3. Forward-fill NaN gaps up to 3 days: `alt_df.ffill(limit=3)`
4. Any remaining NaN after ffill → leave as NaN (math engine handles it via
   `min_periods`)

---

### 4.2 `math_engine.py`

#### Public Interface

```python
def calculate_beta(
    asset_returns: pd.Series,
    btc_returns: pd.Series,
    window: int = 30,
    min_periods: int = 20,
) -> pd.Series:
    """
    Rolling Beta = Cov(R_asset, R_btc) / Var(R_btc)

    Guards:
        - If Var(R_btc) == 0 in any window → returns NaN for that window
        - If fewer than min_periods valid observations → returns NaN
    """

def calculate_correlation(
    asset_returns: pd.Series,
    btc_returns: pd.Series,
    window: int = 30,
    min_periods: int = 20,
) -> pd.Series:
    """
    Rolling 30-day Pearson correlation.
    Uses asset_returns.rolling(window, min_periods=min_periods).corr(btc_returns)
    """

def calculate_kelly(
    returns: pd.Series | np.ndarray,
    max_fraction: float = 0.25,
    min_trades: int = 30,
) -> float:
    """
    Half-Kelly position sizing with safety cap.

    Formula: f* = (b*p - q) / b, then f = f*/2
    Where:
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p

    Guards:
        - If len(returns) < min_trades → returns 0.0
        - If no wins OR no losses in series → returns 0.0 (can't estimate odds)
        - If f* <= 0 (no edge) → returns 0.0
        - Caps at max_fraction (default 25%)
    """

def compute_all_metrics(
    ohlcv_data: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Master function. For each altcoin in ohlcv_data:
        1. Compute daily returns (pct_change) — note: first row is NaN
        2. Calculate rolling beta vs BTC
        3. Calculate rolling correlation vs BTC
        4. Calculate Kelly fraction
        5. Take the LAST valid (non-NaN) value of rolling series as the "current" metric

    data_days = count of non-NaN values in the RETURNS series (not close prices).
    With 60 close prices, pct_change produces 59 returns (first is NaN).

    Returns DataFrame with columns:
        symbol, beta, correlation, kelly_fraction, data_days
    """
```

#### Mathematical Formulas (Exact Implementations)

**Daily Returns (Simple):**
```
R_t = (P_t - P_{t-1}) / P_{t-1}
```
```python
returns = df["close"].pct_change()
```

**30-Day Rolling Pearson Correlation:**
```
r = Σ[(Xᵢ - X̄)(Yᵢ - Ȳ)] / √[Σ(Xᵢ - X̄)² · Σ(Yᵢ - Ȳ)²]
```
```python
corr = asset_returns.rolling(window=30, min_periods=20).corr(btc_returns)
```

**Rolling Beta:**
```
β = Cov(R_asset, R_btc) / Var(R_btc)
```
```python
cov = asset_returns.rolling(window, min_periods=min_periods).cov(btc_returns)
var = btc_returns.rolling(window, min_periods=min_periods).var()
var = var.replace(0, np.nan)  # Guard: division by zero → NaN, not inf
beta = cov / var
```

**Half-Kelly Criterion:**
```
f* = (b·p - q) / b
f_half = f* / 2
position = min(f_half, max_fraction)
```
```python
wins = returns[returns > 0]
losses = returns[returns < 0]
p = len(wins) / len(returns)
q = 1 - p
b = np.mean(wins) / np.abs(np.mean(losses))
f_star = (b * p - q) / b
f_half = f_star / 2
return min(f_half, max_fraction) if f_star > 0 else 0.0
```

#### Edge Cases — Exhaustive List

| Case | Input | Expected Output | Implementation |
|------|-------|-----------------|----------------|
| Perfect 2x leverage | `asset = 2 * btc` | Beta=2.0, Corr=1.0 | Standard formula; verified by test |
| Perfect inverse | `asset = -1 * btc` | Beta=-1.0, Corr=-1.0 | Standard formula; verified by test |
| BTC flat (zero variance) | All btc_returns = 0 | Beta=NaN | `var.replace(0, np.nan)` guard |
| Asset flat (zero variance) | All asset_returns = 0 | Beta=0.0, Corr=NaN | Cov=0 → Beta=0; Corr undefined |
| Insufficient data (<20 days) | 15 data points, window=30 | Beta=NaN, Corr=NaN | `min_periods=20` → all NaN |
| Partial data (25 days) | 25 data points, window=30 | Beta=computed, Corr=computed | `min_periods=20` → valid from day 20 |
| NaN in middle of series | Gap of 4+ days | NaN at gap; valid elsewhere | `rolling()` skips NaN pairs |
| Extreme outlier (flash crash) | Single -90% return | Beta distorted | Documented, not clipped (preserve real data) |
| No winning trades (Kelly) | All returns negative | Kelly=0.0 | `f_star <= 0` guard |
| No losing trades (Kelly) | All returns positive | Kelly=0.0 | `len(losses)==0` guard → 0.0 (can't estimate loss size) |

---

### 4.3 `screener_engine.py`

#### Public Interface

```python
async def run_screen(
    exchange_id: str = "binance",
    min_mcap: float = 20_000_000,
    max_mcap: float = 150_000_000,
    min_beta: float = 1.5,
    min_correlation: float = 0.7,
    min_volume: float = 1_000_000,
    min_supply_pct: float = 0.70,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    End-to-end screening pipeline.

    Steps:
        1. fetch_universe() → filter by MC, exclude stables/wrapped
        2. map_coingecko_to_ccxt() → validate symbols on exchange
        3. fetch_historical_data() → 60-day OHLCV + BTC baseline
        4. compute_all_metrics() → Beta, Correlation, Kelly per coin
        5. merge_metadata() → JOIN CoinGecko metadata (name, market_cap,
           volume_24h, circulating_supply, total_supply) with math engine
           output (beta, correlation, kelly_fraction, data_days) on symbol.
           Compute circulating_pct = circulating_supply / total_supply.
           GUARD: if total_supply is null/0 or circulating_supply is null,
           set circulating_pct = NaN (not crash).
        6. Apply final sieve:
            - data_days >= 20 (first, cheapest check)
            - Beta > min_beta
            - Correlation > min_correlation
            - 24h Volume > min_volume
            - circulating_pct > min_supply_pct ONLY if not NaN
        7. Sort by Beta descending

    Returns DataFrame with columns:
        symbol, name, market_cap, volume_24h, beta, correlation,
        kelly_fraction, circulating_pct, data_days
    """
```

#### Filter Pipeline (Ordered)

The filters are applied in this specific order to minimize expensive operations:

```
Step 1: Market Cap filter         → ~1000 coins → ~100-200 survivors
Step 2: Stablecoin/Wrapped filter → ~100-200 → ~80-180 survivors
Step 3: Symbol mapping to exchange → ~80-180 → ~40-100 survivors (many not on Binance)
Step 4: OHLCV fetch               → ~40-100 symbols (most expensive step)
Step 5: Data sufficiency (≥20 days)→ ~40-100 → ~35-90 survivors
Step 6: Math filters (Beta, Corr) → ~35-90 → ~5-20 survivors
Step 7: Volume filter             → ~5-20 → ~3-15 survivors
Step 8: Supply check              → ~3-15 → ~3-15 (rarely filters, data often null)
```

---

### 4.4 `dashboard.py`

#### Public Interface

```python
def render_results(
    results: pd.DataFrame,
    console: Console | None = None,
) -> None:
    """
    Render screening results as a color-coded rich table.

    Columns:
        Rank | Symbol | Name | Market Cap | 24h Volume |
        Beta | Correlation | Kelly % | Circ. Supply %

    Color rules:
        Beta:        > 2.0 → bold green, 1.5-2.0 → yellow
        Correlation: > 0.85 → bold green, 0.7-0.85 → yellow
        Kelly:       > 0.15 → bold green, > 0 → yellow, 0 → dim
        Volume:      dim white (informational)
        Market Cap:  dim white (informational)
    """

def render_no_results(console: Console | None = None) -> None:
    """Display a message when no coins pass the screen."""
```

#### Dry-Run Mock Data

When `--dry-run` is passed, the CLI constructs a hardcoded DataFrame:

```python
DRY_RUN_DATA = pd.DataFrame([
    {"symbol": "RENDER/USDT", "name": "Render", "market_cap": 45_000_000,
     "volume_24h": 8_500_000, "beta": 2.34, "correlation": 0.89,
     "kelly_fraction": 0.12, "circulating_pct": 0.78, "data_days": 60},
    {"symbol": "FET/USDT", "name": "Fetch.ai", "market_cap": 120_000_000,
     "volume_24h": 15_000_000, "beta": 1.87, "correlation": 0.82,
     "kelly_fraction": 0.09, "circulating_pct": 0.85, "data_days": 60},
    {"symbol": "RNDR/USDT", "name": "Example Coin", "market_cap": 30_000_000,
     "volume_24h": 2_100_000, "beta": 1.62, "correlation": 0.74,
     "kelly_fraction": 0.05, "circulating_pct": 0.91, "data_days": 45},
])
```

---

### 4.5 `cli.py`

#### Arguments

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--dry-run` | bool | False | Use mock data, no API calls |
| `--exchange` | str | "binance" | ccxt exchange ID |
| `--min-mcap` | float | 20000000 | Minimum market cap ($) |
| `--max-mcap` | float | 150000000 | Maximum market cap ($) |
| `--min-beta` | float | 1.5 | Minimum Beta threshold |
| `--min-corr` | float | 0.7 | Minimum correlation threshold |
| `--min-volume` | float | 1000000 | Minimum 24h volume ($) |
| `--no-cache` | bool | False | Force fresh API calls |

#### Entry Points

```python
# After: pip install -e ".[dev]"
# Run:   python -m quant_scanner --dry-run
```

The `__main__.py` contains exactly:
```python
from quant_scanner.cli import main
main()
```

`cli.main()` is a **sync** function that:
1. Calls `logging.basicConfig(level=logging.INFO)` first
2. Parses args
3. If `--dry-run`: builds mock DataFrame, calls `render_results()`, returns (no async needed)
4. If live: calls `asyncio.run(async_main(args))`

#### Environment & Logging Setup

- `ingestion_engine.py` calls `load_dotenv()` at module level and defines
  `logger = logging.getLogger(__name__)`
- `cli.main()` calls `logging.basicConfig(level=logging.INFO)` so all
  module-level loggers are active
- All "skip symbol" / "cache hit" / "dropped coin" messages use `logger.warning()`
  or `logger.info()`

---

## 5. Data Flow

### Single Scan — Complete Sequence Diagram

```
User runs: python -m quant_scanner --exchange binance
    │
    ▼
cli.py: parse_args() → args.exchange="binance", args.dry_run=False
    │
    ▼
cli.py: asyncio.run(async_main(args))
    │
    ▼
screener_engine.py: run_screen(exchange_id="binance")
    │
    ├──► ingestion_engine.py: fetch_universe()
    │       │
    │       ├── Check cache/coingecko_universe.json
    │       │   └── Cache hit + fresh? → load from disk
    │       │   └── Cache miss or stale? → aiohttp GET /coins/markets (4 pages)
    │       │                              └── Save to cache
    │       │
    │       ├── Filter: $20M < market_cap < $150M
    │       ├── Exclude: symbol in STABLECOINS or WRAPPED_TOKENS
    │       └── Return: list[dict] (~100-200 coins)
    │
    ├──► ingestion_engine.py: map_coingecko_to_ccxt(coins, exchange)
    │       │
    │       ├── exchange.load_markets() (ccxt caches this internally)
    │       ├── For each coin: "{symbol.upper()}/USDT" → check in markets
    │       ├── Deduplicate: if 2 coins → same pair, keep higher MC rank
    │       └── Return: list[dict] with added "ccxt_symbol" key (~40-100 coins)
    │
    ├──► ingestion_engine.py: fetch_historical_data(symbols)
    │       │
    │       ├── Always fetch BTC/USDT first (the baseline)
    │       ├── For each symbol: ccxt fetch_ohlcv(symbol, "1d", days=60)
    │       │   └── Semaphore(10) limits concurrency
    │       │   └── enableRateLimit=True handles exchange throttling
    │       │   └── Exponential backoff on 429 errors
    │       │
    │       ├── Convert each to DataFrame with DatetimeIndex
    │       ├── Reindex all to BTC's DatetimeIndex
    │       ├── Forward-fill NaN gaps (limit=3)
    │       └── Return: dict[str, DataFrame]
    │
    ├──► math_engine.py: compute_all_metrics(ohlcv_data)
    │       │
    │       ├── btc_returns = btc_df["close"].pct_change()
    │       ├── For each altcoin:
    │       │   ├── asset_returns = alt_df["close"].pct_change()
    │       │   ├── beta = rolling_cov / rolling_var (window=30, min_periods=20)
    │       │   ├── corr = rolling_corr (window=30, min_periods=20)
    │       │   ├── kelly = half_kelly(asset_returns)
    │       │   └── data_days = count of non-NaN return values
    │       └── Return: DataFrame[symbol, beta, correlation, kelly_fraction, data_days]
    │
    ├──► screener_engine.py: merge_metadata()
    │       │
    │       ├── JOIN CoinGecko data (name, market_cap, volume_24h, supply)
    │       │   with math engine output on symbol
    │       ├── circulating_pct = circulating_supply / total_supply
    │       │   (NaN if either is null/zero — NOT crash)
    │       └── Return: merged DataFrame
    │
    ├──► screener_engine.py: apply_filters()
    │       │
    │       ├── data_days >= 20
    │       ├── beta > 1.5
    │       ├── correlation > 0.7
    │       ├── volume_24h > 1_000_000
    │       ├── circulating_pct > 0.70 (skip if NaN)
    │       └── Sort by beta descending
    │
    └──► dashboard.py: render_results(filtered_df)
            │
            └── Print rich.table.Table to terminal
```

---

## 6. Mathematical Specifications

### 6.1 Daily Simple Returns

```
R_t = (P_t - P_{t-1}) / P_{t-1}
```

Implementation: `df["close"].pct_change()`

Note: We use simple returns, not log returns, because:
- Simple returns aggregate correctly across assets in a portfolio
- For daily crypto moves (<10%), the difference is negligible
- Simple returns are easier to interpret (a 5% return is literally 5%)

### 6.2 Rolling Pearson Correlation (30-day)

```
r_xy = Σᵢ[(Xᵢ - X̄)(Yᵢ - Ȳ)] / √[Σᵢ(Xᵢ - X̄)² · Σᵢ(Yᵢ - Ȳ)²]
```

Equivalently: `r = Cov(X,Y) / (σ_X · σ_Y)`

Implementation:
```python
asset_returns.rolling(window=30, min_periods=20).corr(btc_returns)
```

Range: [-1.0, 1.0]
- +1.0 = perfect positive correlation (moves exactly with BTC)
- 0.0 = no linear relationship
- -1.0 = perfect negative correlation (moves exactly opposite to BTC)

### 6.3 Rolling Beta (30-day)

```
β = Cov(R_asset, R_btc) / Var(R_btc)
```

Implementation:
```python
cov = asset_returns.rolling(30, min_periods=20).cov(btc_returns)
var = btc_returns.rolling(30, min_periods=20).var()
var = var.replace(0, np.nan)
beta = cov / var
```

Interpretation:
- β = 1.0 → asset moves 1:1 with BTC
- β = 2.0 → asset moves 2x as much as BTC
- β = 0.5 → asset moves half as much as BTC
- β = -1.0 → asset moves opposite to BTC with same magnitude

Relationship to correlation: `β = r · (σ_asset / σ_btc)`

### 6.4 Half-Kelly Position Sizing

Full Kelly:
```
f* = (b·p - q) / b
```

Where:
- `b` = average win / average loss (the "odds")
- `p` = probability of a winning trade
- `q` = 1 - p

Half-Kelly (what we use):
```
f = min(f*/2, max_fraction)
```

Why half-Kelly:
- Full Kelly assumes perfect knowledge of p and b (we have estimates)
- Half-Kelly achieves 75% of growth rate with significantly lower drawdowns
- Capped at 25% to prevent catastrophic concentration

### 6.5 Circulating Supply Ratio

```
supply_pct = circulating_supply / total_supply
```

**Guards:** Both `circulating_supply` and `total_supply` can be null from
CoinGecko. Additionally, `total_supply` can be 0 for some tokens.
If EITHER field is null OR `total_supply == 0`, set `supply_pct = NaN`.
The screener skips the supply check when `supply_pct` is NaN.

Coins with supply_pct < 0.70 have significant unreleased tokens that could
cause dilution-driven sell pressure. This is a red flag, not a disqualifier.

---

## 7. API Contracts & Rate Limits

### 7.1 CoinGecko (Free/Demo Tier)

**Endpoint:** `GET https://api.coingecko.com/api/v3/coins/markets`

| Parameter | Value |
|-----------|-------|
| `vs_currency` | `usd` |
| `order` | `market_cap_desc` |
| `per_page` | `250` |
| `page` | `1` through `4` |
| `sparkline` | `false` |

**Response fields used:**
```json
{
  "id": "render-token",
  "symbol": "rndr",
  "name": "Render",
  "market_cap": 45000000,
  "fully_diluted_valuation": 89000000,
  "total_volume": 8500000,
  "circulating_supply": 365000000,
  "total_supply": 530000000,
  "market_cap_rank": 85
}
```

**Rate limits:**
| Tier | Limit | Monthly Cap |
|------|-------|-------------|
| Public (no key) | 5-15 req/min (unstable) | None stated |
| Demo (free key) | 30 req/min (stable) | 10,000/month |

**Our usage:** 4 calls per scan (4 pages). With caching, <10 calls/day.

**Auth:** API key passed as `x-cg-demo-api-key` header (from .env) or no key
for public tier.

### 7.2 CCXT / Binance

**Method:** `exchange.fetch_ohlcv(symbol, timeframe, since, limit)`

| Parameter | Value |
|-----------|-------|
| `symbol` | e.g., `"RENDER/USDT"` |
| `timeframe` | `"1d"` |
| `since` | 60 days ago in ms: `int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000)` — MUST use UTC, not local time |
| `limit` | `60` (at most 60 daily candles) |

**Response:** `[[timestamp_ms, open, high, low, close, volume], ...]`

**Rate limits (Binance):**
- 6,000 weight/min per IP
- `/api/v3/klines` costs weight 2 per call
- Theoretical max: 3,000 calls/min (but shared budget)
- With `enableRateLimit=True`, ccxt auto-throttles

**Our usage:** ~50-100 calls per scan (one per filtered symbol + BTC).
With Semaphore(10), completes in 2-5 minutes.

### 7.3 Error Handling Contract

| Error | Source | Response |
|-------|--------|----------|
| HTTP 429 | CoinGecko or Exchange | Exponential backoff: `2^attempt + random(0,1)` seconds, max 5 retries |
| HTTP 5xx | Any | Same backoff strategy |
| `ccxt.BadSymbol` | Exchange | Log warning, skip symbol, continue |
| `ccxt.NetworkError` | Exchange | Backoff + retry |
| `ccxt.ExchangeNotAvailable` | Exchange | Log error, abort scan |
| Empty OHLCV response | Exchange | Skip symbol (likely delisted or too new) |

---

## 8. Known Landmines & Mitigations

### 8.1 CoinGecko Free Tier Budget Burn

**Risk:** Repeated test runs during development consume the 10,000/month cap.

**Mitigation:**
- All tests use mocked responses (mandatory in acceptance criteria)
- Production code implements 12-hour disk cache
- `--dry-run` never touches the network
- Cache is checked BEFORE any API call

### 8.2 Symbol Mapping Collisions

**Risk:** CoinGecko has 3 different coins with symbol "AI". CCXT only has one
"AI/USDT" on Binance.

**Mitigation:**
- Deduplicate by `market_cap_rank`: lowest rank number (= highest cap) wins
- Log warnings for collisions so the user knows

### 8.3 Timestamp Misalignment

**Risk:** BTC has 60 candles, altcoin has 57. Pandas `rolling().cov()` silently
computes wrong values if DataFrames have different indices.

**Mitigation:**
- All DataFrames reindexed to BTC's DatetimeIndex
- Forward-fill gaps up to 3 days
- Gaps > 3 days left as NaN (math engine's `min_periods` handles it)

### 8.4 Exchange Listings Change

**Risk:** A coin passes CoinGecko filters but was delisted from Binance yesterday.

**Mitigation:**
- `exchange.load_markets()` gives current listings
- `ccxt.BadSymbol` exception is caught and the coin is skipped
- Empty OHLCV responses are detected and the coin is skipped

### 8.5 Windows asyncio Event Loop

**Risk:** Older Python on Windows used `ProactorEventLoop` which had issues with
some async libraries.

**Mitigation:** Python 3.11+ on Windows works fine with `asyncio.run()`.
No special event loop policy needed.

### 8.6 Division by Zero in Beta Calculation

**Risk:** If BTC is perfectly flat for 30 days (Var = 0), Beta = Cov/0 = inf.

**Mitigation:** Explicit guard: `var.replace(0, np.nan)` before division.
In practice, BTC is never flat for 30 days, but the guard is mandatory.

### 8.7 Coins with Identical Returns

**Risk:** If a coin has zero variance (same price for 30 days), correlation is
mathematically undefined (0/0).

**Mitigation:** Pandas `rolling().corr()` correctly returns NaN in this case.
The coin gets filtered out by the `data_days >= 20` check or the correlation
threshold.

### 8.8 CoinGecko Null `market_cap` Field

**Risk:** CoinGecko returns `"market_cap": null` for some obscure coins.
`market_cap < 20_000_000` raises `TypeError` when comparing None to int.

**Mitigation:** Filter out coins where `market_cap is None` BEFORE the
numeric comparison. This is explicit in the QUANT-002 acceptance criteria
and must be tested.

### 8.9 Unclosed ccxt Async Exchange Session

**Risk:** `ccxt.async_support` creates an internal aiohttp session. If
`await exchange.close()` is never called, Python throws
`ResourceWarning: unclosed client session` and may leak connections.

**Mitigation:** Wrap all exchange usage in `try/finally`:
```python
exchange = ccxt.async_support.binance({"enableRateLimit": True})
try:
    # ... fetch OHLCV ...
finally:
    await exchange.close()
```
This is explicit in the QUANT-003 acceptance criteria and tested.

### 8.10 Circulating/Total Supply Both Null

**Risk:** CoinGecko can return null for both `circulating_supply` and
`total_supply`. Computing `null / null` or `X / 0` will crash.

**Mitigation:** If either field is null or `total_supply == 0`, set
`circulating_pct = NaN`. The screener's supply filter skips NaN values.

### 8.11 Editable Install Required for src/ Layout

**Risk:** With `src/` layout, `import quant_scanner` only works after
`pip install -e .`. If the Builder only runs `pip install -r requirements.txt`,
every subsequent import and pytest gate will fail with `ModuleNotFoundError`.

**Mitigation:** QUANT-001 explicitly requires `pip install -e ".[dev]"` and
verifies importability with `python -c "import quant_scanner"`.

### 8.12 Cache Directory Does Not Exist on First Run

**Risk:** The `cache/` and `cache/ohlcv/` directories don't exist on a fresh
clone. Writing `cache/coingecko_universe.json` crashes with `FileNotFoundError`.

**Mitigation:** Every cache write is preceded by
`os.makedirs(os.path.dirname(path), exist_ok=True)`. This is explicit in the
QUANT-002 and QUANT-003 acceptance criteria.

---

## 9. Testing Strategy

### Philosophy

Every test uses **mock data only**. No test ever hits the network. This
guarantees:
1. Tests run in <5 seconds total
2. Tests never fail due to API flakiness
3. Tests are deterministic and reproducible
4. No API budget is consumed during development

### Test Matrix

| Test File | Test Function | What It Proves |
|-----------|--------------|----------------|
| `test_ingestion.py` | `test_market_cap_filter` | Coins outside $20M-$150M are excluded; null market_cap excluded |
| `test_ingestion.py` | `test_stablecoin_exclusion` | USDT, USDC, DAI etc. are excluded |
| `test_ingestion.py` | `test_wrapped_token_exclusion` | WBTC, WETH etc. are excluded |
| `test_ingestion.py` | `test_ohlcv_dataframe_format` | Returns DataFrame with correct columns and DatetimeIndex |
| `test_ingestion.py` | `test_timestamp_alignment` | All altcoin DFs aligned to BTC's index with ffill |
| `test_ingestion.py` | `test_symbol_mapping` | CoinGecko symbols correctly mapped to CCXT format |
| `test_ingestion.py` | `test_symbol_deduplication` | When 2 CG coins → same pair, higher MC rank wins |
| `test_ingestion.py` | `test_cache_saves_and_loads` | Cache file written on fetch, loaded on subsequent call |
| `test_ingestion.py` | `test_exchange_close_called` | exchange.close() was awaited after fetch |
| `test_math.py` | `test_beta_2x_leverage` | If asset = 2*BTC, Beta == 2.0 |
| `test_math.py` | `test_beta_inverse` | If asset = -1*BTC, Beta == -1.0 |
| `test_math.py` | `test_correlation_perfect_positive` | If asset = 2*BTC, Corr == 1.0 |
| `test_math.py` | `test_correlation_perfect_negative` | If asset = -1*BTC, Corr == -1.0 |
| `test_math.py` | `test_zero_variance_btc` | Flat BTC → Beta is NaN, not inf |
| `test_math.py` | `test_insufficient_data` | <20 data points → all NaN |
| `test_math.py` | `test_kelly_positive_edge` | Winning system → Kelly > 0 |
| `test_math.py` | `test_kelly_no_edge` | Losing system → Kelly == 0 |
| `test_math.py` | `test_kelly_no_losses` | All positive returns → Kelly == 0 |
| `test_math.py` | `test_kelly_cap` | Kelly never exceeds max_fraction |
| `test_screener.py` | `test_full_pipeline_mock` | End-to-end with mocked ingestion → correct filters applied |
| `test_screener.py` | `test_beta_filter` | Coins with Beta < 1.5 excluded |
| `test_screener.py` | `test_correlation_filter` | Coins with Corr < 0.7 excluded |
| `test_screener.py` | `test_volume_filter` | Coins with Vol < $1M excluded |
| `test_screener.py` | `test_insufficient_data_excluded` | Coins with <20 days excluded |
| `test_screener.py` | `test_supply_filter_with_null` | Null/NaN supply → coin NOT excluded |
| `test_screener.py` | `test_supply_zero_total` | total_supply=0 → circulating_pct=NaN, not crash |
| `test_screener.py` | `test_results_sorted_by_beta` | Output sorted by Beta descending |
| `test_cli.py` | `test_dry_run_flag` | `--dry-run` sets args.dry_run = True |
| `test_cli.py` | `test_default_args` | Defaults are correct |
| `test_cli.py` | `test_dry_run_produces_output` | `--dry-run` prints a table without error |

### Mock Data Fixtures (conftest.py)

```python
# Key fixtures that all tests share:

@pytest.fixture
def mock_coingecko_response() -> list[dict]:
    """Realistic CoinGecko /coins/markets page with 10 coins spanning
    various market caps, including stablecoins, wrapped tokens,
    AND at least one coin with market_cap=None (null)."""

@pytest.fixture
def mock_btc_ohlcv() -> list[list]:
    """60 days of BTC/USDT daily candles with realistic price movement."""

@pytest.fixture
def mock_alt_ohlcv_2x_btc() -> list[list]:
    """60 days where the alt moves exactly 2x BTC. For Beta=2.0 test."""

@pytest.fixture
def mock_alt_ohlcv_inverse_btc() -> list[list]:
    """60 days where the alt moves exactly -1x BTC. For Corr=-1.0 test."""

@pytest.fixture
def deterministic_btc_returns() -> pd.Series:
    """Seeded np.random BTC returns for reproducible math tests."""
```

---

## 10. Build Sequence (prd.json)

This is the exact story sequence. Each story's `gateCmd` must pass before the
next story begins. The Builder agent is forbidden from proceeding on gate failure.

**See `.claude/prd.json` for the canonical, hardened version.**

The prd.json is the single source of truth for story definitions and gate commands.
Do NOT duplicate it here — always read from the file directly.

Key differences from earlier drafts (patches applied):
- QUANT-001: Requires `pip install -e ".[dev]"` (editable install) and importability check
- QUANT-002: Null `market_cap` guard added; `os.makedirs` for cache; `load_dotenv()` at module level
- QUANT-003: `await exchange.close()` in try/finally; UTC timestamps; `test_exchange_close_called`
- QUANT-004: Kelly guard for "no losses" case; `data_days` = count of non-NaN returns
- QUANT-005: `merge_metadata()` step added; `total_supply=0` → NaN guard; `test_supply_zero_total`
- QUANT-006: gateCmd fixed to `python -m quant_scanner --dry-run` (NOT `python -m src.quant_scanner.cli`)
- All gateCmds prefixed with `cd /f/TradingScanner && .venv/Scripts/python -m pytest`

---

## 11. Acceptance Gate Details

### Gate Failure Protocol

When a `gateCmd` fails:

1. The Builder reads the **full pytest traceback**
2. The Builder identifies the **exact assertion** that failed
3. The Builder fixes **only the failing code** (no refactoring unrelated code)
4. The Builder re-runs the `gateCmd`
5. Maximum 3 retry attempts per gate before escalating to the user

### Gate Pass Criteria

A gate is considered passed when:
- The `gateCmd` exits with code 0
- All specified tests show `PASSED`
- No warnings that indicate silent data corruption (e.g., `RuntimeWarning: divide by zero`)

### Story Dependencies

```
QUANT-001 (scaffold)
    └── QUANT-002 (universe fetch + cache)
        └── QUANT-003 (OHLCV + symbol mapping)
            └── QUANT-004 (math engine) ← INDEPENDENT of 002/003 data structures
            └── QUANT-005 (screener) ← DEPENDS on 003 + 004
                └── QUANT-006 (CLI + dashboard)
```

Note: QUANT-004 (math engine) only depends on QUANT-001 (for pytest config).
It does NOT depend on 002 or 003 because it takes raw DataFrames/Series as
input. This means the math engine can be developed and tested in isolation.

---

## 12. Out of Scope

These are explicitly NOT part of this build session. They are documented here
to prevent scope creep.

| Feature | Why Out of Scope | Future Agent |
|---------|------------------|--------------|
| Trade execution | Capital risk; requires exchange API keys with trading permissions | Separate project |
| Real-time WebSocket streaming | Requires persistent connections, reconnection logic | Agent 1 enhancement |
| On-chain analysis (whale tracking, MVRV, exchange flows) | Requires blockchain RPC (Alchemy/Infura), separate infrastructure | Agent 3: On-Chain Sleuth |
| NLP sentiment analysis | Requires Twitter API, Discord bots, LLM pipeline | Agent 4: Narrative & NLP |
| Smart contract auditing | Requires Etherscan API, bytecode analysis | Agent 5: Risk Manager |
| Database persistence | Over-engineering for a one-shot scanner | Future if needed |
| Web UI / dashboard | Terminal output is sufficient for v1 | Future enhancement |
| Backtesting engine | Different problem domain, separate project | Future project |
| Options/derivatives data | Requires different API endpoints, complex modeling | Agent 2 enhancement |
| Multi-exchange aggregation | Adds complexity; Binance alone has sufficient coverage | Future enhancement |
| Hidden Markov Models for regime detection | Research-heavy, requires separate validation | Future enhancement |

---

## 13. Future Roadmap

### Phase 2: Enhanced Data (Post-MVP)

- Add KuCoin and Bybit as additional exchanges
- Add DefiLlama TVL data as a fundamental filter
- Add GitHub developer activity via GitHub API
- Implement vesting schedule tracking

### Phase 3: Agent Architecture (The 5-Agent Vision)

```
Agent 1: Data Harvester     ← THIS BUILD (v1)
Agent 2: Correlation Engine ← THIS BUILD (v1)
Agent 3: On-Chain Sleuth    ← Phase 2
Agent 4: Narrative & NLP    ← Phase 3
Agent 5: Risk Manager       ← THIS BUILD (partial: screening only)
```

### Phase 4: Execution Layer

- Paper trading mode (simulated orders)
- Signal-to-Telegram/Discord notifications
- Position sizing automation (Kelly already computed)

---

## Appendix A: Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COINGECKO_API_KEY` | No | None | CoinGecko demo API key for stable 30 req/min |
| `EXCHANGE_ID` | No | `binance` | Default ccxt exchange |

If `COINGECKO_API_KEY` is not set, the system falls back to the public tier
(5-15 req/min, unstable). The system will still work but may hit rate limits
more frequently.

## Appendix B: Performance Expectations

| Operation | Expected Duration | Bottleneck |
|-----------|------------------|------------|
| CoinGecko universe fetch (4 pages) | 2-5 seconds | API rate limit |
| CoinGecko universe from cache | <50ms | Disk I/O |
| exchange.load_markets() | 1-3 seconds | Network |
| OHLCV fetch (50 symbols, Semaphore=10) | 2-4 minutes | Exchange rate limit |
| OHLCV from cache (50 symbols) | <500ms | Disk I/O |
| Math computation (50 symbols) | <1 second | CPU (vectorized pandas) |
| Full scan (no cache) | 3-5 minutes | OHLCV fetching |
| Full scan (cached) | <2 seconds | CPU |
| `--dry-run` | <100ms | Zero I/O |

## Appendix C: Test Execution Time Budget

All tests combined must complete in under 5 seconds. This is enforced by:
- Zero network calls (all mocked)
- Small mock datasets (60 rows max)
- No disk I/O in math tests (in-memory DataFrames)
- Cache tests use `tmp_path` pytest fixture (tmpdir, auto-cleaned)
