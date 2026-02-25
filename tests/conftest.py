"""Shared test fixtures for quant_scanner tests."""

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest


@pytest.fixture()
def mock_coingecko_response():
    """Return a list of 12 mock CoinGecko coin objects covering all edge cases.

    Includes:
    - 2 valid coins in range ($20M-$150M)
    - 1 coin below range ($10M)
    - 1 coin above range ($200M)
    - 1 coin with market_cap=None
    - 1 stablecoin (USDT) in range
    - 1 wrapped token (WBTC) in range
    - 1 additional stablecoin (USDC) in range
    - 1 additional wrapped token (WETH) in range
    - 1 coin at the exact lower boundary ($20M)
    - 1 coin at the exact upper boundary ($150M)
    - 1 coin with market_cap=0 (edge case)
    """
    return [
        {
            "id": "alpha-coin",
            "symbol": "abc",
            "name": "Alpha Coin",
            "market_cap": 50_000_000,
            "fully_diluted_valuation": 80_000_000,
            "circulating_supply": 500_000_000,
            "total_supply": 1_000_000_000,
            "total_volume": 5_000_000,
            "market_cap_rank": 200,
        },
        {
            "id": "xray-coin",
            "symbol": "xyz",
            "name": "Xray Coin",
            "market_cap": 100_000_000,
            "fully_diluted_valuation": 150_000_000,
            "circulating_supply": 800_000_000,
            "total_supply": 1_000_000_000,
            "total_volume": 10_000_000,
            "market_cap_rank": 150,
        },
        {
            "id": "tiny-coin",
            "symbol": "tiny",
            "name": "Tiny Coin",
            "market_cap": 10_000_000,
            "fully_diluted_valuation": 20_000_000,
            "circulating_supply": 100_000_000,
            "total_supply": 200_000_000,
            "total_volume": 500_000,
            "market_cap_rank": 500,
        },
        {
            "id": "mega-coin",
            "symbol": "mega",
            "name": "Mega Coin",
            "market_cap": 200_000_000,
            "fully_diluted_valuation": 300_000_000,
            "circulating_supply": 1_000_000_000,
            "total_supply": 1_000_000_000,
            "total_volume": 50_000_000,
            "market_cap_rank": 50,
        },
        {
            "id": "null-cap-coin",
            "symbol": "nullcap",
            "name": "Null Cap Coin",
            "market_cap": None,
            "fully_diluted_valuation": None,
            "circulating_supply": 1_000_000,
            "total_supply": 10_000_000,
            "total_volume": 100_000,
            "market_cap_rank": None,
        },
        {
            "id": "tether",
            "symbol": "usdt",
            "name": "Tether",
            "market_cap": 80_000_000,
            "fully_diluted_valuation": 80_000_000,
            "circulating_supply": 80_000_000_000,
            "total_supply": 80_000_000_000,
            "total_volume": 50_000_000_000,
            "market_cap_rank": 3,
        },
        {
            "id": "wrapped-bitcoin",
            "symbol": "wbtc",
            "name": "Wrapped Bitcoin",
            "market_cap": 80_000_000,
            "fully_diluted_valuation": 80_000_000,
            "circulating_supply": 150_000,
            "total_supply": 150_000,
            "total_volume": 200_000_000,
            "market_cap_rank": 15,
        },
        {
            "id": "usd-coin",
            "symbol": "usdc",
            "name": "USD Coin",
            "market_cap": 60_000_000,
            "fully_diluted_valuation": 60_000_000,
            "circulating_supply": 60_000_000_000,
            "total_supply": 60_000_000_000,
            "total_volume": 5_000_000_000,
            "market_cap_rank": 5,
        },
        {
            "id": "wrapped-ether",
            "symbol": "weth",
            "name": "Wrapped Ether",
            "market_cap": 70_000_000,
            "fully_diluted_valuation": 70_000_000,
            "circulating_supply": 3_000_000,
            "total_supply": 3_000_000,
            "total_volume": 100_000_000,
            "market_cap_rank": 20,
        },
        {
            "id": "boundary-low",
            "symbol": "blow",
            "name": "Boundary Low Coin",
            "market_cap": 20_000_000,
            "fully_diluted_valuation": 40_000_000,
            "circulating_supply": 200_000_000,
            "total_supply": 400_000_000,
            "total_volume": 2_000_000,
            "market_cap_rank": 350,
        },
        {
            "id": "boundary-high",
            "symbol": "bhigh",
            "name": "Boundary High Coin",
            "market_cap": 150_000_000,
            "fully_diluted_valuation": 200_000_000,
            "circulating_supply": 600_000_000,
            "total_supply": 800_000_000,
            "total_volume": 20_000_000,
            "market_cap_rank": 100,
        },
        {
            "id": "zero-cap-coin",
            "symbol": "zerocap",
            "name": "Zero Cap Coin",
            "market_cap": 0,
            "fully_diluted_valuation": 0,
            "circulating_supply": 0,
            "total_supply": 1_000_000,
            "total_volume": 0,
            "market_cap_rank": 999,
        },
    ]


# ---------------------------------------------------------------------------
# QUANT-003: OHLCV / exchange fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_ohlcv_raw():
    """Return 5 days of raw OHLCV data as a list-of-lists.

    Each row: [timestamp_ms, open, high, low, close, volume]
    Timestamps correspond to 2024-01-01 through 2024-01-05 (UTC midnight).
    """
    base_ts = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    day_ms = 86_400_000  # milliseconds in a day
    return [
        [base_ts + 0 * day_ms, 100.0, 110.0, 95.0, 105.0, 1000.0],
        [base_ts + 1 * day_ms, 105.0, 115.0, 100.0, 110.0, 1200.0],
        [base_ts + 2 * day_ms, 110.0, 120.0, 105.0, 115.0, 1100.0],
        [base_ts + 3 * day_ms, 115.0, 125.0, 110.0, 120.0, 1300.0],
        [base_ts + 4 * day_ms, 120.0, 130.0, 115.0, 125.0, 1400.0],
    ]


@pytest.fixture()
def mock_exchange():
    """Return a fully-mocked ccxt async exchange instance.

    Attributes mocked:
        - markets (dict)
        - load_markets (AsyncMock)
        - fetch_ohlcv (AsyncMock)
        - close (AsyncMock)
    """
    exchange = MagicMock()
    exchange.markets = {
        "BTC/USDT": {"symbol": "BTC/USDT"},
        "ETH/USDT": {"symbol": "ETH/USDT"},
        "RENDER/USDT": {"symbol": "RENDER/USDT"},
        "AI/USDT": {"symbol": "AI/USDT"},
    }
    exchange.load_markets = AsyncMock(return_value=exchange.markets)
    exchange.fetch_ohlcv = AsyncMock(return_value=[])
    exchange.close = AsyncMock()
    return exchange
