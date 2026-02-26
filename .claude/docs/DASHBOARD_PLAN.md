# Dashboard Build Plan — Production-Grade 24/7 Live Scanner

## Executive Summary

Upgrade the one-shot CLI scanner into a **persistent, auto-refreshing web dashboard**
that runs 24/7 and displays live screening results in a browser. Stack:
**FastAPI + Jinja2 + HTMX + Lightweight Charts (TradingView)**.

### Why This Stack

| Requirement | FastAPI+HTMX | Dash | Streamlit | Textual |
|---|---|---|---|---|
| Async-native (fits our ccxt/aiohttp pipeline) | YES | NO | NO | YES |
| 24/7 reliable (no terminal, no re-execution) | YES | Leaks | Re-runs | Terminal-bound |
| Lightweight (~5 MB new deps) | YES | +20 MB | +50 MB | +1 MB |
| Full charting (candlestick, sparklines) | YES (JS) | YES | Weak | Sparklines only |
| WebSocket/SSE for push updates | YES | Hacky | NO | NO |
| Testable (httpx.AsyncClient) | YES | Hacky | NO | YES |

### Non-Negotiable Constraints

1. **ZERO changes to math_engine.py** — it is proven correct (Beta=2.0, Corr=-1.0 exact).
2. **ZERO changes to ingestion_engine.py** — rate limiting, caching, backoff all tested.
3. **screener_engine.py** may gain a thin wrapper but `run_screen()` stays untouched.
4. **Existing 48 tests MUST still pass** after the dashboard is built.
5. Every new module gets **dedicated tests with zero network calls**.
6. Every story has a **gate command** — pass or fail, no subjective judgment.

---

## Architecture Overview

```
Browser (any device on network)
    │
    │  HTTP GET / (full page load, once)
    │  HTMX GET /partials/table (poll every 60s)
    │  HTMX GET /partials/status (poll every 10s)
    │  GET /api/scan (JSON endpoint for programmatic use)
    │  GET /api/history (last N scan snapshots)
    │  WS  /ws/updates (optional: push on new scan)
    │
    ▼
┌─────────────────────────────────────────────────┐
│  FastAPI (uvicorn, single async process)         │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │  BackgroundScheduler                        │ │
│  │  - Runs run_screen() every REFRESH_INTERVAL │ │
│  │  - Stores result in ScanStore (in-memory)   │ │
│  │  - Broadcasts via WebSocket manager         │ │
│  │  - Catches ALL exceptions (never crashes)   │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────┐  ┌────────────────────┐        │
│  │  ScanStore   │  │  WebSocket Manager │        │
│  │  - latest    │  │  - connected       │        │
│  │  - history[] │  │  - broadcast()     │        │
│  │  - status    │  │  - cleanup()       │        │
│  │  - lock      │  │                    │        │
│  └──────────────┘  └────────────────────┘        │
│                                                  │
│  Routes:                                         │
│  GET  /              → index.html (Jinja2)       │
│  GET  /partials/table  → table fragment (HTMX)   │
│  GET  /partials/status → status bar fragment      │
│  GET  /api/scan      → JSON (latest results)     │
│  GET  /api/history   → JSON (last 24 snapshots)  │
│  GET  /api/health    → {"status":"ok", ...}      │
│  WS   /ws/updates    → push on new scan          │
└─────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│  Existing Pipeline (UNCHANGED)           │
│  screener_engine.run_screen()            │
│    → ingestion_engine (CoinGecko + CCXT) │
│    → math_engine (Beta/Corr/Kelly)       │
│    → merge + filter + sort               │
└──────────────────────────────────────────┘
```

---

## File Plan

### New Files

```
src/quant_scanner/
├── server.py              # FastAPI app, routes, lifespan, ~200 LOC
├── scan_store.py          # Thread-safe in-memory store, ~80 LOC
├── scheduler.py           # Background scan loop, ~100 LOC
├── ws_manager.py          # WebSocket connection manager, ~50 LOC
├── templates/
│   ├── index.html         # Main page (Jinja2 + HTMX + charts), ~250 LOC
│   └── partials/
│       ├── table.html     # Scan results table fragment, ~80 LOC
│       └── status.html    # Status bar fragment, ~30 LOC
└── static/
    ├── style.css          # Dashboard styling, ~150 LOC
    ├── charts.js          # Chart initialization + update logic, ~100 LOC
    └── vendor/
        ├── htmx.min.js    # Local fallback for HTMX (~14 KB)
        └── lightweight-charts.min.js  # Local fallback (~45 KB)

tests/
├── test_server.py         # FastAPI route tests (httpx), ~200 LOC
├── test_scan_store.py     # Store unit tests, ~100 LOC
├── test_scheduler.py      # Scheduler tests (mocked run_screen), ~120 LOC
└── test_ws_manager.py     # WebSocket manager tests, ~80 LOC
```

### Modified Files

```
pyproject.toml             # Add: fastapi, uvicorn, websockets, jinja2, httpx (dev)
cli.py                     # Add: --serve flag and serve() command
```

### NOT Modified (Proven Correct)

```
ingestion_engine.py        # FROZEN
math_engine.py             # FROZEN
screener_engine.py         # FROZEN (run_screen unchanged)
dashboard.py               # FROZEN (Rich CLI still works for --dry-run)
tests/conftest.py          # FROZEN
tests/test_ingestion.py    # FROZEN
tests/test_math.py         # FROZEN
tests/test_screener.py     # FROZEN
tests/test_scaffold.py     # FROZEN
```

---

## New Dependencies

