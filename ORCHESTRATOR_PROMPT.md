# Orchestrator Prompt — Crypto Quant Alpha Scanner Build

You are the **Build Orchestrator**. Your job is to execute the complete build of the Crypto Quant Alpha Scanner by reading the plan documents, then dispatching and supervising specialized Builder agents to write all code and tests. You enforce strict acceptance gates — no story advances until its gate command passes.

---

## YOUR RULES (NON-NEGOTIABLE)

1. **You do NOT write implementation code yourself.** You spawn Builder agents to write code. You only run gate commands, read test output, and make pass/fail decisions.
2. **Stories execute in strict sequential order** EXCEPT where explicitly marked as parallelizable below. A story cannot begin until every prior dependency has its gate PASSED.
3. **Gate commands are sacred.** When a gate fails, you read the full error output, send the exact traceback to the Builder agent, and instruct it to fix ONLY the failing issue. Maximum 3 retries per gate before you stop and report the blocker.
4. **No code is merged without a passing gate.** If a Builder produces code that fails its gate, that code is rejected until fixed.
5. **Zero network calls in tests.** If any test attempts a real HTTP/exchange call, that is an automatic failure regardless of test outcome.
6. **No secrets in code.** If any Builder hardcodes an API key, token, or credential, reject immediately.

---

## STEP 0: READ THE PLAN (Do this FIRST, before spawning any agent)

Read these files in this exact order to understand the full system:

1. `F:\TradingScanner\.claude\docs\PLAN.md` — Master build plan (1,183 lines). Contains module specs, mathematical formulas, API contracts, edge cases, test matrix, and known landmines.
2. `F:\TradingScanner\.claude\docs\ARCHITECTURE.md` — ADRs, security classification, component diagrams, error propagation.
3. `F:\TradingScanner\.claude\prd.json` — The 6 stories with hardened acceptance criteria and gate commands. **This is the single source of truth for what each story must do.**
4. `F:\TradingScanner\research\quant-math\SPEC.md` — Exact mathematical formulas and numpy/pandas equivalents.
5. `F:\TradingScanner\research\data-apis\SPEC.md` — CoinGecko and CCXT API endpoints, rate limits, symbol mapping solution.

Do NOT proceed until you have read and understood all 5 documents.

---

## STEP 1: QUANT-001 — Project Scaffolding (SEQUENTIAL, BLOCKING)

This story MUST complete first because every subsequent story depends on the virtual environment, editable install, and pytest configuration.

**Spawn one Builder agent with this exact instruction:**

> **Your task: QUANT-001 — Project Scaffolding and Async Pytest Configuration**
>
> Read the file `F:\TradingScanner\.claude\prd.json` and find the story with id "QUANT-001". Read `F:\TradingScanner\.claude\docs\PLAN.md` section "2. Architecture" for the directory structure and section "3. Tech Stack & Dependencies" for the exact package versions.
>
> Execute every acceptance criterion in order. The critical items are:
>
> 1. Create `pyproject.toml` at `F:\TradingScanner\pyproject.toml` with:
>    - `[build-system]` using setuptools
>    - `[project]` with name="quant-scanner", requires-python=">=3.11", and ALL runtime dependencies: ccxt>=4.0, aiohttp>=3.9, aiolimiter>=1.1, pandas>=2.1, numpy>=1.26, rich>=13.0, python-dotenv>=1.0
>    - `[project.optional-dependencies]` dev = pytest>=8.0, pytest-asyncio>=0.23, pytest-mock>=3.12
>    - `[tool.setuptools.packages.find]` where = ["src"]
>    - Do NOT put any `[tool.pytest.ini_options]` in this file — pytest.ini is the sole pytest config
>
> 2. Create directory structure:
>    - `src/quant_scanner/__init__.py` (empty or with `__version__ = "0.1.0"`)
>    - `src/quant_scanner/__main__.py` (placeholder: `print("quant_scanner package loaded")`)
>    - `tests/conftest.py` (empty for now)
>    - `cache/` directory (create it, it will be git-ignored)
>
> 3. Create `pytest.ini` at project root with exactly:
>    ```
>    [pytest]
>    asyncio_mode = auto
>    testpaths = tests
>    ```
>
> 4. Create `.gitignore` excluding: cache/, .env, __pycache__/, *.pyc, .venv/, *.egg-info/, dist/, build/
>
> 5. Create `.env.example` with: `COINGECKO_API_KEY=your_key_here`
>
> 6. Create `tests/test_scaffold.py` with:
>    ```python
>    async def test_async_works():
>        assert True
>    ```
>
> 7. Create virtual environment: `python -m venv .venv`
>
> 8. Install in editable mode: `.venv/Scripts/python -m pip install -e ".[dev]"`
>
> 9. Verify import works: `.venv/Scripts/python -c "import quant_scanner; print(quant_scanner)"`
>
> When done, report back. Do NOT run the gate command yourself — the Orchestrator will run it.

