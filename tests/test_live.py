"""Live API integration tests for production validation.

All tests in this module call REAL exchange and CoinGecko APIs.
They are marked with @pytest.mark.live and skipped in normal test runs.

Run explicitly: pytest -m live -v --timeout=300
"""

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.live


async def test_live_coingecko_universe():
    """fetch_universe() returns >100 coins with required fields."""
    from quant_scanner.ingestion_engine import fetch_universe

    coins = await fetch_universe(use_cache=True)

    assert len(coins) > 100, f"Expected >100 coins, got {len(coins)}"

    # Validate structure of each coin
    required_keys = {"symbol", "market_cap"}
    for coin in coins[:10]:  # spot-check first 10
        for key in required_keys:
            assert key in coin, f"Missing key '{key}' in coin: {coin.get('id')}"
        assert coin["market_cap"] is not None
        assert coin["market_cap"] >= 20_000_000


async def test_live_ohlcv_fetch_btc():
    """BTC/USDT from KuCoin: 55+ rows, all float64 columns, no NaN in close."""
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timedelta, timezone

    from quant_scanner.ingestion_engine import ohlcv_to_dataframe

    exchange = ccxt_async.kucoin({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000
        )
        ohlcv = await exchange.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=60)
    finally:
        await exchange.close()

    assert len(ohlcv) >= 55, f"Expected >=55 candles, got {len(ohlcv)}"

    df = ohlcv_to_dataframe(ohlcv)

    # All columns should be float64 (Phase 1 dtype coercion)
    for col in ["open", "high", "low", "close", "volume"]:
        assert df[col].dtype == "float64", f"{col} is {df[col].dtype}, expected float64"

    # No NaN in close
    assert df["close"].notna().all(), "BTC close should have no NaN values"


async def test_live_ohlcv_dtypes_all_float64():
    """Every OHLCV column for a real altcoin is float64 after ohlcv_to_dataframe."""
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timedelta, timezone

    from quant_scanner.ingestion_engine import ohlcv_to_dataframe

    exchange = ccxt_async.kucoin({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000
        )
        # Use ETH/USDT as a widely available altcoin
        ohlcv = await exchange.fetch_ohlcv("ETH/USDT", "1d", since=since, limit=60)
    finally:
        await exchange.close()

    df = ohlcv_to_dataframe(ohlcv)

    for col in ["open", "high", "low", "close", "volume"]:
        assert df[col].dtype == "float64", (
            f"Altcoin {col} dtype is {df[col].dtype}, expected float64"
        )


async def test_live_alignment_no_synthetic_zeros():
    """After alignment, pct_change() on a real altcoin has no synthetic 0% returns."""
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timedelta, timezone

    from quant_scanner.ingestion_engine import align_to_btc_index, ohlcv_to_dataframe

    exchange = ccxt_async.kucoin({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000
        )
        btc_ohlcv = await exchange.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=60)
        eth_ohlcv = await exchange.fetch_ohlcv("ETH/USDT", "1d", since=since, limit=60)
    finally:
        await exchange.close()

    btc_df = ohlcv_to_dataframe(btc_ohlcv)
    eth_df = ohlcv_to_dataframe(eth_ohlcv)

    aligned = align_to_btc_index(btc_df, {"ETH/USDT": eth_df})
    eth_aligned = aligned["ETH/USDT"]

    returns = eth_aligned["close"].pct_change().dropna()

    # Count exact zeros — there should be very few (real markets rarely have 0% return)
    zero_count = (returns == 0.0).sum()
    total_count = len(returns)
    # Allow up to 5% zero returns (real markets can have flat days)
    assert zero_count / total_count < 0.05, (
        f"Too many zero returns: {zero_count}/{total_count} — possible synthetic zeros"
    )


async def test_live_compute_metrics_ranges():
    """compute_all_metrics() on real data: values are in expected ranges."""
    from quant_scanner.ingestion_engine import (
        fetch_historical_data,
        ohlcv_to_dataframe,
    )
    from quant_scanner.math_engine import compute_all_metrics
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timedelta, timezone

    exchange = ccxt_async.kucoin({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000
        )
        btc_ohlcv = await exchange.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=60)
        eth_ohlcv = await exchange.fetch_ohlcv("ETH/USDT", "1d", since=since, limit=60)
    finally:
        await exchange.close()

    ohlcv_data = {
        "BTC/USDT": ohlcv_to_dataframe(btc_ohlcv),
        "ETH/USDT": ohlcv_to_dataframe(eth_ohlcv),
    }

    result = compute_all_metrics(ohlcv_data)

    assert len(result) == 1
    row = result.iloc[0]

    # Beta should be a finite float
    assert np.isfinite(row["beta"]), f"Beta is not finite: {row['beta']}"

    # Correlation ∈ [-1, 1]
    assert -1 <= row["correlation"] <= 1, (
        f"Correlation out of range: {row['correlation']}"
    )

    # Trend score ∈ [0, 0.25]
    assert 0 <= row["trend_score"] <= 0.25, (
        f"Trend score out of range: {row['trend_score']}"
    )

    # data_days should be reasonable
    assert row["data_days"] >= 20, f"Too few data days: {row['data_days']}"


async def test_live_price_sanity_filter_survives():
    """price_sanity_filter() on real coins+OHLCV doesn't crash. Some symbols survive."""
    from quant_scanner.ingestion_engine import fetch_universe
    from quant_scanner.screener_engine import price_sanity_filter
    import ccxt.async_support as ccxt_async
    from datetime import datetime, timedelta, timezone
    from quant_scanner.ingestion_engine import ohlcv_to_dataframe

    coins = await fetch_universe(use_cache=True)

    # Fetch a few real coins
    exchange = ccxt_async.kucoin({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=60)).timestamp() * 1000
        )
        btc_ohlcv = await exchange.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=60)
        ohlcv_data = {"BTC/USDT": ohlcv_to_dataframe(btc_ohlcv)}

        # Find a coin from universe that exists on kucoin
        for coin in coins[:20]:
            symbol = coin.get("symbol", "").upper() + "/USDT"
            if symbol in exchange.markets and symbol != "BTC/USDT":
                try:
                    alt_ohlcv = await exchange.fetch_ohlcv(
                        symbol, "1d", since=since, limit=60,
                    )
                    if alt_ohlcv:
                        ohlcv_data[symbol] = ohlcv_to_dataframe(alt_ohlcv)
                        break
                except Exception:
                    continue
    finally:
        await exchange.close()

    # Should not crash
    filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv_data)

    # BTC should always survive
    assert "BTC/USDT" in filtered_ohlcv
    # At least some coins should survive
    assert len(filtered_coins) > 0


async def test_live_full_pipeline_returns_results():
    """ACCEPTANCE TEST: real APIs -> real data -> real metrics -> results."""
    from quant_scanner.screener_engine import run_screen

    result = await run_screen(
        exchange_id="kucoin",
        min_beta=1.0,
        min_correlation=0.6,
        max_amihud=1e-5,
        use_cache=True,
    )

    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0, "Full pipeline must return >0 results with calibrated thresholds"

    expected_cols = ["symbol", "beta", "correlation", "trend_score", "amihud", "data_days"]
    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"

    # Every row must satisfy the filter thresholds we set
    assert (result["beta"] > 1.0).all(), "All beta values must exceed min_beta=1.0"
    assert (result["correlation"] > 0.6).all(), "All correlation values must exceed min_corr=0.6"
    assert (result["data_days"] >= 20).all(), "All coins must have >=20 data days"
