"""Ingestion engine: CoinGecko universe fetching, filtering, caching,
CCXT OHLCV fetching, symbol mapping, and timestamp alignment."""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone

import aiohttp
import ccxt.async_support as ccxt_async
import pandas as pd
from aiolimiter import AsyncLimiter
from dotenv import load_dotenv

# Load .env so COINGECKO_API_KEY is available via os.environ
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exclusion lists
# ---------------------------------------------------------------------------

STABLECOINS = frozenset({
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDP",
    "GUSD", "LUSD", "SUSD", "USDD", "PYUSD", "FDUSD", "EURC",
})

WRAPPED_TOKENS = frozenset({
    "WBTC", "WETH", "WBNB", "STETH", "WSTETH", "CBETH",
    "RETH", "MSOL", "BNSOL", "JITOSOL",
})

# ---------------------------------------------------------------------------
# CoinGecko rate limiter (Layer 3): 25 requests per 60 seconds
# ---------------------------------------------------------------------------

_cg_limiter = AsyncLimiter(25, 60)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CG_BASE_URL = "https://api.coingecko.com/api/v3/coins/markets"
_CACHE_PATH = "cache/coingecko_universe.json"
_OHLCV_CACHE_DIR = "cache/ohlcv"
_OHLCV_CACHE_TTL_HOURS = 6
_MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_page(
    session: aiohttp.ClientSession,
    page: int,
    headers: dict,
) -> list[dict]:
    """Fetch a single page from CoinGecko /coins/markets with backoff."""
    url = (
        f"{_CG_BASE_URL}?vs_currency=usd&order=market_cap_desc"
        f"&per_page=250&page={page}&sparkline=false"
    )

    for attempt in range(_MAX_RETRIES):
        async with _cg_limiter:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 429 or resp.status >= 500:
                        if attempt == _MAX_RETRIES - 1:
                            resp.raise_for_status()
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "CoinGecko %s on page %d, retry %d/%d in %.1fs",
                            resp.status, page, attempt + 1, _MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        resp.raise_for_status()
            except aiohttp.ClientResponseError:
                if attempt == _MAX_RETRIES - 1:
                    raise
                delay = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "CoinGecko error on page %d, retry %d/%d in %.1fs",
                    page, attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)

    return []  # unreachable, but keeps mypy happy


def _load_cache(cache_ttl_hours: int) -> list[dict] | None:
    """Return cached data if the file exists and is still fresh."""
    if not os.path.exists(_CACHE_PATH):
        return None
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        age_hours = (
            datetime.now(timezone.utc) - fetched_at
        ).total_seconds() / 3600
        if age_hours < cache_ttl_hours:
            logger.info("CoinGecko cache hit (age %.1fh)", age_hours)
            return data["coins"]
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Cache read failed (%s), will re-fetch", exc)
    return None


def _save_cache(coins: list[dict]) -> None:
    """Persist fetched coins to the cache file."""
    os.makedirs("cache", exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "coins": coins,
    }
    with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    logger.info("Saved %d coins to cache", len(coins))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_universe(
    min_mcap: float = 20_000_000,
    max_mcap: float = 150_000_000,
    use_cache: bool = True,
    cache_ttl_hours: int = 12,
) -> list[dict]:
    """Fetch top 1000 coins from CoinGecko, filter by market cap,
    exclude stablecoins and wrapped tokens.

    IMPORTANT: CoinGecko can return market_cap=null for some coins.
    These must be filtered out BEFORE the numeric comparison to avoid TypeError.

    Cache writes use os.makedirs("cache", exist_ok=True) to auto-create dir.
    Uses load_dotenv() for COINGECKO_API_KEY; falls back to public tier if absent.

    Returns list of dicts with keys:
        id, symbol, name, market_cap, fully_diluted_valuation,
        circulating_supply, total_supply, total_volume
    """

    # --- Try cache first ---
    if use_cache:
        cached = _load_cache(cache_ttl_hours)
        if cached is not None:
            return cached

    # --- Build request headers ---
    headers: dict[str, str] = {}
    api_key = os.environ.get("COINGECKO_API_KEY")
    if api_key:
        headers["x-cg-demo-api-key"] = api_key

    # --- Fetch 4 pages (top 1000) ---
    all_coins: list[dict] = []
    resolver = aiohttp.ThreadedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver)
    async with aiohttp.ClientSession(connector=connector) as session:
        for page in range(1, 5):
            page_coins = await _fetch_page(session, page, headers)
            all_coins.extend(page_coins)
            logger.info("Fetched page %d: %d coins", page, len(page_coins))

    # --- Filter ---
    filtered: list[dict] = []
    for coin in all_coins:
        mc = coin.get("market_cap")

        # 1. Skip coins where market_cap is None/null FIRST
        if mc is None:
            logger.warning(
                "Skipping %s (%s): market_cap is null",
                coin.get("symbol"), coin.get("id"),
            )
            continue

        # 2. Market cap range filter
        if mc < min_mcap or mc > max_mcap:
            continue

        # 3. Stablecoin / wrapped token exclusion
        symbol_upper = coin.get("symbol", "").upper()
        if symbol_upper in STABLECOINS:
            logger.warning("Excluding stablecoin: %s", symbol_upper)
            continue
        if symbol_upper in WRAPPED_TOKENS:
            logger.warning("Excluding wrapped token: %s", symbol_upper)
            continue

        filtered.append(coin)

    logger.info(
        "Universe: %d coins after filtering (%d raw)",
        len(filtered), len(all_coins),
    )

    # --- Save cache ---
    if use_cache:
        _save_cache(filtered)

    return filtered