| Package | Version | Purpose | Size |
|---------|---------|---------|------|
| fastapi | >=0.110 | Async web framework | ~2 MB |
| uvicorn | >=0.27 | ASGI server | ~1 MB |
| websockets | >=12.0 | WebSocket protocol (required by FastAPI WS) | ~0.5 MB |
| jinja2 | >=3.1 | HTML templates | ~1 MB |
| httpx | >=0.27 | Test client for FastAPI (dev only) | ~1 MB |

**Total new footprint: ~4.5 MB runtime, ~5.5 MB with dev.**

> **CRITICAL: Do NOT use `uvicorn[standard]`.** The `[standard]` extra installs
> `uvloop` which does NOT support Windows. Use plain `uvicorn>=0.27` and add
> `websockets>=12.0` explicitly for WebSocket support.

Frontend (bundled locally in `static/vendor/` with CDN as primary):
- HTMX 2.x (~14 KB gzipped) — bundled locally as fallback
- TradingView Lightweight Charts 4.x (~45 KB gzipped) — bundled locally as fallback

> **CDN Fallback:** Both HTMX and Lightweight Charts are loaded from CDN first.
> If CDN is unreachable (no internet), local copies in `static/vendor/` serve as
> fallback. Without HTMX, auto-refresh breaks entirely, so the local fallback is
> mandatory, not optional.

---

## Story Sequence

### Parallelizable Groups

```
Step 1: DASH-001 (scaffold)              — sequential (installs deps)
Step 2: DASH-002 + DASH-003 in parallel  — store + scheduler are independent
Step 3: DASH-004                          — routes depend on store + scheduler
Step 4: DASH-005                          — frontend HTML/CSS (creates index.html)
Step 5: DASH-006                          — WebSocket (modifies index.html JS section)
    > DASH-005 and DASH-006 are SEQUENTIAL, not parallel, because both modify
    > index.html. DASH-005 creates the HTML structure; DASH-006 adds the WebSocket JS.
Step 6: DASH-007                          — CLI --serve flag
Step 7: DASH-008                          — resilience hardening (depends on all)
```

---

## DASH-001: Dependencies & Server Skeleton

### Goal
Install new dependencies, create the FastAPI app with health endpoint,
verify uvicorn serves it.

### Acceptance Criteria

1. Add to `pyproject.toml` dependencies: `fastapi>=0.110`, `uvicorn>=0.27`, `websockets>=12.0`, `jinja2>=3.1`
   > **CRITICAL: NOT `uvicorn[standard]`** — the `[standard]` extra installs `uvloop`
   > which does NOT work on Windows. Use plain `uvicorn` + explicit `websockets`.
2. Add to `pyproject.toml` dev dependencies: `httpx>=0.27`
3. Add to `pyproject.toml` package-data so templates/static are included in wheel:
   ```toml
   [tool.setuptools.package-data]
   quant_scanner = ["templates/**/*.html", "static/**/*"]
   ```
4. Run `pip install -e ".[dev]"` to install new packages
5. Create `src/quant_scanner/server.py` with:
   - `app = FastAPI(title="Crypto Quant Scanner", version="0.1.0")`
   - Lifespan context manager (async generator) that will later start/stop scheduler
   - For now, lifespan is a no-op (yields immediately)
   - `GET /api/health` returns `{"status": "ok", "version": "0.1.0", "uptime_seconds": float}`
   - Track server start time using `time.monotonic()` at lifespan startup (NOT
     `datetime.now()` — monotonic clock is immune to NTP sync jumps)
   - `GET /favicon.ico` returns 204 No Content (prevents 404 log noise from browsers)
6. Create `tests/test_server.py` with:
   - Use `httpx.AsyncClient` + `httpx.ASGITransport` as async context manager
     to properly trigger lifespan events:
     ```python
     transport = httpx.ASGITransport(app=app)
     async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
         response = await client.get("/api/health")
     ```
   - `test_health_endpoint`: GET /api/health returns 200, body has "status"="ok"
   - `test_health_has_uptime`: response includes "uptime_seconds" >= 0
   - `test_health_has_version`: response includes "version" matching `__version__`
