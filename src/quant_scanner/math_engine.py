"""Math engine for Crypto Quant Alpha Scanner.

Computes rolling Beta, Correlation, and Half-Kelly position sizing
for altcoins relative to BTC.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_beta(
    asset_returns: pd.Series,
    btc_returns: pd.Series,
    window: int = 30,
    min_periods: int = 20,
) -> pd.Series:
    """Rolling Beta = Cov(R_asset, R_btc) / Var(R_btc).

    Guards:
        - If Var(R_btc) == 0 in any window, returns NaN for that window.
        - If fewer than min_periods valid observations, returns NaN.
    """
    cov = asset_returns.rolling(window, min_periods=min_periods).cov(btc_returns)
    var = btc_returns.rolling(window, min_periods=min_periods).var()
    var = var.replace(0, np.nan)  # CRITICAL: prevents inf
    beta = cov / var
    return beta


def calculate_correlation(
    asset_returns: pd.Series,
    btc_returns: pd.Series,
    window: int = 30,
    min_periods: int = 20,
) -> pd.Series:
    """Rolling 30-day Pearson correlation.

    Uses asset_returns.rolling(window, min_periods=min_periods).corr(btc_returns).
    """
    corr = asset_returns.rolling(window, min_periods=min_periods).corr(btc_returns)
    return corr


def calculate_kelly(
    returns: pd.Series | np.ndarray,
    max_fraction: float = 0.25,
    min_trades: int = 30,
) -> float:
    """Half-Kelly position sizing with safety cap.

    Formula: f* = (b*p - q) / b, then f = f*/2
    Where:
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p

    Guards:
        - If len(returns) < min_trades, returns 0.0.
        - If no wins OR no losses in series, returns 0.0
          (can't estimate odds without both).
        - If f* <= 0 (no edge), returns 0.0.
        - Caps at max_fraction (default 25%).
    """
    # Convert to numpy array if needed, drop NaN
    if isinstance(returns, pd.Series):
        returns = returns.dropna().values
    else:
        returns = returns[~np.isnan(returns)]

    if len(returns) < min_trades:
        return 0.0

    wins = returns[returns > 0]
    losses = returns[returns < 0]

    if len(wins) == 0 or len(losses) == 0:
        return 0.0  # CRITICAL: can't estimate odds without both

    b = np.mean(wins) / np.abs(np.mean(losses))
    p = len(wins) / len(returns)
    q = 1 - p
    f_star = (b * p - q) / b
    f_half = f_star / 2
    return min(f_half, max_fraction) if f_star > 0 else 0.0


def compute_all_metrics(
    ohlcv_data: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Master function: compute Beta, Correlation, and Kelly for each altcoin.

    Input: dict mapping symbol strings to DataFrames with at least a "close"
    column. Must include "BTC/USDT" as the baseline.

    For each altcoin:
        1. Compute daily returns via pct_change().
        2. Calculate rolling beta vs BTC.
        3. Calculate rolling correlation vs BTC.
        4. Calculate Kelly fraction on the asset returns.
        5. Take the LAST valid (non-NaN) value of each rolling series
           as the "current" metric.

    data_days = count of non-NaN values in the RETURNS series
    (not close prices). With 60 close prices, pct_change produces
    59 returns (first is NaN).

    Returns DataFrame with columns:
        symbol, beta, correlation, kelly_fraction, data_days
    """
    if "BTC/USDT" not in ohlcv_data:
        raise ValueError("ohlcv_data must contain 'BTC/USDT' as the baseline")

    btc_df = ohlcv_data["BTC/USDT"]
    btc_returns = btc_df["close"].pct_change()

    results = []

    for symbol, df in ohlcv_data.items():
        if symbol == "BTC/USDT":
            continue

        asset_returns = df["close"].pct_change()

        # data_days = count of non-NaN values in RETURNS series
        data_days = int(asset_returns.notna().sum())

        # Rolling beta and correlation
        beta_series = calculate_beta(asset_returns, btc_returns)
        corr_series = calculate_correlation(asset_returns, btc_returns)

        # Last valid (non-NaN) value is the "current" metric
        beta_val = beta_series.dropna().iloc[-1] if not beta_series.dropna().empty else np.nan
        corr_val = corr_series.dropna().iloc[-1] if not corr_series.dropna().empty else np.nan

        # Kelly fraction on the asset returns
        kelly_val = calculate_kelly(asset_returns)

        results.append(
            {
                "symbol": symbol,
                "beta": beta_val,
                "correlation": corr_val,
                "kelly_fraction": kelly_val,
                "data_days": data_days,
            }
        )

    return pd.DataFrame(results)
