"""Screener engine: filter pipeline & ranking.

Orchestrates ingestion_engine and math_engine to produce a filtered,
ranked DataFrame of altcoins that meet the screening criteria.
"""

from __future__ import annotations

import logging

import ccxt.async_support as ccxt_async
import numpy as np
import pandas as pd

from quant_scanner.ingestion_engine import (
    fetch_historical_data,
    fetch_universe,
    map_coingecko_to_ccxt,
)
from quant_scanner.math_engine import compute_all_metrics

logger = logging.getLogger(__name__)

# Output columns in the final DataFrame
_OUTPUT_COLUMNS = [
    "symbol",
    "name",
    "market_cap",
    "volume_24h",
    "beta",
    "correlation",
    "kelly_fraction",
    "circulating_pct",
    "data_days",
]


def merge_metadata(
    coins: list[dict],
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Join CoinGecko metadata with math engine output on symbol.

    Parameters
    ----------
    coins : list[dict]
        CoinGecko coin dicts from fetch_universe(). Each has at least:
        symbol (lowercase), name, market_cap, total_volume,
        circulating_supply, total_supply, market_cap_rank.
    metrics : pd.DataFrame
        Output of compute_all_metrics() with columns:
        symbol (e.g. "RENDER/USDT"), beta, correlation,
        kelly_fraction, data_days.

    Returns
    -------
    pd.DataFrame
        Merged DataFrame with columns: symbol, name, market_cap,
        volume_24h, beta, correlation, kelly_fraction,
        circulating_pct, data_days.
    """
    # Build a lookup from CCXT-style symbol ("RENDER/USDT") to CG metadata
    cg_lookup: dict[str, dict] = {}
    for coin in coins:
        raw_sym = coin.get("symbol", "")
        ccxt_symbol = raw_sym.upper() + "/USDT"

        # Compute circulating_pct with safe division
        circ = coin.get("circulating_supply")
        total = coin.get("total_supply")

        if circ is None or total is None or total == 0:
            circulating_pct = np.nan
        else:
            # Also guard against NaN values passed as floats
            try:
                if np.isnan(circ) or np.isnan(total):
                    circulating_pct = np.nan
                else:
                    circulating_pct = circ / total
            except (TypeError, ValueError):
                circulating_pct = np.nan

        cg_lookup[ccxt_symbol] = {
            "name": coin.get("name", ""),
            "market_cap": coin.get("market_cap"),
            "volume_24h": coin.get("total_volume"),
            "circulating_pct": circulating_pct,
        }

    # Build merged rows
    rows: list[dict] = []
    for _, row in metrics.iterrows():
        sym = row["symbol"]
        meta = cg_lookup.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "name": meta.get("name", ""),
                "market_cap": meta.get("market_cap"),
                "volume_24h": meta.get("volume_24h"),
                "beta": row["beta"],
                "correlation": row["correlation"],
                "kelly_fraction": row["kelly_fraction"],
                "circulating_pct": meta.get("circulating_pct", np.nan),
                "data_days": row["data_days"],
            }
        )

    if not rows:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def apply_filters(
    df: pd.DataFrame,
    min_beta: float = 1.5,
    min_correlation: float = 0.7,
    min_volume: float = 1_000_000,
    min_supply_pct: float = 0.70,
) -> pd.DataFrame:
    """Apply the screening filters in order and sort by beta descending.

    Filter order (cheapest first):
        1. data_days >= 20
        2. beta > min_beta
        3. correlation > min_correlation
        4. volume_24h > min_volume
        5. circulating_pct > min_supply_pct ONLY where not NaN
           (NaN rows PASS this filter)

    Returns
    -------
    pd.DataFrame
        Filtered and sorted DataFrame with columns matching _OUTPUT_COLUMNS.
    """
    if df.empty:
        return df[_OUTPUT_COLUMNS] if all(c in df.columns for c in _OUTPUT_COLUMNS) else df

    result = df.copy()

    # 1. data_days >= 20
    result = result[result["data_days"] >= 20]

    # 2. beta > min_beta
    result = result[result["beta"] > min_beta]

    # 3. correlation > min_correlation
    result = result[result["correlation"] > min_correlation]

    # 4. volume_24h > min_volume
    result = result[result["volume_24h"] > min_volume]

    # 5. circulating_pct > min_supply_pct ONLY where not NaN
    #    NaN rows pass this filter
    supply_mask = result["circulating_pct"].isna() | (
        result["circulating_pct"] > min_supply_pct
    )
    result = result[supply_mask]

    # Sort by beta descending
    result = result.sort_values("beta", ascending=False).reset_index(drop=True)

    return result[_OUTPUT_COLUMNS]


async def run_screen(
    exchange_id: str = "binance",
    min_mcap: float = 20_000_000,
    max_mcap: float = 150_000_000,
    min_beta: float = 1.5,
    min_correlation: float = 0.7,
    min_volume: float = 1_000_000,
    min_supply_pct: float = 0.70,
    days: int = 60,
    use_cache: bool = True,
) -> pd.DataFrame:
    """End-to-end screening pipeline.

    Orchestrates:
        1. fetch_universe() -- CoinGecko filtered coin list
        2. map_coingecko_to_ccxt() -- symbol validation against exchange
        3. fetch_historical_data() -- 60-day OHLCV + BTC baseline
        4. compute_all_metrics() -- Beta, Correlation, Kelly per coin
        5. merge_metadata() -- join CG metadata with math output
        6. apply_filters() -- final sieve + sort by Beta descending

    Returns
    -------
    pd.DataFrame
        Filtered results with columns: symbol, name, market_cap,
        volume_24h, beta, correlation, kelly_fraction,
        circulating_pct, data_days.
        Returns empty DataFrame if nothing passes filters.
    """
    # Step 1: Fetch universe from CoinGecko
    coins = await fetch_universe(
        min_mcap=min_mcap,
        max_mcap=max_mcap,
        use_cache=use_cache,
    )

    if not coins:
        logger.warning("No coins returned from fetch_universe")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 2: Map CoinGecko symbols to CCXT symbols
    exchange = getattr(ccxt_async, exchange_id)({"enableRateLimit": True})
    try:
        await exchange.load_markets()
        symbols = map_coingecko_to_ccxt(coins, exchange)
    finally:
        await exchange.close()

    if not symbols:
        logger.warning("No symbols mapped to exchange")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 3: Fetch historical OHLCV data
    ohlcv_data = await fetch_historical_data(
        symbols=symbols,
        exchange_id=exchange_id,
        days=days,
        use_cache=use_cache,
    )

    if not ohlcv_data:
        logger.warning("No OHLCV data returned")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 4: Compute all metrics (Beta, Correlation, Kelly)
    metrics = compute_all_metrics(ohlcv_data)

    if metrics.empty:
        logger.warning("No metrics computed")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 5: Merge CoinGecko metadata with math engine output
    merged = merge_metadata(coins, metrics)

    # Step 6: Apply filters and sort
    filtered = apply_filters(
        merged,
        min_beta=min_beta,
        min_correlation=min_correlation,
        min_volume=min_volume,
        min_supply_pct=min_supply_pct,
    )

    logger.info(
        "Screening complete: %d coins passed out of %d candidates",
        len(filtered),
        len(merged),
    )

    return filtered