7. All 48 existing tests still pass

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py tests/test_scaffold.py tests/test_math.py tests/test_ingestion.py tests/test_screener.py tests/test_cli.py -v
```

---

## DASH-002: ScanStore — Coroutine-Safe In-Memory Data Store

### Goal
Create a store that holds the latest scan result, historical snapshots,
and scan metadata (status, timestamps, error info). This decouples the
scanner from the web routes.

> **Naming note:** This store is "coroutine-safe" (protected by `asyncio.Lock`),
> NOT thread-safe. All access happens on a single asyncio event loop. If uvicorn
> is ever run with `--workers > 1`, each worker gets its own store instance.
> Do NOT use `run_in_executor()` to access the store from a thread.

### Acceptance Criteria

1. Create `src/quant_scanner/scan_store.py` with class `ScanStore`:
   ```python
   class ScanStore:
       def __init__(self, max_history: int = 288):  # 288 = 24h at 5min intervals
       async def update(self, df: pd.DataFrame) -> None:
       def get_latest(self) -> pd.DataFrame | None:
       def get_latest_as_records(self) -> list[dict]:  # NaN-safe JSON serialization
       def get_history(self, limit: int = 24) -> list[dict]:
       def get_status(self) -> dict:
       def set_error(self, error: str) -> None:
       def clear_error(self) -> None:
       def set_scanning(self) -> None:
       def set_next_scan_at(self, dt: datetime) -> None:
   ```
2. `update()` stores a COPY of the DataFrame (`df.copy()`), records `updated_at`
   timestamp (UTC), appends a snapshot summary to history (timestamp, coin_count,
   top_beta_symbol), trims history to `max_history` entries
3. `get_latest()` returns a COPY of the most recent DataFrame (`self._latest.copy()`)
   or None if no scan completed yet. **Callers must not mutate the stored data.**
4. `get_latest_as_records()` returns the latest DataFrame as `list[dict]` with
   **all NaN/None values converted to None** for valid JSON serialization.
   Implementation: `df.where(df.notna(), None).to_dict(orient='records')`.
   This is the ONLY method routes should use for JSON responses.
5. `get_history()` returns the last N snapshot summaries as list of dicts
6. `get_status()` returns:
   ```python
   {
       "last_scan_at": "ISO timestamp or null",
       "next_scan_at": "ISO timestamp or null",  # set by scheduler
       "scan_count": int,
       "coin_count": int,  # coins in latest result
       "status": "idle" | "scanning" | "error",
       "error": "message or null",
   }
   ```
   > **Note:** `uptime_seconds` is NOT in the store. It belongs only in
   > `/api/health`, computed from `app.state.start_time` using `time.monotonic()`.
7. `set_scanning()` sets status to "scanning"
8. `set_next_scan_at(dt)` updates the next_scan_at field
9. Use `asyncio.Lock` to protect `update()` from concurrent coroutine access
   (scheduler + manual refresh could overlap)
10. All fields default to safe values (None, 0, "idle", empty list) on init
8. Create `tests/test_scan_store.py` with:
   - `test_initial_state`: new store has None latest, empty history, status="idle"
   - `test_update_stores_dataframe`: after update(), get_latest() returns the df
   - `test_update_records_history`: after 3 updates, get_history(3) returns 3 entries
   - `test_history_limit`: after max_history+5 updates, history length == max_history
   - `test_status_after_update`: scan_count increments, coin_count matches df length
   - `test_error_handling`: set_error() sets status="error" and message; clear_error() resets
   - `test_concurrent_updates`: two concurrent update() calls don't corrupt state
   - `test_empty_dataframe_update`: update with empty df sets coin_count=0, still records history

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_scan_store.py -v
```

---

## DASH-003: Background Scheduler

### Goal
Create an async background loop that calls `run_screen()` on a configurable
interval, stores results in ScanStore, and NEVER crashes the server.

### Acceptance Criteria

1. Create `src/quant_scanner/scheduler.py` with:
   ```python
   class ScanScheduler:
       def __init__(
           self,
           store: ScanStore,
           interval_seconds: int = 300,  # 5 minutes
           scan_kwargs: dict | None = None,  # passed to run_screen()
       ):
       async def start(self) -> None:  # launches background task
       async def stop(self) -> None:   # cancels background task, waits for cleanup
       async def trigger_now(self) -> None:  # manual trigger (for refresh button)
       async def _loop(self) -> None:  # the actual loop
       async def _run_one_scan(self) -> None:  # single scan execution
   ```
2. `_loop()` runs forever: call `_run_one_scan()`, then compute remaining sleep:
   `sleep_time = max(0, interval - (time.monotonic() - scan_start))`.
   This prevents scan-duration drift — if a scan takes 2 minutes with a 5-minute
   interval, the next scan starts 3 minutes later (not 7). Then wait for EITHER
   `asyncio.sleep(sleep_time)` OR `self._trigger_event` using `asyncio.wait()`
   with `return_when=FIRST_COMPLETED`. Clear the event after waking.
   On CancelledError, exit cleanly.
3. `_run_one_scan()` MUST:
   - Set `self._scanning = True` and call `store.set_scanning()`
   - Import `run_screen` lazily (inside the method, not at module top) to avoid
     circular imports and ensure `--dry-run` works without importing the server
   - Call `await run_screen(**scan_kwargs)`
   - On success: `await store.update(result)`, `store.clear_error()`,
     if ws_manager: `await ws_manager.broadcast({...})`
   - On ANY exception: `store.set_error(str(e))`, log full traceback via
     `logger.exception()`, do NOT re-raise (the loop continues)
   - Finally: `self._scanning = False`, update `next_scan_at` in store
4. `trigger_now()` uses an `asyncio.Event` to wake the loop early.
   If a scan is already running (`self._scanning is True`), it does nothing
   (no double-scan). Also applies a 10-second cooldown — reject triggers
   within 10s of the last trigger to prevent abuse of POST /api/refresh.