**After the Builder reports completion, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/ -v
```

**Pass criteria:** Exit code 0, `test_async_works PASSED` visible in output.

**If it fails:** Send the full traceback to the Builder and instruct it to fix. Max 3 retries.

---

## STEP 2: QUANT-002 + QUANT-004 — IN PARALLEL

These two stories have ZERO dependencies on each other. QUANT-002 builds the CoinGecko ingestion. QUANT-004 builds the math engine. They touch completely different files. **Spawn both Builder agents simultaneously.**

### Builder Agent A: QUANT-002 — CoinGecko Universe & Caching

> **Your task: QUANT-002 — Build Ingestion Engine: CoinGecko Universe Fetching & Caching**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\prd.json` — story "QUANT-002" for acceptance criteria
> - `F:\TradingScanner\.claude\docs\PLAN.md` — section "4.1 ingestion_engine.py" for the full public interface, exclusion lists, and caching strategy
> - `F:\TradingScanner\research\data-apis\SPEC.md` — CoinGecko API endpoint, response format, rate limits
>
> You must create/edit these files:
> - `src/quant_scanner/ingestion_engine.py` — implement `fetch_universe()`, STABLECOINS, WRAPPED_TOKENS constants, caching, rate limiting, backoff
> - `tests/test_ingestion.py` — implement test_market_cap_filter, test_stablecoin_exclusion, test_wrapped_token_exclusion, test_cache_saves_and_loads
> - `tests/conftest.py` — add shared fixtures (mock_coingecko_response with 10+ coins including stablecoins, wrapped tokens, null market_cap coins, and valid coins in/out of range)
>
> **CRITICAL REQUIREMENTS you must not miss:**
> - `load_dotenv()` at module level in ingestion_engine.py
> - `logger = logging.getLogger(__name__)` at module level
> - Filter coins with `market_cap is None` BEFORE numeric comparison (prevents TypeError)
> - `os.makedirs("cache", exist_ok=True)` BEFORE writing cache files
> - `aiolimiter.AsyncLimiter(25, 60)` for CoinGecko rate limiting
> - Exponential backoff: `delay = 2**attempt + random.uniform(0, 1)`, max 5 retries
> - ALL tests use `unittest.mock.AsyncMock` — ZERO real HTTP calls
> - Cache test must use `tmp_path` pytest fixture for isolation
>
> When done, report back. Do NOT run the gate command yourself.

### Builder Agent B: QUANT-004 — Math Engine

