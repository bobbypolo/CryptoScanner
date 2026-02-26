"""Tests for the background scan scheduler.

All tests mock run_screen via unittest.mock.patch -- ZERO network calls.
Uses asyncio.Event for synchronization instead of asyncio.sleep to prevent
timing-dependent flaky tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from quant_scanner.scan_store import ScanStore
from quant_scanner.scheduler import ScanScheduler

_PATCH_TARGET = "quant_scanner.screener_engine.run_screen"


def _make_scan_df(n: int = 3) -> pd.DataFrame:
    """Build a small DataFrame mimicking run_screen() output."""
    return pd.DataFrame(
        {
            "symbol": [f"COIN{i}/USDT" for i in range(n)],
            "name": [f"Coin {i}" for i in range(n)],
            "market_cap": [50_000_000 + i * 10_000_000 for i in range(n)],
            "volume_24h": [5_000_000 + i * 1_000_000 for i in range(n)],
            "beta": [2.0 + i * 0.1 for i in range(n)],
            "correlation": [0.85 + i * 0.01 for i in range(n)],
            "kelly_fraction": [0.12 + i * 0.01 for i in range(n)],
            "circulating_pct": [0.75 + i * 0.05 for i in range(n)],
            "data_days": [59] * n,
        }
    )


async def _wait_scan_done(scheduler: ScanScheduler, timeout: float = 5.0) -> None:
    """Wait for the scheduler to finish scanning."""
    for _ in range(int(timeout / 0.01)):
        if not scheduler._scanning:
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("Scheduler still scanning after timeout")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store():
    """Return a fresh ScanStore instance."""
    return ScanStore()


@pytest.fixture()
async def scheduler(store):
    """Create a ScanScheduler with a very long interval, yield, then stop."""
    sched = ScanScheduler(store=store, interval_seconds=9999)
    yield sched
    await sched.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_scheduler_calls_run_screen(scheduler, store):
    """Start scheduler, trigger immediate scan, verify run_screen was called."""
    called_event = asyncio.Event()

    async def _side_effect(**kwargs):
        called_event.set()
        return _make_scan_df()

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        await scheduler.start()
        await scheduler.trigger_now()
        await asyncio.wait_for(called_event.wait(), timeout=5)
        await _wait_scan_done(scheduler)
        mock_run_screen.assert_called()
        await scheduler.stop()


async def test_scheduler_stores_result(scheduler, store):
    """After a scan, store.get_latest() should contain the DataFrame."""
    called_event = asyncio.Event()
    mock_df = _make_scan_df(4)

    async def _side_effect(**kwargs):
        called_event.set()
        return mock_df

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        await scheduler.start()
        await scheduler.trigger_now()
        await asyncio.wait_for(called_event.wait(), timeout=5)
        await _wait_scan_done(scheduler)
        await scheduler.stop()

    latest = store.get_latest()
    assert latest is not None
    assert len(latest) == 4


async def test_scheduler_survives_exception(scheduler, store):
    """run_screen raises RuntimeError; scheduler continues running."""
    error_event = asyncio.Event()
    success_event = asyncio.Event()
    call_count = 0

    async def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            error_event.set()
            raise RuntimeError("API down")
        success_event.set()
        return _make_scan_df()

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        await scheduler.start()
        await scheduler.trigger_now()
        await asyncio.wait_for(error_event.wait(), timeout=5)
        await _wait_scan_done(scheduler)

        status = store.get_status()
        assert status["status"] == "error"
        assert "API down" in status["error"]

        # Reset cooldown so we can trigger again
        scheduler._last_trigger_time = 0

        # Trigger a second scan that succeeds
        await scheduler.trigger_now()
        await asyncio.wait_for(success_event.wait(), timeout=5)
        await _wait_scan_done(scheduler)

        status = store.get_status()
        assert status["status"] == "idle"
        assert status["error"] is None
        await scheduler.stop()


async def test_scheduler_stop_clean(store):
    """Start then immediately stop; verify task is None or done."""
    with patch(_PATCH_TARGET, new_callable=AsyncMock) as mock_run_screen:
        mock_run_screen.return_value = _make_scan_df()
        sched = ScanScheduler(store=store, interval_seconds=9999)
        await sched.start()
        await sched.stop()

    assert sched._task is None or sched._task.done()


async def test_trigger_now(scheduler, store):
    """trigger_now() causes immediate scan without waiting for long interval."""
    called_event = asyncio.Event()

    async def _side_effect(**kwargs):
        called_event.set()
        return _make_scan_df()

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        await scheduler.start()
        # The interval is 9999s, so without trigger_now it would never fire
        await scheduler.trigger_now()
        await asyncio.wait_for(called_event.wait(), timeout=5)
        await _wait_scan_done(scheduler)
        mock_run_screen.assert_called()
        await scheduler.stop()


async def test_scheduler_start_idempotent(scheduler, store):
    """Calling start() twice creates only one background task."""
    with patch(_PATCH_TARGET, new_callable=AsyncMock) as mock_run_screen:
        mock_run_screen.return_value = _make_scan_df()
        await scheduler.start()
        task1 = scheduler._task
        await scheduler.start()  # second call
        task2 = scheduler._task
        assert task1 is task2
        await scheduler.stop()


async def test_scan_sets_status(scheduler, store):
    """Status is 'scanning' during scan and 'idle' after."""
    hold_event = asyncio.Event()
    scanning_observed = asyncio.Event()

    async def _side_effect(**kwargs):
        scanning_observed.set()
        await hold_event.wait()
        return _make_scan_df()

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        await scheduler.start()
        await scheduler.trigger_now()

        # Wait until run_screen is executing (scan is in progress)
        await asyncio.wait_for(scanning_observed.wait(), timeout=5)

        status = store.get_status()
        assert status["status"] == "scanning"

        # Release the scan
        hold_event.set()
        await _wait_scan_done(scheduler)

        status = store.get_status()
        assert status["status"] == "idle"
        await scheduler.stop()


async def test_scheduler_passes_kwargs(store):
    """scan_kwargs are forwarded to run_screen()."""
    called_event = asyncio.Event()
    captured_kwargs: dict = {}

    async def _side_effect(**kwargs):
        captured_kwargs.update(kwargs)
        called_event.set()
        return _make_scan_df()

    with patch(_PATCH_TARGET) as mock_run_screen:
        mock_run_screen.side_effect = _side_effect
        custom_kwargs = {"exchange_id": "kraken", "min_beta": 2.0}
        sched = ScanScheduler(
            store=store,
            interval_seconds=9999,
            scan_kwargs=custom_kwargs,
        )
        await sched.start()
        await sched.trigger_now()
        await asyncio.wait_for(called_event.wait(), timeout=5)
        await _wait_scan_done(sched)
        await sched.stop()

    assert captured_kwargs["exchange_id"] == "kraken"
    assert captured_kwargs["min_beta"] == 2.0