5. `stop()` cancels the background task and waits for it with a 30-second timeout.
   If timeout, log a warning and continue (don't hang shutdown).
6. `start()` is idempotent — calling it twice doesn't create two loops.
7. scan_kwargs defaults to `{"use_cache": True}` if not provided.
8. Create `tests/test_scheduler.py` with:
   - ALL tests mock `run_screen` with `AsyncMock` — ZERO network calls
   - **Use `asyncio.Event` for synchronization instead of `asyncio.sleep` in tests**
     to prevent timing-dependent flakiness. Mock `run_screen` to set an event
     when called; tests await that event instead of sleeping a fixed duration.
   - **Use a pytest fixture with cleanup** to prevent leaked tasks:
     ```python
     @pytest.fixture
     async def scheduler(store):
         sched = ScanScheduler(store=store, interval_seconds=9999)
         yield sched
         await sched.stop()  # always cleanup
     ```
   - `test_scheduler_calls_run_screen`: start scheduler, await mock event, verify called
   - `test_scheduler_stores_result`: after scan, store.get_latest() is not None
   - `test_scheduler_survives_exception`: mock run_screen to raise RuntimeError,
     verify scheduler continues (store has error status, not crashed)
   - `test_scheduler_stop_clean`: start then stop, verify no background task running
   - `test_trigger_now`: trigger_now() causes an immediate scan (not waiting for interval)
   - `test_scheduler_start_idempotent`: calling start() twice doesn't create two tasks
   - `test_scan_sets_status`: mock run_screen with an Event to control timing,
     verify status is "scanning" during scan and "idle" after
   - `test_scheduler_passes_kwargs`: scan_kwargs are forwarded to run_screen

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_scheduler.py -v
```

---

## DASH-004: FastAPI Routes & Jinja2 Templates

### Goal
Wire the ScanStore and Scheduler into FastAPI routes. Serve the main
page with Jinja2. Serve HTMX partial fragments for auto-refresh.

### Acceptance Criteria

1. Update `src/quant_scanner/server.py`:
   - Create `ScanStore` and `ScanScheduler` instances at lifespan startup
   - Start scheduler in lifespan; stop scheduler in lifespan cleanup
   - Configure Jinja2Templates pointing to `templates/` directory
   - Mount `/static` for static files
   - Store and scheduler accessible via `app.state.store` and `app.state.scheduler`

2. Routes:
   ```python
   GET /                  # Serves index.html (full page)
   GET /partials/table    # Returns ONLY the table HTML fragment (for HTMX swap)
   GET /partials/status   # Returns ONLY the status bar fragment
   GET /api/scan          # Returns JSON: latest scan as list of records
   GET /api/history       # Returns JSON: historical snapshots
   GET /api/health        # Already exists from DASH-001 (enhance with store status)
   POST /api/refresh      # Triggers immediate re-scan, returns 202 Accepted
   ```

3. `GET /` renders `templates/index.html` with context:
   - `results`: latest scan DataFrame as list of dicts (or empty list)
   - `status`: store.get_status()
   - `config`: current scan_kwargs (exchange, thresholds, etc.)

4. `GET /partials/table` renders `templates/partials/table.html`:
   - Just the `<tbody>` rows or full `<table>` element
   - Color coding: Beta > 2.0 → green class, 1.5-2.0 → yellow class, etc.
   - Format numbers: market_cap → "$45.0M", volume → "$8.5M", beta → "2.34",
     correlation → "0.89", kelly → "12.0%", circulating_pct → "78.0%" or "N/A"
   - If no results: show "No coins pass current filters" message

5. `GET /partials/status` renders `templates/partials/status.html`:
   - Shows: status (idle/scanning/error), last scan time (relative: "2m ago"),
     next scan time, coin count, scan count
   - If error: show error message in red

6. `GET /api/scan` returns:
   ```json
   {
       "results": [...],
       "count": 5,
       "scanned_at": "ISO timestamp",
       "status": "idle"
   }
   ```
   > **CRITICAL: NaN JSON serialization.** The DataFrame from `run_screen()`
   > contains `np.nan` values (e.g., `circulating_pct`). `json.dumps(float('nan'))`
   > produces `NaN` which is NOT valid JSON (RFC 8259). The `/api/scan` route
   > MUST use `store.get_latest_as_records()` which converts NaN→None before
   > serialization. NEVER call `df.to_dict()` directly in a route.

   If no scan yet: `{"results": [], "count": 0, "scanned_at": null, "status": "idle"}`

7. `POST /api/refresh` calls `scheduler.trigger_now()` and returns:
   ```json
   {"message": "Scan triggered", "status": "scanning"}
   ```
   > The scheduler's `trigger_now()` has a 10-second cooldown to prevent abuse.

8. Update `/api/health` to include store status fields (coin_count, last_scan_at).

9. Server configuration via `_server_config` module-level dict:
   > **Test pollution warning:** Tests that call `server.configure()` mutate
   > module-level state. Each test module MUST reset config in a fixture:
   > ```python
   > @pytest.fixture(autouse=True)
   > def reset_server_config():
   >     from quant_scanner.server import _server_config, _DEFAULT_CONFIG
   >     _server_config.update(_DEFAULT_CONFIG)
   >     yield
   >     _server_config.update(_DEFAULT_CONFIG)
   > ```

10. Create `tests/test_server.py` additions (or extend existing):
   - `test_index_returns_html`: GET / returns 200 with content-type text/html
   - `test_partials_table_returns_fragment`: GET /partials/table returns 200
   - `test_partials_status_returns_fragment`: GET /partials/status returns 200
   - `test_api_scan_json`: GET /api/scan returns valid JSON with "results" key
   - `test_api_scan_empty_before_first_scan`: returns empty results before scheduler runs
   - `test_api_scan_nan_safe`: after a scan with NaN circulating_pct, GET /api/scan
     returns valid JSON (no NaN literals); verify `json.loads()` succeeds
   - `test_api_history_json`: GET /api/history returns list
   - `test_api_refresh_triggers_scan`: POST /api/refresh returns 202
   - `test_api_refresh_returns_scanning_status`: after trigger, status includes "scanning"
   - `test_format_mcap_none`: Jinja2 format_mcap filter handles None → "N/A"
   - `test_format_mcap_nan`: Jinja2 format_mcap filter handles NaN → "N/A"
   - ALL tests mock `run_screen` — ZERO network calls
   - Use `httpx.AsyncClient` as async context manager to trigger lifespan:
     ```python
     async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
         response = await client.get("/api/scan")
     ```

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py -v
```

---

## DASH-005: Frontend — HTML, CSS, HTMX Auto-Refresh

### Goal
Build the complete frontend that auto-refreshes via HTMX polling,
with proper styling that replicates and enhances the Rich terminal table.

### Acceptance Criteria

1. Create `src/quant_scanner/templates/index.html`:
   - HTML5 document with proper meta tags (charset, viewport)
   - Load HTMX from CDN with local fallback:
     ```html
     <script src="https://unpkg.com/htmx.org@2.0.4"></script>
     <script>window.htmx || document.write('<script src="/static/vendor/htmx.min.js"><\/script>')</script>
     ```
   - Load Lightweight Charts from CDN with local fallback (same pattern)
   - Link to `/static/style.css`
   - Page title: "Crypto Quant Scanner — Live Dashboard"
   - Layout sections:
     a. **Header**: Title + "Live" indicator (green dot when connected)
     b. **Status Bar**: `hx-get="/partials/status" hx-trigger="every 10s"` —
        shows scan status, last update time, next update time, coin count
     c. **Config Display**: Show active exchange, min_beta, min_corr, min_volume
        so the user knows WHICH filters are running
     d. **Controls Row**: Refresh button (`hx-post="/api/refresh"`),
        filter display (current min_beta, min_corr, min_volume)
     e. **Results Table**: `hx-get="/partials/table" hx-trigger="every 60s"` —
        full data table with sorting indicators
     f. **Footer**: Version, uptime, "Powered by CoinGecko + CCXT"
   - HTMX indicators: show spinner during table/status fetches
     (`hx-indicator=".spinner"`)
   - **Dedup HTMX+WS refreshes:** When WebSocket triggers a `scan-complete` event,
     JavaScript resets the HTMX polling timer to prevent a double-fetch. Pattern:
     ```javascript
     // On WS scan-complete, refresh table then reset poll timer
     document.body.addEventListener('scan-complete', () => {
         htmx.trigger('#results-table', 'htmx:abort');  // cancel pending poll
         htmx.ajax('GET', '/partials/table', '#results-table');  // immediate fetch
     });
     ```
     The table div uses `hx-trigger="every 60s"` only — the WS event triggers
     via JS, not a second hx-trigger attribute. This eliminates the double-refresh race.

2. Create `src/quant_scanner/templates/partials/table.html`:
   - `<table>` with columns matching Rich dashboard:
     Rank, Symbol, Name, Market Cap, 24h Volume, Beta, Correlation, Kelly %, Circ. %
   - Each metric cell has CSS class based on value:
     - `.beta-high` (>2.0), `.beta-mid` (1.5-2.0), `.beta-low` (<1.5)
     - `.corr-high` (>0.85), `.corr-mid` (0.7-0.85), `.corr-low` (<0.7)
     - `.kelly-high` (>0.15), `.kelly-mid` (>0), `.kelly-zero` (==0)
   - Number formatting: Market Cap "$45.0M", Volume "$8.5M", Beta "2.34",
     Correlation "0.89", Kelly "12.0%", Circ "78.0%" or "N/A"
   - Empty state: single row spanning all columns: "No coins pass current filters"
     or "Waiting for first scan..." if never scanned

3. Create `src/quant_scanner/templates/partials/status.html`:
   - Shows: Status badge (green=idle, yellow=scanning, red=error)
   - Last scan: relative time ("2m ago") + absolute UTC time on hover
   - Next scan: countdown or relative time
   - Coins found: count
   - Total scans: count
   - Error message (if any, in red)

4. Create `src/quant_scanner/static/style.css`:
   - Dark theme (matches terminal aesthetic): `#0d1117` background, `#c9d1d9` text
   - Table styling: alternating row colors, hover highlight
   - Color classes matching Rich output:
     - `.beta-high { color: #3fb950; font-weight: bold; }`  (green)
     - `.beta-mid { color: #d29922; }` (yellow)
     - `.corr-high { color: #3fb950; font-weight: bold; }`
     - `.corr-mid { color: #d29922; }`
     - `.kelly-high { color: #3fb950; font-weight: bold; }`
     - `.kelly-mid { color: #d29922; }`
     - `.kelly-zero { color: #484f58; }` (dim)
   - Status badge: colored dot + text
   - Responsive: table scrolls horizontally on mobile
   - Spinner animation for HTMX loading states
   - Transition effects on table swap (subtle fade)

5. Create `src/quant_scanner/static/charts.js`:
   - Initialize a TradingView Lightweight Chart container (hidden by default)
   - Function `renderBetaSparkline(elementId, values)` — mini inline chart
   - For v1: chart section is a placeholder with "Charts coming in next release"
     text. The chart JS infrastructure is wired but data feed is deferred to
     DASH-006. This prevents blocking on chart data plumbing.

6. All HTMX attributes use proper error handling:
   - `hx-on::after-request="if(event.detail.failed) this.innerHTML = 'Error loading data'"`
   - Network failure doesn't blank the table (HTMX settles on error by default,
     but we add explicit handling)

