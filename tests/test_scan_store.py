"""Tests for ScanStore -- coroutine-safe in-memory data store."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from quant_scanner.scan_store import ScanStore


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_df(n: int = 3, beta_values: list[float] | None = None) -> pd.DataFrame:
    """Create a simple DataFrame with *n* rows for testing."""
    data = {
        "symbol": [f"COIN{i}" for i in range(n)],
        "name": [f"Coin {i}" for i in range(n)],
        "market_cap": [50_000_000 + i * 10_000_000 for i in range(n)],
        "beta": beta_values if beta_values is not None else [1.5 + 0.1 * i for i in range(n)],
        "correlation": [0.8 + 0.01 * i for i in range(n)],
        "circulating_pct": [0.5 + 0.05 * i for i in range(n)],
    }
    return pd.DataFrame(data)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_state():
    """New store has None latest, empty history, status='idle', scan_count=0."""
    store = ScanStore()
    assert store.get_latest() is None
    assert store.get_history() == []
    status = store.get_status()
    assert status["status"] == "idle"
    assert status["scan_count"] == 0


@pytest.mark.asyncio
async def test_update_stores_dataframe():
    """After update(), get_latest() returns df with same length and columns but is a DIFFERENT object."""
    store = ScanStore()
    original = _make_df(5)
    await store.update(original)

    latest = store.get_latest()
    assert latest is not None
    assert len(latest) == len(original)
    assert list(latest.columns) == list(original.columns)
    # Copy check: the returned object must NOT be the same as the original
    assert id(latest) != id(original)


@pytest.mark.asyncio
async def test_update_records_history():
    """After 3 updates with different dfs, get_history(3) returns 3 entries with correct coin_counts."""
    store = ScanStore()
    for n in (2, 4, 6):
        await store.update(_make_df(n))

    history = store.get_history(3)
    assert len(history) == 3
    assert history[0]["coin_count"] == 2
    assert history[1]["coin_count"] == 4
    assert history[2]["coin_count"] == 6


@pytest.mark.asyncio
async def test_history_limit():
    """Create store with max_history=5, do 8 updates, verify len(get_history(10)) == 5."""
    store = ScanStore(max_history=5)
    for i in range(8):
        await store.update(_make_df(i + 1))

    history = store.get_history(10)
    assert len(history) == 5


@pytest.mark.asyncio
async def test_status_after_update():
    """scan_count increments by 1 per update, coin_count matches latest df length, last_scan_at is not None."""
    store = ScanStore()
    await store.update(_make_df(3))
    status = store.get_status()
    assert status["scan_count"] == 1
    assert status["coin_count"] == 3
    assert status["last_scan_at"] is not None

    await store.update(_make_df(7))
    status = store.get_status()
    assert status["scan_count"] == 2
    assert status["coin_count"] == 7


@pytest.mark.asyncio
async def test_error_handling():
    """set_error('API down') sets status='error' and error='API down'; clear_error() resets."""
    store = ScanStore()
    store.set_error("API down")
    status = store.get_status()
    assert status["status"] == "error"
    assert status["error"] == "API down"

    store.clear_error()
    status = store.get_status()
    assert status["status"] == "idle"
    assert status["error"] is None


@pytest.mark.asyncio
async def test_concurrent_updates():
    """Use asyncio.gather to run 10 update() calls simultaneously, verify scan_count == 10."""
    store = ScanStore()
    dfs = [_make_df(i + 1) for i in range(10)]
    await asyncio.gather(*(store.update(df) for df in dfs))

    status = store.get_status()
    assert status["scan_count"] == 10
    # No corruption: latest should be a valid DataFrame
    latest = store.get_latest()
    assert latest is not None
    assert len(latest) > 0


@pytest.mark.asyncio
async def test_empty_dataframe_update():
    """Update with empty df sets coin_count=0, still records in history with coin_count=0."""
    store = ScanStore()
    await store.update(pd.DataFrame())

    status = store.get_status()
    assert status["coin_count"] == 0

    history = store.get_history(1)
    assert len(history) == 1
    assert history[0]["coin_count"] == 0


@pytest.mark.asyncio
async def test_snapshot_contains_top_beta():
    """Update with df containing beta column, verify history entry has top_beta_symbol matching highest beta."""
    store = ScanStore()
    df = _make_df(3, beta_values=[1.2, 2.8, 1.5])
    await store.update(df)

    history = store.get_history(1)
    assert len(history) == 1
    # COIN1 has the highest beta (2.8)
    assert history[0]["top_beta_symbol"] == "COIN1"


@pytest.mark.asyncio
async def test_get_latest_returns_copy():
    """get_latest() returns a new copy each time; modifying it does not affect the store."""
    store = ScanStore()
    await store.update(_make_df(3))

    copy1 = store.get_latest()
    assert copy1 is not None
    # Mutate the returned copy
    copy1.drop(copy1.index, inplace=True)
    assert len(copy1) == 0

    # Store should be unaffected
    copy2 = store.get_latest()
    assert copy2 is not None
    assert len(copy2) == 3


@pytest.mark.asyncio
async def test_get_latest_as_records_nan_safe():
    """Update with df containing np.nan in circulating_pct, verify NaN becomes None and json.dumps succeeds."""
    store = ScanStore()
    df = _make_df(2)
    df.loc[0, "circulating_pct"] = np.nan
    await store.update(df)

    records = store.get_latest_as_records()
    assert isinstance(records, list)
    assert len(records) == 2

    # The NaN field should be None, not float('nan')
    assert records[0]["circulating_pct"] is None

    # json.dumps MUST succeed (NaN would cause invalid JSON)
    json_str = json.dumps(records)
    assert isinstance(json_str, str)
    # Verify no NaN literal snuck through
    assert "NaN" not in json_str