# ---------------------------------------------------------------------------
# OHLCV caching helpers
# ---------------------------------------------------------------------------


def _symbol_to_cache_filename(symbol: str) -> str:
    """Convert a CCXT symbol like 'BTC/USDT' to a safe filename like 'BTC_USDT'."""
    return symbol.replace("/", "_")


def _load_ohlcv_cache(symbol: str) -> list[list] | None:
    """Return cached OHLCV data for *symbol* if fresh (< 6 hours old)."""
    safe_name = _symbol_to_cache_filename(symbol)
    path = os.path.join(_OHLCV_CACHE_DIR, f"{safe_name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        age_hours = (
            datetime.now(timezone.utc) - fetched_at
        ).total_seconds() / 3600
        if age_hours < _OHLCV_CACHE_TTL_HOURS:
            logger.info("OHLCV cache hit for %s (age %.1fh)", symbol, age_hours)
            return data["ohlcv"]
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("OHLCV cache read failed for %s (%s)", symbol, exc)
    return None


def _save_ohlcv_cache(symbol: str, ohlcv: list[list]) -> None:
    """Persist raw OHLCV data for *symbol* to disk."""
    os.makedirs(_OHLCV_CACHE_DIR, exist_ok=True)
    safe_name = _symbol_to_cache_filename(symbol)
    path = os.path.join(_OHLCV_CACHE_DIR, f"{safe_name}.json")
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ohlcv": ohlcv,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    logger.info("Saved OHLCV cache for %s", symbol)


# ---------------------------------------------------------------------------
# OHLCV → DataFrame conversion
# ---------------------------------------------------------------------------


def ohlcv_to_dataframe(ohlcv: list[list]) -> pd.DataFrame:
    """Convert raw OHLCV list-of-lists to a pandas DataFrame.

    Parameters
    ----------
    ohlcv : list[list]
        Each inner list is ``[timestamp_ms, open, high, low, close, volume]``.

    Returns
    -------
    pd.DataFrame
        Columns: ``open, high, low, close, volume``.
        Index: ``DatetimeIndex`` (UTC).
    """
    timestamps = [row[0] for row in ohlcv]
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df.index = pd.to_datetime(timestamps, unit="ms", utc=True)
    df = df.drop(columns=["timestamp"])
    return df


# ---------------------------------------------------------------------------
# Symbol mapping: CoinGecko → CCXT
# ---------------------------------------------------------------------------


def map_coingecko_to_ccxt(
    coins: list[dict],
    exchange,
) -> list[str]:
    """Map CoinGecko coin dicts to CCXT trading pair strings.

    Steps:
        1. Uppercase coin["symbol"], append "/USDT" to form candidate pair.
        2. Exclude BTC/USDT (it is the baseline, fetched separately).
        3. Check if candidate exists in ``exchange.markets``.
        4. Deduplicate: when multiple CG coins map to the same pair,
           keep the one with the lowest ``market_cap_rank`` (= highest MC).
        5. Log dropped/deduplicated coins via ``logger.warning()``.

    Returns list of unique CCXT symbol strings.
    """
    # Collect candidates: mapping from ccxt_symbol → best CG coin dict
    best: dict[str, dict] = {}

    for coin in coins:
        raw_symbol = coin.get("symbol", "")
        candidate = raw_symbol.upper() + "/USDT"

        # Exclude BTC/USDT — it's the baseline, fetched separately
        if candidate == "BTC/USDT":
            continue

        # Check if the pair exists on the exchange
        if candidate not in exchange.markets:
            logger.warning(
                "Dropping %s (%s): %s not found on exchange",
                coin.get("id"), raw_symbol, candidate,
            )
            continue

        # Deduplicate: keep the coin with the lowest market_cap_rank
        rank = coin.get("market_cap_rank")
        if rank is None:
            rank = float("inf")

        if candidate in best:
            existing_rank = best[candidate].get("market_cap_rank")
            if existing_rank is None:
                existing_rank = float("inf")
            if rank < existing_rank:
                logger.warning(
                    "Deduplicating %s: keeping %s (rank %s) over %s (rank %s)",
                    candidate,
                    coin.get("id"), rank,
                    best[candidate].get("id"), existing_rank,
                )
                best[candidate] = coin
            else:
                logger.warning(
                    "Deduplicating %s: keeping %s (rank %s), dropping %s (rank %s)",
                    candidate,
                    best[candidate].get("id"), existing_rank,
                    coin.get("id"), rank,
                )
        else:
            best[candidate] = coin

    return list(best.keys())