7. Test: the HTML templates must be syntactically valid (no unclosed tags).
   Add to test_server.py:
   - `test_index_contains_htmx`: response body contains "htmx.org"
   - `test_index_contains_table`: response body contains "<table" tag
   - `test_partials_table_contains_rows`: after a mock scan, table partial
     contains coin symbols from the mock data
   - `test_partials_status_shows_idle`: before any scan, status shows "idle"

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py -v && .venv/Scripts/python -c "from quant_scanner.server import app; print('Server imports OK')"
```

---

## DASH-006: WebSocket Live Push

### Goal
Add WebSocket support so the dashboard updates instantly when a new scan
completes, instead of waiting for the next HTMX poll.

### Acceptance Criteria

1. Create `src/quant_scanner/ws_manager.py`:
   ```python
   class ConnectionManager:
       def __init__(self):
       async def connect(self, websocket: WebSocket) -> None:
       def disconnect(self, websocket: WebSocket) -> None:
       async def broadcast(self, message: dict) -> None:
   ```
2. `connect()` accepts the WebSocket and adds to active set
3. `disconnect()` removes from active set (safe if already removed)
4. `broadcast()` sends JSON to ALL connected clients. If a send fails
   (client disconnected), catch the exception, remove that client, continue
   broadcasting to others. NEVER let one bad client crash the broadcast.
5. Wire into `server.py`:
   - `WS /ws/updates` endpoint that accepts connections via manager
   - On disconnect: remove from manager
6. Wire into `scheduler.py`:
   - After successful scan, call `manager.broadcast({"type": "scan_complete", "coin_count": N})`
   - Pass manager reference to scheduler at init (optional dependency — if None, skip broadcast)
7. Frontend (`index.html`) JavaScript:
   - Connect to `ws://host/ws/updates` on page load
   - On "scan_complete" message: trigger HTMX refresh of table + status
     (`htmx.trigger(document.body, 'scan-complete')`)
   - Auto-reconnect on disconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
   - Show connection status indicator (green dot = connected, red = disconnected)
