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
    fetch_historical_data_multi,
    fetch_universe,
    map_coingecko_to_ccxt,
    map_coingecko_to_ccxt_multi,
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


def price_sanity_filter(
    coins: list[dict],
    ohlcv_data: dict[str, pd.DataFrame],
    max_divergence: float = 0.15,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    """Drop coins where CoinGecko price diverges >15% from OHLCV last close.

    Called BEFORE compute_all_metrics to avoid wasting CPU on garbage data.
    Returns filtered (coins, ohlcv_data) with divergent symbols removed from both.
    BTC/USDT is always preserved in ohlcv_data (it's the baseline).
    """
    # Build lookup: CG symbol (lowercase) → current_price
    cg_prices: dict[str, float | None] = {}
    for coin in coins:
        raw_sym = coin.get("symbol", "")
        ccxt_symbol = raw_sym.upper() + "/USDT"
        cg_prices[ccxt_symbol] = coin.get("current_price")

    # Identify symbols to drop
    symbols_to_drop: set[str] = set()
    for symbol, df in ohlcv_data.items():
        if symbol == "BTC/USDT":
            continue

        cg_price = cg_prices.get(symbol)

        # Fail-open: if CG price is None/0 or OHLCV is empty, keep the coin
        if cg_price is None or cg_price == 0:
            continue
        if df.empty or "close" not in df.columns:
            continue

        last_close = df["close"].iloc[-1]
        if last_close is None or last_close == 0:
            continue

        try:
            divergence = abs(cg_price - last_close) / cg_price
        except (TypeError, ZeroDivisionError):
            continue

        if divergence > max_divergence:
            logger.warning(
                "Price sanity check failed for %s: CG=%.4f, OHLCV=%.4f, divergence=%.1f%% — dropping",
                symbol, cg_price, last_close, divergence * 100,
            )
            symbols_to_drop.add(symbol)

    if not symbols_to_drop:
        return coins, ohlcv_data

    # Filter ohlcv_data
    filtered_ohlcv = {k: v for k, v in ohlcv_data.items() if k not in symbols_to_drop}

    # Filter coins list: remove coins whose CCXT symbol was dropped
    dropped_cg_symbols = {s.split("/")[0].lower() for s in symbols_to_drop}
    filtered_coins = [
        c for c in coins if c.get("symbol", "").lower() not in dropped_cg_symbols
    ]

    return filtered_coins, filtered_ohlcv


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
    exchange_id: str = "kucoin,okx,gate",
    min_mcap: float = 20_000_000,
    max_mcap: float = 150_000_000,
    min_beta: float = 1.5,
    min_correlation: float = 0.7,
    min_volume: float = 1_000_000,
    min_supply_pct: float = 0.70,
    days: int = 60,
    use_cache: bool = True,
) -> pd.DataFrame:
    """End-to-end screening pipeline with multi-exchange support.

    Accepts a comma-separated string of exchange IDs.  When multiple
    exchanges are specified, symbols are mapped across all of them and
    OHLCV data is fetched from the exchange that owns each symbol.
    Single-exchange usage (e.g. ``exchange_id="kucoin"``) still works.

    Orchestrates:
        1. fetch_universe() -- CoinGecko filtered coin list
        2. Load markets from all exchanges (skip failures with warning)
        3. map_coingecko_to_ccxt_multi() -- symbol validation across exchanges
        4. fetch_historical_data_multi() -- 60-day OHLCV + BTC baseline
        5. compute_all_metrics() -- Beta, Correlation, Kelly per coin
        6. merge_metadata() -- join CG metadata with math output
        7. apply_filters() -- final sieve + sort by Beta descending

    Returns
    -------
    pd.DataFrame
        Filtered results with columns: symbol, name, market_cap,
        volume_24h, beta, correlation, kelly_fraction,
        circulating_pct, data_days.
        Returns empty DataFrame if nothing passes filters.
    """
    # Parse comma-separated exchange IDs
    exchange_ids = [x.strip() for x in exchange_id.split(",")]

    # Step 1: Fetch universe from CoinGecko
    coins = await fetch_universe(
        min_mcap=min_mcap,
        max_mcap=max_mcap,
        use_cache=use_cache,
    )

    if not coins:
        logger.warning("No coins returned from fetch_universe")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 2: Load markets from all exchanges (skip failures)
    loaded_exchanges: list[tuple[str, object]] = []
    for eid in exchange_ids:
        ex = getattr(ccxt_async, eid)({"enableRateLimit": True})
        try:
            await ex.load_markets()
            market_count = len(ex.markets) if ex.markets else 0
            loaded_exchanges.append((eid, ex))
            logger.info("Loaded markets from %s (%d)", eid, market_count)
        except Exception as exc:
            logger.warning(
                "Failed to load markets from %s: %s — skipping", eid, exc,
            )
            await ex.close()

    if not loaded_exchanges:
        logger.warning("All exchanges failed to load markets — returning empty result")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    loaded_names = ", ".join(
        f"{eid} ({len(ex.markets)})" for eid, ex in loaded_exchanges
    )
    logger.info("Loaded markets from: %s", loaded_names)

    # Step 3: Map CoinGecko symbols to CCXT symbols across all exchanges
    try:
        symbol_exchange_map = map_coingecko_to_ccxt_multi(coins, loaded_exchanges)
    finally:
        # Close all exchange connections used for market loading
        for _, ex in loaded_exchanges:
            await ex.close()

    if not symbol_exchange_map:
        logger.warning("No symbols mapped to any exchange")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 4: Fetch historical OHLCV data from the correct exchange per symbol
    ohlcv_data = await fetch_historical_data_multi(
        symbol_exchange_map=symbol_exchange_map,
        days=days,
        use_cache=use_cache,
    )

    if not ohlcv_data:
        logger.warning("No OHLCV data returned")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 4.5: Price sanity filter — drop symbol collisions BEFORE math
    coins, ohlcv_data = price_sanity_filter(coins, ohlcv_data)

    if len(ohlcv_data) <= 1:  # only BTC/USDT left
        logger.warning("All coins dropped by price sanity filter")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 5: Compute all metrics (Beta, Correlation, Kelly)
    metrics = compute_all_metrics(ohlcv_data)

    if metrics.empty:
        logger.warning("No metrics computed")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # Step 6: Merge CoinGecko metadata with math engine output
    merged = merge_metadata(coins, metrics)

    # Step 7: Apply filters and sort
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
