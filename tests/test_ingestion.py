"""Tests for quant_scanner.ingestion_engine — CoinGecko universe fetching,
CCXT OHLCV fetching, symbol mapping, and timestamp alignment."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from quant_scanner.ingestion_engine import (
    STABLECOINS,
    WRAPPED_TOKENS,
    align_to_btc_index,
    fetch_historical_data,
    fetch_universe,
    map_coingecko_to_ccxt,
    ohlcv_to_dataframe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(data: list[dict], status: int = 200):
    """Create a mock aiohttp response that behaves as an async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)

    # Make the response work as an async context manager (async with session.get(...))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_mock_session(pages: dict[int, list[dict]]):
    """Create a mock aiohttp.ClientSession whose .get() returns page-specific data.

    ``pages`` maps page number (1-4) to the list of coins for that page.
    """

    def _get_side_effect(url, **kwargs):
        # Extract the page number from the URL query string
        for part in url.split("&"):
            if part.startswith("page="):
                page_num = int(part.split("=")[1])
                return _make_mock_response(pages.get(page_num, []))
        return _make_mock_response([])

    session = MagicMock()
    session.get = MagicMock(side_effect=_get_side_effect)

    # Make session work as an async context manager
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_market_cap_filter(mock_coingecko_response):
    """Coins outside the $20M-$150M range and those with null market_cap
    are excluded; only in-range coins survive."""

    # Put all coins on page 1, empty pages for 2-4
    mock_session = _make_mock_session({
        1: mock_coingecko_response,
        2: [],
        3: [],
        4: [],
    })

    with patch("quant_scanner.ingestion_engine.aiohttp.ClientSession", return_value=mock_session):
        result = await fetch_universe(use_cache=False)

    # Extract the symbols that survived
    symbols = {coin["symbol"] for coin in result}

    # Valid in-range coins should survive
    assert "abc" in symbols, "abc (50M) should be in results"
    assert "xyz" in symbols, "xyz (100M) should be in results"

    # Boundary coins should survive (20M and 150M are inclusive)
    assert "blow" in symbols, "blow (exactly 20M) should be in results"
    assert "bhigh" in symbols, "bhigh (exactly 150M) should be in results"

    # Out-of-range coins must NOT be present
    assert "tiny" not in symbols, "tiny (10M) should be excluded"
    assert "mega" not in symbols, "mega (200M) should be excluded"

    # Null market_cap coin must NOT be present
    assert "nullcap" not in symbols, "null market_cap should be excluded"

    # Zero market_cap coin must NOT be present (0 < 20M)
    assert "zerocap" not in symbols, "zero market_cap should be excluded"

    # Stablecoins and wrapped tokens are also filtered, but that's
    # verified in their own dedicated tests below.


async def test_stablecoin_exclusion(mock_coingecko_response):
    """Stablecoins (e.g., USDT, USDC) inside the market-cap range are excluded."""

    mock_session = _make_mock_session({
        1: mock_coingecko_response,
        2: [],
        3: [],
        4: [],
    })

    with patch("quant_scanner.ingestion_engine.aiohttp.ClientSession", return_value=mock_session):
        result = await fetch_universe(use_cache=False)

    symbols = {coin["symbol"].upper() for coin in result}

    # USDT is in the fixture at 80M (in range) but must be excluded
    assert "USDT" not in symbols, "USDT should be excluded as a stablecoin"
    # USDC is in the fixture at 60M (in range) but must be excluded
    assert "USDC" not in symbols, "USDC should be excluded as a stablecoin"

    # Verify the constants contain the minimum required stablecoins
    for stable in ("USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDP", "GUSD"):
        assert stable in STABLECOINS, f"{stable} should be in STABLECOINS"


async def test_wrapped_token_exclusion(mock_coingecko_response):
    """Wrapped tokens (e.g., WBTC, WETH) inside the market-cap range are excluded."""

    mock_session = _make_mock_session({
        1: mock_coingecko_response,
        2: [],
        3: [],
        4: [],
    })

    with patch("quant_scanner.ingestion_engine.aiohttp.ClientSession", return_value=mock_session):
        result = await fetch_universe(use_cache=False)

    symbols = {coin["symbol"].upper() for coin in result}

    # WBTC is in the fixture at 80M (in range) but must be excluded
    assert "WBTC" not in symbols, "WBTC should be excluded as a wrapped token"
    # WETH is in the fixture at 70M (in range) but must be excluded
    assert "WETH" not in symbols, "WETH should be excluded as a wrapped token"

    # Verify the constants contain the minimum required wrapped tokens
    for wrapped in ("WBTC", "WETH", "WBNB", "STETH", "WSTETH"):
        assert wrapped in WRAPPED_TOKENS, f"{wrapped} should be in WRAPPED_TOKENS"