8. Create `tests/test_ws_manager.py` (unit tests with mock WebSocket objects):
   - `test_connect_adds_to_set`: after connect, manager has 1 connection
   - `test_disconnect_removes`: after disconnect, manager has 0 connections
   - `test_broadcast_sends_to_all`: connect 2 clients, broadcast, both receive
   - `test_broadcast_handles_dead_client`: one client force-closed, broadcast
     doesn't crash, remaining client still receives
   - `test_disconnect_idempotent`: disconnecting twice doesn't raise
   - `test_client_count`: connect 3, disconnect 1, verify client_count() == 2
   - `test_broadcast_to_zero_clients`: broadcast with no connections is a no-op

9. WebSocket endpoint integration test (in `tests/test_server.py`):
   > **IMPORTANT: `httpx.ASGITransport` does NOT support WebSocket testing.**
   > Use Starlette's `TestClient` for WebSocket-specific tests:
   > ```python
   > from starlette.testclient import TestClient
   > def test_ws_endpoint_connects():
   >     with TestClient(app) as client:
   >         with client.websocket_connect("/ws/updates") as ws:
   >             # Connection established
   >             pass  # disconnect
   > ```
   > Note: `TestClient` is synchronous (uses `anyio`). WebSocket tests are
   > in their own test class/file to avoid confusing async/sync patterns.

10. Bundle local copies of HTMX and Lightweight Charts:
    - Download `htmx.min.js` (v2.0.4) → `src/quant_scanner/static/vendor/htmx.min.js`
    - Download `lightweight-charts.standalone.production.js` (v4.2.2) →
      `src/quant_scanner/static/vendor/lightweight-charts.min.js`
    - These are ~60KB total and ensure the dashboard works without internet

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_ws_manager.py tests/test_server.py -v
```

---

## DASH-007: CLI Integration & Serve Command

### Goal
Add `--serve` flag to CLI so the user can launch the dashboard from the
same entry point. Wire up all configuration (exchange, thresholds) to
pass through to the scheduler.

### Acceptance Criteria

1. Update `cli.py`:
   - Add `--serve` flag: `action="store_true"`, help="Launch live web dashboard"
   - Add `--port` flag: `type=int, default=8080`, help="Dashboard port"
   - Add `--host` flag: `type=str, default="127.0.0.1"`, help="Dashboard bind address"
   - Add `--refresh-interval` flag: `type=int, default=300`, help="Scan interval in seconds"
   - When `--serve` is set: import server, configure scan_kwargs from CLI args,
     launch with `uvicorn.run(app, host=host, port=port)`
   - `--dry-run` and `--serve` are mutually exclusive — if both set, print error and exit(1)
   - `--serve` without other flags uses all defaults

2. Configuration flow:
   ```python
   scan_kwargs = {
       "exchange_id": args.exchange,
       "min_mcap": args.min_mcap,
       "max_mcap": args.max_mcap,
       "min_beta": args.min_beta,
       "min_correlation": args.min_corr,
       "min_volume": args.min_volume,
       "use_cache": not args.no_cache,
   }
   ```
   These are passed to the scheduler, which passes them to `run_screen()`.

3. Server configuration mechanism:
   - Create a simple config dict that `server.py` reads at lifespan startup
   - Set via `server.configure(scan_kwargs=..., interval=..., ...)` BEFORE `uvicorn.run()`
   - This avoids global mutable state while allowing CLI to configure the server

4. Update `tests/test_cli.py`:
   - `test_serve_flag`: `parse_args(['--serve'])` sets args.serve to True
   - `test_port_flag`: `parse_args(['--port', '9090'])` sets args.port to 9090
   - `test_host_flag`: `parse_args(['--host', '0.0.0.0'])` sets args.host
   - `test_refresh_interval_flag`: `parse_args(['--refresh-interval', '60'])` sets correctly
   - `test_default_port`: default port is 8080
   - `test_default_host`: default host is "127.0.0.1"
   - `test_default_refresh_interval`: default interval is 300

5. Existing `--dry-run` behavior unchanged.
6. Existing one-shot scan (no flags) behavior unchanged.

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_cli.py -v && .venv/Scripts/python -m quant_scanner --dry-run
```

