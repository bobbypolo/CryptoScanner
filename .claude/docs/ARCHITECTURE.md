# Crypto Quant Alpha Scanner — Architecture Document

> **Classification:** P2 (Competitive IP) for math engine, P3 (Resilience) for API keys

---

## Security Classification

| Component | Classification | Policy |
|-----------|---------------|--------|
| Math Engine (Beta, Correlation, Kelly) | **P2 — Competitive IP** | Core alpha logic; well-tested, no external exposure |
| API Keys (CoinGecko, Exchange) | **P3 — Resilience** | MUST use `os.getenv()` via python-dotenv; NEVER hardcode |
| Cache Files | P1 — Public | Contains only publicly available market data |
| CLI / Dashboard | P1 — Public | Display layer only |

## Architectural Decisions Record (ADR)

### ADR-001: Raw aiohttp over pycoingecko

**Context:** Need HTTP client for CoinGecko API.
**Decision:** Use raw `aiohttp` requests.
**Rationale:** pycoingecko is unmaintained (last release Nov 2024, Snyk: inactive).
The CoinGecko REST API is simple GET requests — a wrapper adds dependency risk
without meaningful abstraction value. Raw aiohttp also enables native async
and custom rate limiting via aiolimiter.

### ADR-002: ccxt built-in rate limiter + Semaphore

**Context:** Fetching OHLCV for 50-100 symbols concurrently.
**Decision:** Three-layer defense: ccxt `enableRateLimit=True` (layer 1),
`asyncio.Semaphore(10)` (layer 2), exponential backoff with jitter (layer 3).
**Rationale:** ccxt's internal rate limiter handles per-exchange throttling.
Semaphore prevents memory blow-up from 100+ concurrent coroutines.
Backoff handles transient 429 errors that slip through.

### ADR-003: Disk cache over database

**Context:** Need to avoid re-fetching data on repeated runs.
**Decision:** Simple JSON files in `cache/` directory with `fetched_at` timestamps.
**Rationale:** No persistence needed between sessions. JSON is human-readable,
debuggable, and requires zero infrastructure. A database would be over-engineering
for a one-shot scanner.

### ADR-004: Simple returns over log returns

**Context:** Need to compute daily returns for Beta/Correlation.
**Decision:** Use simple returns: `(P_t - P_{t-1}) / P_{t-1}` via `pct_change()`.
**Rationale:** Simple returns aggregate correctly across assets in a portfolio
context. For daily crypto moves (<10% typical), the difference from log returns
is negligible. Simple returns are more intuitive to interpret.

### ADR-005: Half-Kelly over full Kelly

**Context:** Need position sizing recommendation.
**Decision:** Output half-Kelly, capped at 25%.
**Rationale:** Full Kelly assumes perfect parameter estimation (we have
estimates from 60 days of data — not perfect). Half-Kelly achieves 75% of the
growth rate with significantly lower max drawdown. The 25% cap prevents
catastrophic concentration.

### ADR-006: argparse over click/typer

**Context:** Need CLI argument parsing for 4-8 flags.
**Decision:** Use stdlib `argparse`.
**Rationale:** Zero additional dependencies. Sufficient for our flag count.
Trivially testable by passing `argv` list to `parse_args()`. Would reconsider
if we needed nested subcommands.

### ADR-007: Forward-fill limit=3 for timestamp alignment

**Context:** Altcoins may have missing daily candles (exchange maintenance, low liquidity).
**Decision:** Forward-fill NaN gaps up to 3 consecutive days.
**Rationale:** 1-2 day gaps are common and benign (weekends for some exchanges,
maintenance windows). Filling >3 days would mask genuine illiquidity, which is a
negative signal. Remaining NaNs after ffill are handled by `min_periods=20` in
the math engine.

### ADR-008: src/ layout over flat layout

**Context:** Project directory structure.
**Decision:** `src/quant_scanner/` package layout.
**Rationale:** PyPA-recommended. Prevents accidental import of local source
instead of installed package. Test isolation is guaranteed — tests always
import the installed package.

## Component Interaction Diagram

```
┌─────────────────────────────────────────────────────────┐
│                        cli.py                            │
│  argparse → async_main() → screener → dashboard          │
└────────────────┬────────────────────────────┬────────────┘
                 │                            │
                 ▼                            ▼
┌────────────────────────────┐  ┌────────────────────────┐
│   screener_engine.py       │  │   dashboard.py          │
│                            │  │                        │
│   run_screen()             │  │   render_results()     │
│   ├─ fetch_universe()      │  │   render_no_results()  │
│   ├─ map_coingecko_to_ccxt │  │                        │
│   ├─ fetch_historical_data │  │   Uses: rich.table     │
│   ├─ compute_all_metrics() │  │         rich.console   │
│   └─ apply_filters()       │  │         rich.text      │
└───────┬──────────┬─────────┘  └────────────────────────┘
        │          │
        ▼          ▼
┌──────────────┐ ┌──────────────────────┐
│ ingestion_   │ │ math_engine.py       │
│ engine.py    │ │                      │
│              │ │ calculate_beta()     │
│ CoinGecko    │ │ calculate_corr()     │
│ ccxt async   │ │ calculate_kelly()    │
│ caching      │ │ compute_all_metrics()│
│ rate limiting│ │                      │
│ symbol map   │ │ Uses: pandas, numpy  │
└──────────────┘ └──────────────────────┘
```

## Error Propagation

```
Exchange 429 → backoff retry (max 5) → if still failing → skip symbol + log warning
CoinGecko 429 → backoff retry (max 5) → if still failing → raise RuntimeError
ccxt.BadSymbol → catch → skip symbol + log warning
Empty OHLCV → skip symbol + log warning
CoinGecko market_cap=null → filter out before numeric comparison (prevent TypeError)
Division by zero (math) → NaN via var.replace(0, np.nan) (never raises)
circulating_supply/total_supply null or 0 → circulating_pct = NaN (never raises)
No coins pass screen → render_no_results() message (never crashes)
ccxt async session → always closed in try/finally (prevent ResourceWarning)
```

## Thread / Async Model

```
Main Thread
└── asyncio.run(async_main())
    ├── aiohttp session (CoinGecko)
    │   └── AsyncLimiter(25, 60) gates requests
    │
    └── ccxt async exchange instance
        └── Semaphore(10) gates concurrent fetches
            ├── fetch_ohlcv(symbol_1) ─┐
            ├── fetch_ohlcv(symbol_2)  ├── up to 10 concurrent
            ├── fetch_ohlcv(symbol_3)  │
            └── ...                   ─┘
```

All I/O is async. The math computation (pandas/numpy) is synchronous but
CPU-bound and completes in <1 second for 100 symbols. No threading is needed.