# ---------------------------------------------------------------------------
# Timestamp alignment
# ---------------------------------------------------------------------------


def align_to_btc_index(
    btc_df: pd.DataFrame,
    alt_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Reindex all altcoin DataFrames to BTC's DatetimeIndex, then forward-fill.

    Parameters
    ----------
    btc_df : pd.DataFrame
        BTC/USDT DataFrame whose index is the master DatetimeIndex.
    alt_dfs : dict[str, pd.DataFrame]
        Mapping of symbol to altcoin DataFrame.

    Returns
    -------
    dict[str, pd.DataFrame]
        Same mapping with DataFrames reindexed and forward-filled (limit=3).
    """
    aligned: dict[str, pd.DataFrame] = {}
    for symbol, df in alt_dfs.items():
        reindexed = df.reindex(btc_df.index)
        reindexed = reindexed.ffill(limit=3)
        aligned[symbol] = reindexed
    return aligned


# ---------------------------------------------------------------------------
# OHLCV fetching (CCXT async)
# ---------------------------------------------------------------------------


async def fetch_historical_data(
    symbols: list[str],
    exchange_id: str = "binance",
    days: int = 60,
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV data for *symbols* plus the BTC/USDT baseline.

    Uses ``ccxt.async_support`` with ``enableRateLimit=True`` and an
    ``asyncio.Semaphore(10)`` to cap concurrent fetches.

    CRITICAL: Uses ``datetime.now(timezone.utc)`` for the ``since``
    timestamp — NOT ``datetime.now()`` which gives local time on Windows.

    CRITICAL: Always calls ``await exchange.close()`` in a ``try/finally``
    block to prevent ResourceWarning (unclosed client session).

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of symbol (e.g. ``"RENDER/USDT"``) to DataFrame.
        ``"BTC/USDT"`` is always included. All altcoin DataFrames are
        aligned to BTC's DatetimeIndex with forward-fill (limit=3).
    """
    # Ensure BTC/USDT is first and only appears once
    all_symbols = ["BTC/USDT"] + [s for s in symbols if s != "BTC/USDT"]

    since = int(
        (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
    )

    sem = asyncio.Semaphore(10)

    exchange = getattr(ccxt_async, exchange_id)({"enableRateLimit": True})

    try:
        await exchange.load_markets()

        async def _fetch_one(symbol: str) -> tuple[str, list[list] | None]:
            """Fetch OHLCV for a single symbol, respecting semaphore."""
            # Try cache first
            if use_cache:
                cached = _load_ohlcv_cache(symbol)
                if cached is not None:
                    return (symbol, cached)

            async with sem:
                try:
                    ohlcv = await exchange.fetch_ohlcv(
                        symbol, "1d", since=since, limit=days,
                    )
                except ccxt_async.BadSymbol:
                    logger.warning("BadSymbol for %s, skipping", symbol)
                    return (symbol, None)

            if not ohlcv:
                logger.warning(
                    "Empty OHLCV response for %s, skipping", symbol,
                )
                return (symbol, None)

            # Save to cache
            if use_cache:
                _save_ohlcv_cache(symbol, ohlcv)

            return (symbol, ohlcv)

        # Fetch all symbols concurrently
        tasks = [_fetch_one(s) for s in all_symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        await exchange.close()

    # Convert results to DataFrames
    raw_dfs: dict[str, pd.DataFrame] = {}
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Fetch exception: %s", result)
            continue
        symbol, ohlcv = result
        if ohlcv is None:
            continue
        raw_dfs[symbol] = ohlcv_to_dataframe(ohlcv)

    # BTC must be present for alignment
    if "BTC/USDT" not in raw_dfs:
        logger.warning("BTC/USDT data missing — returning empty result")
        return {}

    btc_df = raw_dfs["BTC/USDT"]

    # Separate altcoin DataFrames for alignment
    alt_dfs = {s: df for s, df in raw_dfs.items() if s != "BTC/USDT"}
    aligned = align_to_btc_index(btc_df, alt_dfs)

    # Build final output: BTC + aligned altcoins
    output: dict[str, pd.DataFrame] = {"BTC/USDT": btc_df}
    output.update(aligned)

    return output