---

## DASH-008: Resilience Hardening & Final Integration

### Goal
Ensure the dashboard runs 24/7 without crashing, leaking memory, or
losing data. This is the "make it bulletproof" story.

### Acceptance Criteria

1. **Graceful shutdown**:
   - On SIGINT (Ctrl+C): scheduler stops cleanly, active scan completes or
     is cancelled with 30s timeout, WebSocket connections closed, server stops
   - Implement via FastAPI lifespan cleanup (already structured in DASH-001)
   - > **Windows note:** `SIGTERM` does NOT work on Windows. Only `SIGINT`
   >   (Ctrl+C) triggers graceful shutdown. This is a platform limitation, not a bug.
   >   On Linux/macOS both SIGINT and SIGTERM work via uvicorn's signal handlers.
   - Test: verify lifespan cleanup calls `scheduler.stop()` (mock-based, no real signals)

2. **Memory safety**:
   - ScanStore history is bounded (max_history=288, ~24h at 5min intervals)
   - Old DataFrames are dereferenced when replaced by new scan (Python GC handles it)
   - WebSocket manager prunes dead connections on every broadcast
   - No global DataFrame accumulation — only latest + bounded history summaries

3. **Error recovery** (ALL of these must be tested):
   - CoinGecko down → scan fails → store records error → dashboard shows
     "Last successful scan: 5m ago, Error: <message>" → next scan retries
   - CCXT exchange unreachable → same pattern
   - All coins filtered out → empty DataFrame → dashboard shows
     "No coins pass filters" → not an error state
   - WebSocket client disconnects mid-broadcast → other clients unaffected
   - Jinja2 template rendering error → FastAPI returns 500 with JSON error
     (not a crash)

4. **Logging**:
   - Structured logging at startup: bind address, port, refresh interval,
     exchange, all threshold values
   - Each scan: log start, duration, coin count, or error
   - WebSocket: log connect/disconnect events at DEBUG level
   - Rate limit hits: already logged by ingestion engine (no change needed)

5. **Health check enhanced**:
   - `/api/health` returns:
     ```json
     {
         "status": "ok",
         "version": "0.1.0",
         "uptime_seconds": 3600.5,
         "scanner": {
             "status": "idle",
             "last_scan_at": "ISO",
             "scan_count": 42,
             "coin_count": 7,
             "error": null
         },
         "websocket_clients": 2
     }
     ```

6. **Static file serving hardened**:
   - If static/ or templates/ directory is missing, server starts but returns
     useful 500 error on GET / (not a crash)
   - CDN scripts (HTMX, Lightweight Charts) have integrity hashes in HTML

7. **Create integration test file** `tests/test_integration_dashboard.py`:
   - `test_full_lifecycle`: mock run_screen → start app → verify /api/health →
     wait for scheduler → verify /api/scan has results → verify /partials/table
     contains coin symbols → verify /partials/status shows "idle"
   - `test_error_recovery`: mock run_screen to fail first call, succeed second →
     verify error shown then cleared
   - `test_manual_refresh`: POST /api/refresh → verify scan triggered →
     verify results updated
   - `test_empty_scan_result`: mock run_screen returns empty df → verify
     dashboard shows "no coins" message, status is "idle" not "error"
   - `test_concurrent_requests`: fire 20 simultaneous GET /api/scan via
     asyncio.gather, all return 200 (no race condition crashes)
   - `test_nan_in_scan_produces_valid_json`: mock run_screen with df containing
     NaN circulating_pct → GET /api/scan → `json.loads()` succeeds (no NaN literal)
   - `test_first_scan_status_is_scanning`: during the first scan (before any results),
     GET /partials/status shows "scanning" badge, not "idle"

8. **ALL existing tests still pass** (48 original + all new dashboard tests).

9. **Known limitations** (documented, not bugs):
   - No runtime parameter change without restart (POST /api/config is post-MVP)
   - No individual coin detail view (table only)
   - No SSL (use reverse proxy for production network exposure)
   - `SIGTERM` shutdown only works on Linux/macOS (Windows: Ctrl+C only)
   - Two exchange instances per scan (one for map, one for OHLCV) — accepted
     inefficiency from the FROZEN constraint on screener_engine.py

### Gate Command
```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/ -v --tb=short
```

### Final Smoke Test (Manual)
```bash
cd /f/TradingScanner && .venv/Scripts/python -m quant_scanner --serve --port 8080 --refresh-interval 60
# Open http://127.0.0.1:8080 in browser
# Verify: table loads, status bar updates, refresh button works
# Wait 60s: table auto-updates via HTMX
# Ctrl+C: clean shutdown, no tracebacks
```

---

## Edge Cases & Failure Modes Registry

Every failure mode below MUST be handled (no unhandled exceptions in production):

