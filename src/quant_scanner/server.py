"""FastAPI application for the Crypto Quant Scanner dashboard."""

import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from quant_scanner import __version__
from quant_scanner.scan_store import ScanStore
from quant_scanner.scheduler import ScanScheduler
from quant_scanner.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server configuration (module-level, reset by test fixtures)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "scan_kwargs": {},
    "interval_seconds": 300,
}

_server_config: dict = {**_DEFAULT_CONFIG}


def configure(**kwargs) -> None:
    """Update server configuration.

    Accepts any keys from _DEFAULT_CONFIG. Unknown keys are stored too,
    allowing forward-compatible extension.
    """
    _server_config.update(kwargs)


# ---------------------------------------------------------------------------
# Jinja2 setup
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

if _TEMPLATES_DIR.is_dir():
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
else:
    logger.warning("Templates directory not found: %s", _TEMPLATES_DIR)
    templates = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------


def _is_nan(value) -> bool:
    """Check if a value is NaN, safely handling non-float types."""
    try:
        return math.isnan(value)
    except (TypeError, ValueError):
        return False


def format_mcap(value) -> str:
    """Format a market cap value: 45000000 -> '$45.0M', None/NaN -> 'N/A'."""
    if value is None or _is_nan(value):
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def format_volume(value) -> str:
    """Format volume: same pattern as format_mcap."""
    return format_mcap(value)


def format_pct(value) -> str:
    """Format a decimal as percentage: 0.78 -> '78.0%', None/NaN -> 'N/A'."""
    if value is None or _is_nan(value):
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{v * 100:.1f}%"


def format_beta(value) -> str:
    """Format beta: 2.34 -> '2.34', None/NaN -> 'N/A'."""
    if value is None or _is_nan(value):
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{v:.2f}"


# Register filters on the Jinja2 environment
if templates is not None:
    templates.env.filters["format_mcap"] = format_mcap
    templates.env.filters["format_volume"] = format_volume
    templates.env.filters["format_pct"] = format_pct
    templates.env.filters["format_beta"] = format_beta


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Async lifespan context manager for startup/shutdown."""
    app.state.start_time = time.monotonic()

    # Create ScanStore
    store = ScanStore()
    app.state.store = store

    # Create WebSocket connection manager
    ws_manager = ConnectionManager()
    app.state.ws_manager = ws_manager

    # Create and start ScanScheduler (with ws_manager for push updates)
    scheduler = ScanScheduler(
        store=store,
        interval_seconds=_server_config["interval_seconds"],
        scan_kwargs=_server_config.get("scan_kwargs", {}),
        ws_manager=ws_manager,
    )
    app.state.scheduler = scheduler
    await scheduler.start()

    # Structured startup logging
    scan_kw = _server_config.get("scan_kwargs", {})
    logger.info(
        "Dashboard started: host=%s, port=%s, refresh_interval=%ds, "
        "exchange=%s, min_mcap=%s, max_mcap=%s, min_beta=%s, "
        "min_correlation=%s, min_volume=%s, use_cache=%s",
        _server_config.get("host", "127.0.0.1"),
        _server_config.get("port", 8080),
        _server_config["interval_seconds"],
        scan_kw.get("exchange_id", "binance"),
        scan_kw.get("min_mcap", 20_000_000),
        scan_kw.get("max_mcap", 150_000_000),
        scan_kw.get("min_beta", 1.5),
        scan_kw.get("min_correlation", 0.7),
        scan_kw.get("min_volume", 1_000_000),
        scan_kw.get("use_cache", True),
    )

    yield

    # Shutdown: stop scheduler
    await scheduler.stop()


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Crypto Quant Scanner",
    version=__version__,
    lifespan=lifespan,
)

# Mount static files (only if directory exists)
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
else:
    logger.warning("Static directory not found: %s — skipping mount", _STATIC_DIR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def index(request: Request):
    """Render the main dashboard page."""
    store: ScanStore = request.app.state.store
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "results": store.get_latest_as_records(),
            "status": store.get_status(),
            "has_scanned": store.get_latest() is not None,
            "config": _server_config["scan_kwargs"],
        },
    )


@app.get("/partials/table")
async def partials_table(request: Request):
    """Render the scan results table fragment for HTMX swap."""
    store: ScanStore = request.app.state.store
    return templates.TemplateResponse(
        request,
        "partials/table.html",
        {
            "results": store.get_latest_as_records(),
            "has_scanned": store.get_latest() is not None,
        },
    )


@app.get("/partials/status")
async def partials_status(request: Request):
    """Render the status bar fragment for HTMX swap."""
    store: ScanStore = request.app.state.store
    return templates.TemplateResponse(
        request,
        "partials/status.html",
        {
            "status": store.get_status(),
        },
    )


@app.get("/api/scan")
async def api_scan(request: Request):
    """Return latest scan results as JSON (NaN-safe)."""
    store: ScanStore = request.app.state.store
    status = store.get_status()
    records = store.get_latest_as_records()
    return JSONResponse(
        content={
            "results": records,
            "count": len(records),
            "scanned_at": status["last_scan_at"],
            "status": status["status"],
        }
    )


@app.get("/api/history")
async def api_history(request: Request):
    """Return scan history as JSON list."""
    store: ScanStore = request.app.state.store
    return JSONResponse(content=store.get_history())


@app.post("/api/refresh")
async def api_refresh(request: Request):
    """Trigger an immediate re-scan and return 202 Accepted."""
    scheduler: ScanScheduler = request.app.state.scheduler
    await scheduler.trigger_now()
    return JSONResponse(
        status_code=202,
        content={"message": "Scan triggered"},
    )


@app.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket):
    """WebSocket endpoint for live push updates.

    Accepts the connection via the manager, then loops receiving messages
    (keep-alive). On disconnect, removes the client from the manager.
    """
    manager: ConnectionManager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive by waiting for messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/health")
async def health(request: Request):
    """Return health status with version, uptime, and scanner status."""
    uptime = time.monotonic() - request.app.state.start_time
    store: ScanStore = request.app.state.store
    ws_manager: ConnectionManager = request.app.state.ws_manager
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": uptime,
        "scanner": store.get_status(),
        "websocket_clients": ws_manager.client_count(),
    }


@app.get("/favicon.ico")
async def favicon():
    """Return 204 No Content to prevent browser 404 log spam."""
    return Response(status_code=204)
