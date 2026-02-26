"""Tests for the FastAPI server skeleton and DASH-004 routes."""

import json
import math
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
import httpx

from quant_scanner import __version__
from quant_scanner.server import (
    app,
    lifespan,
    _DEFAULT_CONFIG,
    _server_config,
    format_mcap,
    format_beta,
    format_pct,
    format_volume,
)


# ---------------------------------------------------------------------------
# Autouse fixture: reset server config to prevent test pollution
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_server_config():
    """Reset _server_config to defaults before and after each test."""
    _server_config.clear()
    _server_config.update({**_DEFAULT_CONFIG})
    yield
    _server_config.clear()
    _server_config.update({**_DEFAULT_CONFIG})


# ---------------------------------------------------------------------------
# Fixture: httpx.AsyncClient with mocked run_screen
# ---------------------------------------------------------------------------


def _make_mock_df(n: int = 3) -> pd.DataFrame:
    """Create a small test DataFrame mimicking run_screen output."""
    return pd.DataFrame(
        {
            "symbol": [f"COIN{i}" for i in range(n)],
            "name": [f"Coin {i}" for i in range(n)],
            "market_cap": [50_000_000 + i * 10_000_000 for i in range(n)],
            "total_volume": [5_000_000 + i * 1_000_000 for i in range(n)],
            "beta": [1.5 + i * 0.3 for i in range(n)],
            "correlation": [0.7 + i * 0.05 for i in range(n)],
            "kelly_fraction": [0.05 + i * 0.02 for i in range(n)],
            "amihud": [1e-8 + i * 1e-9 for i in range(n)],
            "circulating_pct": [0.5 + i * 0.1 for i in range(n)],
        }
    )


@pytest.fixture
async def client():
    """Yield an httpx.AsyncClient wired to the FastAPI app via ASGITransport.

    Manually enters the lifespan context to trigger startup/shutdown events,
    since httpx.ASGITransport does not invoke ASGI lifespan on its own.

    Mocks run_screen to prevent any network calls.
    """
    mock_df = _make_mock_df()
    with patch(
        "quant_scanner.screener_engine.run_screen",
        new_callable=AsyncMock,
        return_value=mock_df,
    ):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                yield c


# ---------------------------------------------------------------------------
# Original DASH-001 tests (kept intact)
# ---------------------------------------------------------------------------


async def test_health_endpoint(client):
    """GET /api/health returns 200 with status 'ok'."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


async def test_health_has_uptime(client):
    """GET /api/health response contains uptime_seconds >= 0."""
    response = await client.get("/api/health")
    data = response.json()
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


async def test_health_has_version(client):
    """GET /api/health response version matches __version__."""
    response = await client.get("/api/health")
    data = response.json()
    assert "version" in data
    assert data["version"] == __version__


async def test_favicon_no_404(client):
    """GET /favicon.ico returns 204, not 404."""
    response = await client.get("/favicon.ico")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# DASH-004: Route tests
# ---------------------------------------------------------------------------


async def test_index_returns_html(client):
    """GET / returns 200 with text/html content type."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_index_contains_htmx(client):
    """GET / response body contains 'htmx.org'."""
    response = await client.get("/")
    assert "htmx.org" in response.text


async def test_partials_table_returns_200(client):
    """GET /partials/table returns 200."""
    response = await client.get("/partials/table")
    assert response.status_code == 200


async def test_partials_status_returns_200(client):
    """GET /partials/status returns 200."""
    response = await client.get("/partials/status")
    assert response.status_code == 200


async def test_api_scan_json_structure(client):
    """GET /api/scan returns JSON with expected keys."""
    response = await client.get("/api/scan")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "count" in data
    assert "scanned_at" in data
    assert "status" in data


async def test_api_scan_empty_before_first_scan(client):
    """Before any scan runs, GET /api/scan returns count=0 and results=[]."""
    # The client fixture starts the scheduler but the scan may or may not have
    # run yet. We create a fresh client with a very long interval so no scan
    # fires during the test.
    _server_config["interval_seconds"] = 99999
    mock_df = _make_mock_df()
    with patch(
        "quant_scanner.screener_engine.run_screen",
        new_callable=AsyncMock,
        return_value=mock_df,
    ) as mock_run:
        # Make run_screen block forever so the first scan never completes
        import asyncio

        never_done = asyncio.Event()

        async def block_forever(**kwargs):
            await never_done.wait()
            return mock_df

        mock_run.side_effect = block_forever

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                # Query immediately while first scan is still "running"
                response = await c.get("/api/scan")
                data = response.json()
                assert data["count"] == 0
                assert data["results"] == []
                # Release the blocked scan so cleanup can proceed
                never_done.set()