async def test_cache_saves_and_loads(tmp_path, mock_coingecko_response):
    """Cache is written to disk and successfully loaded on subsequent calls."""

    cache_file = tmp_path / "coingecko_universe.json"

    # --- 1. First call: fetch from "API" and write cache ---
    mock_session = _make_mock_session({
        1: mock_coingecko_response,
        2: [],
        3: [],
        4: [],
    })

    with (
        patch("quant_scanner.ingestion_engine.aiohttp.ClientSession", return_value=mock_session),
        patch("quant_scanner.ingestion_engine._CACHE_PATH", str(cache_file)),
        patch("quant_scanner.ingestion_engine.os.makedirs"),
    ):
        first_result = await fetch_universe(use_cache=True)

    # Verify cache file was written
    assert cache_file.exists(), "Cache file should have been created"

    # Verify cache structure
    with open(cache_file, "r", encoding="utf-8") as fh:
        cache_data = json.load(fh)
    assert "fetched_at" in cache_data, "Cache must have fetched_at timestamp"
    assert "coins" in cache_data, "Cache must have coins list"

    # Verify the cached data matches the returned result
    assert len(cache_data["coins"]) == len(first_result)

    # --- 2. Second call: should read from cache (no HTTP) ---
    # Create a new session mock that would fail if called, proving cache was used
    fail_session = MagicMock()
    fail_session.get = MagicMock(side_effect=AssertionError("Should not fetch from API"))

    with (
        patch("quant_scanner.ingestion_engine.aiohttp.ClientSession", return_value=fail_session),
        patch("quant_scanner.ingestion_engine._CACHE_PATH", str(cache_file)),
    ):
        second_result = await fetch_universe(use_cache=True)

    # Results should match
    assert len(second_result) == len(first_result)
    first_symbols = {c["symbol"] for c in first_result}
    second_symbols = {c["symbol"] for c in second_result}
    assert first_symbols == second_symbols, "Cached results should match original"


# ---------------------------------------------------------------------------
# QUANT-003 Tests: OHLCV DataFrame, Timestamp Alignment, Symbol Mapping
# ---------------------------------------------------------------------------


def test_ohlcv_dataframe_format(mock_ohlcv_raw):
    """OHLCV list-of-lists is converted to a DataFrame with the correct
    columns (open, high, low, close, volume) and a DatetimeIndex."""

    df = ohlcv_to_dataframe(mock_ohlcv_raw)

    # Verify columns
    expected_cols = ["open", "high", "low", "close", "volume"]
    assert list(df.columns) == expected_cols, (
        f"Expected columns {expected_cols}, got {list(df.columns)}"
    )

    # Verify index is DatetimeIndex
    assert isinstance(df.index, pd.DatetimeIndex), (
        f"Expected DatetimeIndex, got {type(df.index)}"
    )

    # Verify the data values match
    assert len(df) == 5
    assert df.iloc[0]["open"] == 100.0
    assert df.iloc[0]["close"] == 105.0
    assert df.iloc[4]["close"] == 125.0

    # Verify timestamps are UTC
    assert str(df.index.tz) == "UTC"