| # | Failure Mode | Component | Expected Behavior | Tested In |
|---|---|---|---|---|
| 1 | CoinGecko API returns 429 | ingestion_engine | Backoff retry (existing) | test_ingestion |
| 2 | CoinGecko API returns 500 | ingestion_engine | Backoff retry (existing) | test_ingestion |
| 3 | CoinGecko API key invalid | ingestion_engine | Falls back to public tier | test_ingestion |
| 4 | CCXT exchange unreachable | ingestion_engine | Skip symbol, log warning | test_ingestion |
| 5 | All coins filtered out | screener_engine | Empty DataFrame (not error) | test_screener |
| 6 | Zero variance in BTC | math_engine | Beta=NaN (not inf) | test_math |
| 7 | run_screen() raises any exception | scheduler | Catch, store error, continue loop | test_scheduler |
| 8 | Two scans triggered simultaneously | scheduler | Second is ignored (Event guard) | test_scheduler |
| 9 | WebSocket client disconnects | ws_manager | Removed, others unaffected | test_ws_manager |
| 10 | WebSocket broadcast to zero clients | ws_manager | No-op (no error) | test_ws_manager |
| 11 | Browser requests /partials/table before first scan | server | Returns "Waiting for first scan..." | test_server |
| 12 | Browser requests /api/scan before first scan | server | Returns empty results JSON | test_server |
| 13 | POST /api/refresh during active scan | scheduler | Ignored (idempotent) | test_scheduler |
| 14 | Server SIGINT during active scan | scheduler | 30s timeout then force-cancel | test_integration |
| 15 | Templates directory missing | server | Returns 500 JSON error, not crash | test_server |
| 16 | Static directory missing | server | Non-fatal, CSS/JS 404s | test_server |
| 17 | Memory accumulation over 24h | scan_store | Bounded history, GC handles DFs | test_scan_store |
| 18 | Stale cache + --no-cache | ingestion_engine | Fresh fetch (existing) | test_ingestion |
| 19 | Empty DataFrame in store.update() | scan_store | Stores it, coin_count=0 | test_scan_store |
| 20 | Concurrent store.update() calls | scan_store | asyncio.Lock prevents corruption | test_scan_store |
| 21 | NaN in DataFrame → JSON response | server /api/scan | store.get_latest_as_records() converts NaN→None | test_server, test_integration |
| 22 | CDN unreachable (no internet) | templates | Local fallback in static/vendor/ | manual |
| 23 | HTMX poll + WS fire simultaneously | templates JS | JS dedup: WS refresh cancels pending poll | manual |
| 24 | POST /api/refresh spam (100 calls) | scheduler | 10s cooldown; _scanning flag prevents overlap | test_scheduler |
| 25 | Scan takes longer than refresh interval | scheduler | Sleep = max(0, interval - scan_duration) | test_scheduler |
| 26 | Port already in use | cli | Catch OSError, print friendly message | test_cli |
| 27 | Jinja2 filter receives None/NaN | templates | format_mcap(None) → "N/A", not crash | test_server |
| 28 | get_latest() mutated by caller | scan_store | Returns .copy(), original untouched | test_scan_store |
| 29 | SIGTERM on Windows | server | Does not work; only SIGINT (Ctrl+C) supported | documented limitation |

---

## Test Coverage Matrix

| Module | Test File | Test Count (est.) | Mock Strategy |
|---|---|---|---|
| server.py (routes) | test_server.py | ~18 | httpx.AsyncClient (async) + Starlette TestClient (WS) |
| scan_store.py | test_scan_store.py | ~10 | Pure unit tests (no mocks needed) |
| scheduler.py | test_scheduler.py | ~8 | AsyncMock on run_screen, Event-based sync |
| ws_manager.py | test_ws_manager.py | ~7 | Mock WebSocket objects |
| Integration | test_integration_dashboard.py | ~7 | Full app with mocked run_screen |
| cli.py (new flags) | test_cli.py | ~8 new + 2 existing | Pure unit (parse_args only) |
| **Total new tests** | | **~58** | |
| **Total with existing** | | **~106** | |

---

## Dependency Safety

### CDN Fallback Strategy
HTMX and Lightweight Charts are loaded from CDN with local fallback:
- Primary: CDN (unpkg.com) for fast delivery
- Fallback: `static/vendor/htmx.min.js` and `static/vendor/lightweight-charts.min.js`
- Without HTMX, auto-refresh is completely broken, so the local fallback is mandatory
- HTML uses: CDN script tag first, then `window.htmx || document.write(...)` fallback

### No New Async Complexity
- FastAPI uses the SAME asyncio event loop as our existing pipeline
- No thread pools, no multiprocessing, no new event loop creation
- uvicorn runs our app in a single process with a single event loop
- The scheduler is an asyncio.Task on that same loop

---

## Implementation Order (For Builder Agents)

```
DASH-001 (skeleton)     ← Must be first (installs deps)
    │
    ├── DASH-002 (store)     ← Independent
    ├── DASH-003 (scheduler) ← Independent (uses store interface)
    │
    DASH-004 (routes)        ← Depends on DASH-002 + DASH-003
    │
    DASH-005 (frontend)      ← Depends on DASH-004 (creates index.html)
    │
    DASH-006 (websocket)     ← Depends on DASH-005 (modifies index.html)
    │  > NOT parallel with DASH-005 — both touch index.html
    │
    DASH-007 (CLI)           ← Depends on DASH-006 (imports server)
    │
    DASH-008 (hardening)     ← Depends on ALL above
```

---

## Success Criteria

The dashboard is DONE when:

1. `python -m quant_scanner --serve` opens a browser-accessible dashboard at localhost:8080
2. The dashboard auto-refreshes with new scan data every 5 minutes (configurable)
3. The table shows all screening columns with correct color coding
4. The status bar updates every 10 seconds showing scan status
5. The refresh button triggers an immediate re-scan
6. WebSocket pushes update the page instantly when a scan completes
7. If the scanner errors, the dashboard shows the error and recovers on next scan
8. Ctrl+C shuts down cleanly with no tracebacks
9. `pytest tests/ -v` passes ALL tests (original 48 + ~58 new = ~106 total)
10. The `--dry-run` one-shot CLI still works exactly as before