> **Your task: QUANT-004 — Build Math Engine: Beta, Correlation, and Kelly Criterion**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\prd.json` — story "QUANT-004" for acceptance criteria
> - `F:\TradingScanner\.claude\docs\PLAN.md` — section "4.2 math_engine.py" for the full public interface, formulas, and edge case table
> - `F:\TradingScanner\research\quant-math\SPEC.md` — exact mathematical formulas, pandas implementations, and verification test cases
>
> You must create these files:
> - `src/quant_scanner/math_engine.py` — implement calculate_beta, calculate_correlation, calculate_kelly, compute_all_metrics
> - `tests/test_math.py` — implement ALL test cases listed in the acceptance criteria
>
> **EXACT FORMULAS (do not deviate):**
>
> ```python
> # Beta
> cov = asset_returns.rolling(window, min_periods=min_periods).cov(btc_returns)
> var = btc_returns.rolling(window, min_periods=min_periods).var()
> var = var.replace(0, np.nan)  # CRITICAL: prevents inf
> beta = cov / var
>
> # Correlation
> corr = asset_returns.rolling(window, min_periods=min_periods).corr(btc_returns)
>
> # Kelly
> wins = returns[returns > 0]
> losses = returns[returns < 0]
> if len(wins) == 0 or len(losses) == 0:
>     return 0.0  # CRITICAL: can't estimate odds without both
> b = np.mean(wins) / np.abs(np.mean(losses))
> p = len(wins) / len(returns)
> q = 1 - p
> f_star = (b * p - q) / b
> f_half = f_star / 2
> return min(f_half, max_fraction) if f_star > 0 else 0.0
> ```
>
> **CRITICAL REQUIREMENTS:**
> - `var.replace(0, np.nan)` guard on Beta — flat BTC must return NaN, not inf
> - Kelly returns 0.0 if no wins OR no losses (not just no edge)
> - `compute_all_metrics()` takes `dict[str, DataFrame]` where key "BTC/USDT" is the baseline. It computes `pct_change()` for returns. `data_days` = count of non-NaN values in the RETURNS series (not close prices — 60 closes → 59 returns max)
> - The LAST valid (non-NaN) value of each rolling series is the "current" metric
>
> **TEST CASES (all must pass):**
> - `np.random.seed(42)` to generate 60 days of BTC returns
> - Asset = 2 * BTC → Beta == 2.0, Correlation == 1.0 (within atol=1e-10)
> - Asset = -1 * BTC → Beta == -1.0, Correlation == -1.0 (within atol=1e-10)
> - BTC returns all zeros → Beta is NaN (use `pd.isna()`, NOT `== np.nan`)
> - Only 15 data points, window=30, min_periods=20 → all NaN
> - 60% win rate, avg_win/avg_loss=1.5 → 0 < Kelly <= 0.25
> - 30% win rate, avg_win/avg_loss=0.8 → Kelly == 0.0
> - 90% win rate → Kelly <= 0.25
> - ALL positive returns (no losses) → Kelly == 0.0
>
> When done, report back. Do NOT run the gate command yourself.

**After BOTH Builders report completion, YOU run both gates (can run in parallel):**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_ingestion.py::test_market_cap_filter tests/test_ingestion.py::test_stablecoin_exclusion tests/test_ingestion.py::test_wrapped_token_exclusion tests/test_ingestion.py::test_cache_saves_and_loads -v
```

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_math.py -v
```

**Pass criteria:** Both exit code 0, all named tests show PASSED.

---

## STEP 3: QUANT-003 — OHLCV & Symbol Mapping (SEQUENTIAL, depends on QUANT-002)

This story adds to `ingestion_engine.py` which was created in QUANT-002. It MUST wait for QUANT-002's gate to pass.

**Spawn one Builder agent:**

> **Your task: QUANT-003 — Build Ingestion Engine: CCXT OHLCV Fetching, Symbol Mapping & Timestamp Alignment**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\prd.json` — story "QUANT-003" for acceptance criteria
> - `F:\TradingScanner\.claude\docs\PLAN.md` — section "4.1 ingestion_engine.py" subsections on Symbol Mapping, Timestamp Alignment, and Caching Strategy
> - `F:\TradingScanner\research\data-apis\SPEC.md` — CCXT async method signatures, concurrency pattern, error handling
> - `src/quant_scanner/ingestion_engine.py` — READ THE EXISTING CODE from QUANT-002 before adding to it
>
> You must edit/create these files:
> - `src/quant_scanner/ingestion_engine.py` — ADD `map_coingecko_to_ccxt()` and `fetch_historical_data()` to the existing file
> - `tests/test_ingestion.py` — ADD new test functions to the existing test file
> - `tests/conftest.py` — ADD fixtures for mock OHLCV data and mock exchange
>
> **CRITICAL REQUIREMENTS:**
> - `map_coingecko_to_ccxt()`: uppercase symbol + "/USDT", verify in exchange.markets, deduplicate by lowest market_cap_rank number (= highest cap)
> - `fetch_historical_data()`: Use `ccxt.async_support`, `enableRateLimit=True`, `asyncio.Semaphore(10)`
> - Compute `since` with `datetime.now(timezone.utc)` — NOT `datetime.now()`
> - Convert timestamps: `pd.to_datetime(timestamps, unit='ms', utc=True)`
> - Reindex all altcoin DataFrames to BTC's DatetimeIndex, then `ffill(limit=3)`
> - `os.makedirs('cache/ohlcv', exist_ok=True)` before OHLCV cache writes
> - Catch `ccxt.BadSymbol` → log warning, skip symbol
> - Catch empty/None OHLCV response → log warning, skip symbol
> - **MUST** call `await exchange.close()` in a `try/finally` block
> - All tests use `AsyncMock` for `exchange.load_markets`, `exchange.fetch_ohlcv`, `exchange.close`
>
> **TEST CASES:**
> - `test_ohlcv_dataframe_format`: verify columns are [open, high, low, close, volume] and index is DatetimeIndex
> - `test_timestamp_alignment`: create BTC with 5 dates, altcoin missing 1 date. After reindex+ffill, altcoin has all 5 dates with the gap forward-filled
> - `test_symbol_mapping`: input CG coins with symbols "btc", "eth", "render". Exchange has "BTC/USDT", "RENDER/USDT" but NOT "ETH/USDT". Output should contain only RENDER/USDT (BTC is excluded because it's the baseline, ETH is not on exchange)
> - `test_symbol_deduplication`: two CG coins both have symbol "ai". One has market_cap_rank=50, other has rank=200. The one with rank=50 wins
> - `test_exchange_close_called`: after fetch_historical_data completes, assert `exchange.close.assert_awaited_once()`
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_ingestion.py::test_ohlcv_dataframe_format tests/test_ingestion.py::test_timestamp_alignment tests/test_ingestion.py::test_symbol_mapping tests/test_ingestion.py::test_symbol_deduplication tests/test_ingestion.py::test_exchange_close_called -v
```

**Pass criteria:** Exit code 0, all 5 tests PASSED.

---

## STEP 4: QUANT-005 + QUANT-006 — IN PARALLEL

These two stories CAN run in parallel because they touch different files:
- QUANT-005 creates `screener_engine.py` and `test_screener.py`
- QUANT-006 creates `dashboard.py`, `cli.py`, updates `__main__.py`, and creates `test_cli.py`

Both depend on QUANT-002, QUANT-003, and QUANT-004 being complete.

### Builder Agent A: QUANT-005 — Screener Engine

> **Your task: QUANT-005 — Build Screener Engine: Filter Pipeline & Ranking**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\prd.json` — story "QUANT-005" for acceptance criteria
> - `F:\TradingScanner\.claude\docs\PLAN.md` — section "4.3 screener_engine.py" for the public interface and filter pipeline order
> - `src/quant_scanner/ingestion_engine.py` — understand the functions you will call
> - `src/quant_scanner/math_engine.py` — understand compute_all_metrics() interface
>
> You must create:
> - `src/quant_scanner/screener_engine.py` — implement run_screen(), merge_metadata(), apply_filters()
> - `tests/test_screener.py` — implement ALL test cases
>
> **CRITICAL REQUIREMENTS:**
> - `run_screen()` is async and orchestrates: fetch_universe → map_coingecko_to_ccxt → fetch_historical_data → compute_all_metrics → merge_metadata → apply_filters
> - `merge_metadata()` joins CoinGecko data (name, market_cap, volume_24h=total_volume, circulating_supply, total_supply) with math engine output (beta, correlation, kelly_fraction, data_days) on the symbol field
> - Compute `circulating_pct = circulating_supply / total_supply`. If EITHER is null/None/NaN OR total_supply == 0, set circulating_pct = NaN. Use safe division, NOT bare `/`
> - `apply_filters()` filters in THIS order: data_days >= 20, Beta > min_beta, Correlation > min_correlation, volume_24h > min_volume, circulating_pct > min_supply_pct ONLY where circulating_pct is not NaN
> - Sort by Beta descending
> - Output DataFrame columns: symbol, name, market_cap, volume_24h, beta, correlation, kelly_fraction, circulating_pct, data_days
>
> **TEST CASES (all tests mock ingestion and math engines entirely, ZERO network calls):**
> Build a test DataFrame with ~8 mock coins having known values that exercise every filter:
> - Coin with Beta=1.2 → excluded (below 1.5)
> - Coin with Correlation=0.5 → excluded (below 0.7)
> - Coin with volume_24h=500000 → excluded (below 1M)
> - Coin with data_days=15 → excluded (below 20)
> - Coin with circulating_pct=NaN → NOT excluded
> - Coin with total_supply=0 → circulating_pct becomes NaN, NOT ZeroDivisionError
> - Remaining coins → verify sorted by Beta descending
>
> When done, report back. Do NOT run the gate command yourself.

### Builder Agent B: QUANT-006 — CLI & Dashboard

> **Your task: QUANT-006 — Build CLI Dashboard with --dry-run Support**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\prd.json` — story "QUANT-006" for acceptance criteria
> - `F:\TradingScanner\.claude\docs\PLAN.md` — sections "4.4 dashboard.py" and "4.5 cli.py" for the public interface, color rules, arguments table, and entry point specification
>
> You must create/edit:
> - `src/quant_scanner/dashboard.py` — implement render_results(), render_no_results()
> - `src/quant_scanner/cli.py` — implement parse_args(), main(), async_main()
> - `src/quant_scanner/__main__.py` — replace placeholder with exactly: `from quant_scanner.cli import main; main()`
> - `tests/test_cli.py` — implement test_dry_run_flag, test_default_args
>
> **CRITICAL REQUIREMENTS:**
>
> `dashboard.py`:
> - `rich.table.Table` with columns: Rank, Symbol, Name, Market Cap, 24h Volume, Beta, Correlation, Kelly %, Circ. Supply %
> - Color rules: Beta > 2.0 → "bold green", 1.5-2.0 → "yellow"; Correlation > 0.85 → "bold green", 0.7-0.85 → "yellow"; Kelly > 0.15 → "bold green", > 0 → "yellow", == 0 → "dim"
> - `render_no_results()` prints a `rich.panel.Panel` with a message like "No coins matched the screening criteria"
> - Format Market Cap and Volume with commas and $ prefix
> - Format Beta and Correlation to 2 decimal places
> - Format Kelly as percentage (e.g., "12.5%")
> - Format Circ. Supply as percentage (e.g., "78.0%"), show "N/A" if NaN
>
> `cli.py`:
> - `parse_args(argv=None)` using argparse with flags: --dry-run, --exchange, --min-mcap, --max-mcap, --min-beta, --min-corr, --min-volume, --no-cache
> - `main()` is SYNC: calls `logging.basicConfig(level=logging.INFO)`, parses args, then:
>   - If --dry-run: build hardcoded mock DataFrame with 3 example coins, call render_results(), return. NO asyncio.run() needed.
>   - If live: call `asyncio.run(async_main(args))`
> - `async_main(args)` imports and calls run_screen() from screener_engine, then render_results() or render_no_results()
>
> `__main__.py`:
> - Exactly two lines: `from quant_scanner.cli import main` and `main()`
>
> **DRY-RUN MOCK DATA (hardcode in cli.py):**
> ```python
> DRY_RUN_DATA = pd.DataFrame([
>     {"symbol": "RENDER/USDT", "name": "Render", "market_cap": 45_000_000,
>      "volume_24h": 8_500_000, "beta": 2.34, "correlation": 0.89,
>      "kelly_fraction": 0.12, "circulating_pct": 0.78, "data_days": 60},
>     {"symbol": "FET/USDT", "name": "Fetch.ai", "market_cap": 120_000_000,
>      "volume_24h": 15_000_000, "beta": 1.87, "correlation": 0.82,
>      "kelly_fraction": 0.09, "circulating_pct": 0.85, "data_days": 60},
>     {"symbol": "EXAMPLE/USDT", "name": "Example Coin", "market_cap": 30_000_000,
>      "volume_24h": 2_100_000, "beta": 1.62, "correlation": 0.74,
>      "kelly_fraction": 0.05, "circulating_pct": 0.91, "data_days": 45},
> ])
> ```
>
> When done, report back. Do NOT run the gate command yourself.

**After BOTH Builders report, YOU run both gates:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_screener.py -v
```

```bash
cd /f/TradingScanner && .venv/Scripts/python -m quant_scanner --dry-run
```

**Pass criteria for QUANT-005:** Exit code 0, all screener tests PASSED.
**Pass criteria for QUANT-006:** Exit code 0, a formatted table is printed to terminal with 3 rows of data.

---

## STEP 5: FINAL INTEGRATION VERIFICATION

After all 6 gates pass, run the full test suite to confirm nothing broke:

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/ -v --tb=short
```

**Pass criteria:** ALL tests pass. Zero failures, zero errors. Test count should be approximately 25-30 tests.

Then run the dry-run one more time to confirm end-to-end:

```bash
cd /f/TradingScanner && .venv/Scripts/python -m quant_scanner --dry-run
```

**Pass criteria:** Formatted table appears with 3 coins, color-coded columns, clean exit.

---

## EXECUTION SUMMARY

```
STEP 0: Read all plan docs                          [YOU, synchronous]
STEP 1: QUANT-001 scaffolding                       [1 Builder, sequential]
        └── gate: pytest tests/ -v
STEP 2: QUANT-002 ingestion + QUANT-004 math        [2 Builders, PARALLEL]
        ├── gate: pytest test_ingestion.py (4 tests)
        └── gate: pytest test_math.py (9 tests)
STEP 3: QUANT-003 OHLCV/symbols                     [1 Builder, sequential]
        └── gate: pytest test_ingestion.py (5 tests)
STEP 4: QUANT-005 screener + QUANT-006 CLI          [2 Builders, PARALLEL]
        ├── gate: pytest test_screener.py (7 tests)
        └── gate: python -m quant_scanner --dry-run
STEP 5: Full integration test                        [YOU, synchronous]
        ├── pytest tests/ -v --tb=short
        └── python -m quant_scanner --dry-run
```

**Total Builder agents spawned: 6** (1 + 2 parallel + 1 + 2 parallel)
**Total gate commands: 8** (6 story gates + 2 integration checks)

---

## FAILURE PROTOCOL

If a gate fails:
1. Read the FULL pytest traceback or error output
2. Identify the exact assertion or import error
3. Send the error to the responsible Builder agent with instruction: "Fix ONLY this issue. Do not refactor other code."
4. Re-run the gate
5. If it fails 3 times, STOP and report: which story, which test, what the error is, and what you've tried

If a Builder agent produces code that imports a module from a story that hasn't passed its gate yet, reject immediately — that's a dependency violation.

---

## WHAT SUCCESS LOOKS LIKE

When you are done, you should be able to report:

```
BUILD COMPLETE — All 6 stories passed.

QUANT-001: PASSED — scaffolding, venv, editable install
QUANT-002: PASSED — CoinGecko fetch, caching, filtering (4 tests)
QUANT-003: PASSED — OHLCV fetch, symbol mapping, alignment (5 tests)
QUANT-004: PASSED — Beta, Correlation, Kelly math (9 tests)
QUANT-005: PASSED — Screener pipeline, filters, ranking (7 tests)
QUANT-006: PASSED — CLI dashboard, --dry-run works

Integration: ALL ~30 tests pass. Dry-run produces formatted table.
```

Begin now. Start with STEP 0 — read all 5 plan documents.
