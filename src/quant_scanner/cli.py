"""CLI entry point for Crypto Quant Alpha Scanner."""

import argparse
import asyncio
import logging

import pandas as pd

from quant_scanner.dashboard import render_no_results, render_results

DRY_RUN_DATA = pd.DataFrame([
    {"symbol": "RENDER/USDT", "name": "Render", "market_cap": 45_000_000,
     "volume_24h": 8_500_000, "beta": 2.34, "correlation": 0.89,
     "kelly_fraction": 0.12, "circulating_pct": 0.78, "data_days": 60},
    {"symbol": "FET/USDT", "name": "Fetch.ai", "market_cap": 120_000_000,
     "volume_24h": 15_000_000, "beta": 1.87, "correlation": 0.82,
     "kelly_fraction": 0.09, "circulating_pct": 0.85, "data_days": 60},
    {"symbol": "EXAMPLE/USDT", "name": "Example Coin", "market_cap": 30_000_000,
     "volume_24h": 2_100_000, "beta": 1.62, "correlation": 0.74,
     "kelly_fraction": 0.05, "circulating_pct": 0.91, "data_days": 45},
])


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Crypto Quant Alpha Scanner — find low-cap altcoins with high Beta/Correlation to BTC"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Use mock data, no API calls",
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="binance",
        help="ccxt exchange ID (default: binance)",
    )
    parser.add_argument(
        "--min-mcap",
        type=int,
        default=20_000_000,
        help="Minimum market cap in USD (default: 20000000)",
    )
    parser.add_argument(
        "--max-mcap",
        type=int,
        default=150_000_000,
        help="Maximum market cap in USD (default: 150000000)",
    )
    parser.add_argument(
        "--min-beta",
        type=float,
        default=1.5,
        help="Minimum Beta threshold (default: 1.5)",
    )
    parser.add_argument(
        "--min-corr",
        type=float,
        default=0.7,
        help="Minimum correlation threshold (default: 0.7)",
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=1_000_000,
        help="Minimum 24h volume in USD (default: 1000000)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Force fresh API calls, bypass cache",
    )
    return parser.parse_args(argv)


def main():
    """Sync entry point for the scanner CLI."""
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    if args.dry_run:
        render_results(DRY_RUN_DATA)
        return

    asyncio.run(async_main(args))


async def async_main(args):
    """Async entry point that runs the full screening pipeline."""
    from quant_scanner.screener_engine import run_screen

    result = await run_screen(
        exchange_id=args.exchange,
        min_mcap=args.min_mcap,
        max_mcap=args.max_mcap,
        min_beta=args.min_beta,
        min_correlation=args.min_corr,
        min_volume=args.min_volume,
        use_cache=not args.no_cache,
    )

    if result.empty:
        render_no_results()
    else:
        render_results(result)