async def test_api_scan_nan_safe(client):
    """After storing a scan with NaN, GET /api/scan returns valid JSON."""
    # Manually update the store with a DataFrame containing NaN
    store = app.state.store
    df_with_nan = pd.DataFrame(
        {
            "symbol": ["TESTCOIN"],
            "name": ["Test Coin"],
            "market_cap": [50_000_000.0],
            "total_volume": [5_000_000.0],
            "beta": [1.5],
            "correlation": [0.8],
            "kelly_fraction": [0.1],
            "amihud": [1e-8],
            "circulating_pct": [float("nan")],
        }
    )
    await store.update(df_with_nan)

    response = await client.get("/api/scan")
    assert response.status_code == 200

    # Verify the response is valid JSON (json.loads must succeed)
    body = response.text
    parsed = json.loads(body)

    # Verify no NaN literal in the response body
    assert "NaN" not in body
    assert "nan" not in body

    # Verify the NaN was converted to None (null in JSON)
    results = parsed["results"]
    assert len(results) == 1
    assert results[0]["circulating_pct"] is None


async def test_api_history_returns_list(client):
    """GET /api/history returns 200 with JSON list."""
    response = await client.get("/api/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_api_refresh_returns_202(client):
    """POST /api/refresh returns 202."""
    response = await client.post("/api/refresh")
    assert response.status_code == 202
    data = response.json()
    assert "message" in data


async def test_health_includes_scanner_status(client):
    """GET /api/health response includes 'scanner' key with 'status' field."""
    response = await client.get("/api/health")
    data = response.json()
    assert "scanner" in data
    assert "status" in data["scanner"]


# ---------------------------------------------------------------------------
# DASH-004: Jinja2 filter tests
# ---------------------------------------------------------------------------


def test_format_mcap_none():
    """Jinja2 format_mcap filter returns 'N/A' for None input."""
    assert format_mcap(None) == "N/A"


def test_format_mcap_nan():
    """Jinja2 format_mcap filter returns 'N/A' for NaN input."""
    assert format_mcap(float("nan")) == "N/A"


# ---------------------------------------------------------------------------
# DASH-005: Frontend styling, color coding & chart placeholder tests
# ---------------------------------------------------------------------------


async def test_index_contains_table_tag(client):
    """GET / response contains '<table'."""
    response = await client.get("/")
    assert "<table" in response.text


async def test_index_loads_stylesheet(client):
    """GET / response contains '/static/style.css'."""
    response = await client.get("/")
    assert "/static/style.css" in response.text


async def test_static_css_served(client):
    """GET /static/style.css returns 200 with text/css content type."""
    response = await client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


async def test_partials_table_has_color_classes(client):
    """After storing a scan with beta=2.5, GET /partials/table contains 'beta-high'."""
    store = app.state.store
    df_high_beta = pd.DataFrame(
        {
            "symbol": ["HIGHBETA"],
            "name": ["High Beta Coin"],
            "market_cap": [80_000_000.0],
            "total_volume": [10_000_000.0],
            "beta": [2.5],
            "correlation": [0.9],
            "kelly_fraction": [0.2],
            "amihud": [5e-9],
            "circulating_pct": [0.65],
        }
    )
    await store.update(df_high_beta)

    response = await client.get("/partials/table")
    assert response.status_code == 200
    assert "beta-high" in response.text


async def test_partials_table_empty_message():
    """Before any scan, GET /partials/table contains 'Waiting for first scan'."""
    _server_config["interval_seconds"] = 99999
    mock_df = _make_mock_df()
    with patch(
        "quant_scanner.screener_engine.run_screen",
        new_callable=AsyncMock,
        return_value=mock_df,
    ) as mock_run:
        import asyncio

        never_done = asyncio.Event()

        async def block_forever(**kwargs):
            await never_done.wait()
            return mock_df

        mock_run.side_effect = block_forever

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                response = await c.get("/partials/table")
                assert response.status_code == 200
                assert "Waiting for first scan" in response.text
                never_done.set()


# ---------------------------------------------------------------------------
# DASH-006: WebSocket endpoint integration test
# ---------------------------------------------------------------------------


def test_ws_endpoint_connects():
    """WebSocket /ws/updates accepts connections (Starlette TestClient, sync).

    Uses Starlette TestClient because httpx.ASGITransport cannot test WebSocket.
    Must mock run_screen to prevent network calls during lifespan startup.
    """
    from starlette.testclient import TestClient

    with patch(
        "quant_scanner.screener_engine.run_screen",
        new_callable=AsyncMock,
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/updates") as ws:
                # Connection established successfully
                pass