def test_timestamp_alignment():
    """Altcoin DataFrame missing a date is reindexed to BTC's index,
    and the gap is forward-filled from the previous day's values."""

    # BTC has 5 consecutive dates
    btc_dates = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    btc_df = pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104],
            "high": [110, 111, 112, 113, 114],
            "low": [90, 91, 92, 93, 94],
            "close": [105, 106, 107, 108, 109],
            "volume": [1000, 1100, 1200, 1300, 1400],
        },
        index=btc_dates,
    )

    # Altcoin is missing 2024-01-03 (index position 2)
    alt_dates = pd.DatetimeIndex(
        ["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-05"],
        tz="UTC",
    )
    alt_df = pd.DataFrame(
        {
            "open": [50, 51, 53, 54],
            "high": [60, 61, 63, 64],
            "low": [40, 41, 43, 44],
            "close": [55, 56, 58, 59],
            "volume": [500, 510, 530, 540],
        },
        index=alt_dates,
    )

    aligned = align_to_btc_index(btc_df, {"ALT/USDT": alt_df})
    result = aligned["ALT/USDT"]

    # All 5 BTC dates should be present
    assert len(result) == 5, f"Expected 5 rows, got {len(result)}"
    assert result.index.equals(btc_df.index), "Index should match BTC's DatetimeIndex"

    # The gap on 2024-01-03 should be forward-filled from 2024-01-02
    jan_03 = pd.Timestamp("2024-01-03", tz="UTC")
    assert result.loc[jan_03, "close"] == 56, (
        "2024-01-03 close should be ffilled from 2024-01-02 (56)"
    )
    assert result.loc[jan_03, "open"] == 51, (
        "2024-01-03 open should be ffilled from 2024-01-02 (51)"
    )


def test_symbol_mapping(mock_exchange):
    """CoinGecko coins are correctly mapped to CCXT pairs:
    - BTC is excluded (baseline, fetched separately)
    - ETH is excluded (not present on mock exchange)
    - RENDER is included (present on mock exchange)"""

    # Override mock_exchange.markets so ETH/USDT is absent
    mock_exchange.markets = {
        "BTC/USDT": {},
        "RENDER/USDT": {},
    }

    coins = [
        {"symbol": "btc", "id": "bitcoin", "market_cap_rank": 1},
        {"symbol": "eth", "id": "ethereum", "market_cap_rank": 2},
        {"symbol": "render", "id": "render-token", "market_cap_rank": 85},
    ]

    result = map_coingecko_to_ccxt(coins, mock_exchange)

    # BTC excluded (baseline), ETH not on exchange
    assert "BTC/USDT" not in result, "BTC/USDT should be excluded (baseline)"
    assert "ETH/USDT" not in result, "ETH/USDT should be excluded (not on exchange)"
    assert "RENDER/USDT" in result, "RENDER/USDT should be in results"
    assert result == ["RENDER/USDT"], f"Expected ['RENDER/USDT'], got {result}"


def test_symbol_deduplication(mock_exchange):
    """When two CG coins map to the same CCXT pair, the one with the lower
    market_cap_rank (= higher market cap) wins."""

    mock_exchange.markets = {"AI/USDT": {}}

    coins = [
        {"symbol": "ai", "id": "ai-project-a", "market_cap_rank": 200},
        {"symbol": "ai", "id": "ai-project-b", "market_cap_rank": 50},
    ]

    result = map_coingecko_to_ccxt(coins, mock_exchange)

    # Only one AI/USDT should remain
    assert len(result) == 1, f"Expected 1 symbol, got {len(result)}"
    assert result[0] == "AI/USDT"


async def test_exchange_close_called():
    """exchange.close() is always awaited, even if nothing is fetched,
    ensuring no unclosed client session warnings."""

    # Build a fully mocked exchange
    mock_ex = MagicMock()
    mock_ex.markets = {"BTC/USDT": {"symbol": "BTC/USDT"}}
    mock_ex.load_markets = AsyncMock(return_value=mock_ex.markets)

    # BTC/USDT returns valid OHLCV data
    base_ts = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    day_ms = 86_400_000
    btc_ohlcv = [
        [base_ts + i * day_ms, 100.0, 110.0, 95.0, 105.0, 1000.0]
        for i in range(5)
    ]
    mock_ex.fetch_ohlcv = AsyncMock(return_value=btc_ohlcv)
    mock_ex.close = AsyncMock()

    # Patch the ccxt constructor to return our mock exchange
    with patch(
        "quant_scanner.ingestion_engine.ccxt_async"
    ) as mock_ccxt_module:
        # Make getattr(ccxt_async, "binance") return a callable that gives our mock
        mock_ccxt_module.binance = MagicMock(return_value=mock_ex)
        mock_ccxt_module.BadSymbol = Exception

        result = await fetch_historical_data(
            symbols=[], exchange_id="binance", days=5, use_cache=False,
        )

    # The critical assertion: exchange.close was awaited
    mock_ex.close.assert_awaited_once()
