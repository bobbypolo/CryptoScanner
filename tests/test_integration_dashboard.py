"""Integration tests for the full dashboard lifecycle.

All tests mock run_screen via unittest.mock.patch -- ZERO network calls.
Uses httpx.AsyncClient with httpx.ASGITransport(app=app) for async testing.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
import httpx

from quant_scanner.server import app, configure, lifespan, _DEFAULT_CONFIG, _server_config

_PATCH_TARGET = "quant_scanner.screener_engine.run_screen"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scan_df(n: int = 3) -> pd.DataFrame:
    """Build a mock DataFrame mimicking run_screen() output."""
    return pd.DataFrame([
        {
            "symbol": f"COIN{i}/USDT",
            "name": f"Coin {i}",
            "market_cap": 50_000_000 + i * 10_000_000,
            "volume_24h": 5_000_000,
            "beta": 2.5 - i * 0.3,
            "correlation": 0.9 - i * 0.05,
            "kelly_fraction": 0.15 - i * 0.03,
            "circulating_pct": 0.8 if i % 2 == 0 else float("nan"),
            "data_days": 59,
        }
        for i in range(n)
    ])


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
# Integration tests
# ---------------------------------------------------------------------------


async def test_full_lifecycle():
    """Full lifecycle: health -> trigger scan -> results -> partials."""
    mock_df = make_scan_df(3)
    _server_config["interval_seconds"] = 9999

    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=mock_df):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Health check returns ok
                resp = await client.get("/api/health")
                assert resp.status_code == 200
                health = resp.json()
                assert health["status"] == "ok"

                # Trigger scan
                resp = await client.post("/api/refresh")
                assert resp.status_code == 202

                # Wait for scan to complete
                await asyncio.sleep(0.5)

                # GET /api/scan returns 3 results
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["count"] == 3
                assert len(data["results"]) == 3

                # GET /partials/table contains COIN0
                resp = await client.get("/partials/table")
                assert resp.status_code == 200
                assert "COIN0" in resp.text

                # GET /partials/status contains 'idle'
                resp = await client.get("/partials/status")
                assert resp.status_code == 200
                assert "idle" in resp.text.lower()


async def test_error_recovery():
    """First scan fails, second succeeds -- error clears."""
    _server_config["interval_seconds"] = 9999
    call_count = 0
    first_scan_done = asyncio.Event()
    second_scan_done = asyncio.Event()

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            first_scan_done.set()
            raise RuntimeError("API down")
        second_scan_done.set()
        return make_scan_df(2)

    with patch(_PATCH_TARGET, new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = _side_effect

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # The initial scan from _loop fires automatically (call_count=1, fails)
                await asyncio.wait_for(first_scan_done.wait(), timeout=5)
                # Give the scheduler a moment to record the error
                await asyncio.sleep(0.1)

                # Verify error status
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["status"] == "error"

                # Reset cooldown so we can trigger again
                app.state.scheduler._last_trigger_time = 0

                # Trigger second scan (will succeed)
                await client.post("/api/refresh")
                await asyncio.wait_for(second_scan_done.wait(), timeout=5)
                await asyncio.sleep(0.1)

                # Verify results appear and error is cleared
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["count"] == 2
                assert len(data["results"]) == 2
                assert data["status"] == "idle"


async def test_manual_refresh():
    """Manual refresh triggers scan without waiting for long interval."""
    _server_config["interval_seconds"] = 9999
    mock_df = make_scan_df(3)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=mock_df):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # POST /api/refresh
                resp = await client.post("/api/refresh")
                assert resp.status_code == 202

                # Wait briefly for scan to complete
                await asyncio.sleep(0.5)

                # Verify results are available
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["count"] == 3
                assert len(data["results"]) == 3


async def test_empty_scan_result():
    """Empty DataFrame is not an error -- shows 'No coins' message."""
    _server_config["interval_seconds"] = 9999
    empty_df = pd.DataFrame(columns=[
        "symbol", "name", "market_cap", "volume_24h", "beta",
        "correlation", "kelly_fraction", "circulating_pct", "data_days",
    ])

    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=empty_df):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Trigger scan
                await client.post("/api/refresh")
                await asyncio.sleep(0.5)

                # GET /api/scan returns count=0
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["count"] == 0

                # GET /partials/table contains 'No coins'
                resp = await client.get("/partials/table")
                assert "No coins" in resp.text

                # Status is 'idle', NOT 'error'
                resp = await client.get("/api/scan")
                data = resp.json()
                assert data["status"] == "idle"


async def test_concurrent_requests():
    """20 simultaneous GET /api/scan all return 200."""
    _server_config["interval_seconds"] = 9999
    mock_df = make_scan_df(3)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=mock_df):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Trigger scan and wait for data
                await client.post("/api/refresh")
                await asyncio.sleep(0.5)

                # Fire 20 simultaneous requests
                tasks = [client.get("/api/scan") for _ in range(20)]
                responses = await asyncio.gather(*tasks)

                # All return 200
                for resp in responses:
                    assert resp.status_code == 200


async def test_nan_in_scan_produces_valid_json():
    """NaN in scan results produces valid JSON (no NaN literal)."""
    _server_config["interval_seconds"] = 9999
    # make_scan_df already contains NaN in circulating_pct for odd indices
    mock_df = make_scan_df(3)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=mock_df):
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Trigger scan and wait
                await client.post("/api/refresh")
                await asyncio.sleep(0.5)

                # GET /api/scan
                resp = await client.get("/api/scan")
                body = resp.text

                # json.loads must succeed
                parsed = json.loads(body)
                assert parsed is not None

                # 'NaN' string literal must NOT appear
                assert "NaN" not in body


async def test_first_scan_shows_scanning_status():
    """During a scan, GET /partials/status shows 'scanning'."""
    _server_config["interval_seconds"] = 9999
    hold_event = asyncio.Event()

    async def _slow_scan(**kwargs):
        await hold_event.wait()
        return make_scan_df(3)

    with patch(_PATCH_TARGET, new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = _slow_scan

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # Trigger scan (it will block on hold_event)
                await client.post("/api/refresh")

                # Give the scheduler a moment to start the scan
                await asyncio.sleep(0.2)

                # While scan is running, status should be 'scanning'
                resp = await client.get("/partials/status")
                assert "scanning" in resp.text.lower()

                # Release the scan
                hold_event.set()
                await asyncio.sleep(0.3)

                # After completion, status should be 'idle'
                resp = await client.get("/partials/status")
                assert "idle" in resp.text.lower()
