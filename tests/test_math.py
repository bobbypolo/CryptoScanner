"""Tests for math_engine.py — Beta, Correlation, and Kelly Criterion.

All test cases verify the exact mathematical formulas and edge case guards
specified in the QUANT-004 acceptance criteria and quant-math/SPEC.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_scanner.math_engine import (
    calculate_beta,
    calculate_correlation,
    calculate_kelly,
    compute_all_metrics,
)


# ---------------------------------------------------------------------------
# Fixtures: deterministic BTC returns for Beta / Correlation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def btc_returns_60d() -> pd.Series:
    """60 days of deterministic BTC returns using seed(42)."""
    np.random.seed(42)
    return pd.Series(np.random.randn(60) * 0.02)  # ~2% daily vol


# ---------------------------------------------------------------------------
# Beta tests
# ---------------------------------------------------------------------------


class TestBeta:
    """Verify rolling Beta calculation."""

    def test_asset_2x_btc_beta_equals_2(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly 2 * BTC returns -> Beta == 2.0."""
        asset_returns = 2 * btc_returns_60d
        beta = calculate_beta(asset_returns, btc_returns_60d)
        last_beta = beta.dropna().iloc[-1]
        assert np.isclose(last_beta, 2.0, atol=1e-10)

    def test_asset_neg1x_btc_beta_equals_neg1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly -1 * BTC returns -> Beta == -1.0."""
        asset_returns = -1 * btc_returns_60d
        beta = calculate_beta(asset_returns, btc_returns_60d)
        last_beta = beta.dropna().iloc[-1]
        assert np.isclose(last_beta, -1.0, atol=1e-10)

    def test_flat_btc_returns_nan(self) -> None:
        """BTC returns all zeros (zero variance) -> Beta is NaN, not inf."""
        btc_returns = pd.Series(np.zeros(60))
        asset_returns = pd.Series(np.random.randn(60) * 0.02)
        beta = calculate_beta(asset_returns, btc_returns)
        # Every value should be NaN because var is always 0
        assert beta.dropna().empty or pd.isna(beta.dropna().iloc[-1])
        # Specifically: no inf values allowed
        assert not np.any(np.isinf(beta.values))

    def test_insufficient_data_all_nan(self) -> None:
        """Only 15 data points, window=30, min_periods=20 -> all NaN."""
        btc_returns = pd.Series(np.random.randn(15) * 0.02)
        asset_returns = pd.Series(np.random.randn(15) * 0.03)
        beta = calculate_beta(asset_returns, btc_returns, window=30, min_periods=20)
        assert beta.notna().sum() == 0, "Expected all NaN with insufficient data"


# ---------------------------------------------------------------------------
# Correlation tests
# ---------------------------------------------------------------------------


class TestCorrelation:
    """Verify rolling Correlation calculation."""

    def test_asset_2x_btc_corr_equals_1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly 2 * BTC returns -> Correlation == 1.0."""
        asset_returns = 2 * btc_returns_60d
        corr = calculate_correlation(asset_returns, btc_returns_60d)
        last_corr = corr.dropna().iloc[-1]
        assert np.isclose(last_corr, 1.0, atol=1e-10)

    def test_asset_neg1x_btc_corr_equals_neg1(self, btc_returns_60d: pd.Series) -> None:
        """Asset = exactly -1 * BTC returns -> Correlation == -1.0."""
        asset_returns = -1 * btc_returns_60d
        corr = calculate_correlation(asset_returns, btc_returns_60d)
        last_corr = corr.dropna().iloc[-1]
        assert np.isclose(last_corr, -1.0, atol=1e-10)

    def test_insufficient_data_all_nan(self) -> None:
        """Only 15 data points, window=30, min_periods=20 -> all NaN."""
        btc_returns = pd.Series(np.random.randn(15) * 0.02)
        asset_returns = pd.Series(np.random.randn(15) * 0.03)
        corr = calculate_correlation(asset_returns, btc_returns, window=30, min_periods=20)
        assert corr.notna().sum() == 0, "Expected all NaN with insufficient data"


# ---------------------------------------------------------------------------
# Kelly tests
# ---------------------------------------------------------------------------


class TestKelly:
    """Verify Half-Kelly position sizing with all guard clauses."""

    def test_60pct_win_rate_avg_ratio_1_5(self) -> None:
        """60% win rate, avg_win/avg_loss=1.5 -> 0 < Kelly <= 0.25."""
        # 36 wins of +0.03, 24 losses of -0.02  =>  0.03/0.02 = 1.5
        returns = np.array([0.03] * 36 + [-0.02] * 24)
        kelly = calculate_kelly(returns)
        assert kelly > 0, f"Expected Kelly > 0, got {kelly}"
        assert kelly <= 0.25, f"Expected Kelly <= 0.25, got {kelly}"

    def test_30pct_win_rate_avg_ratio_0_8(self) -> None:
        """30% win rate, avg_win/avg_loss=0.8 -> Kelly == 0.0 (no edge)."""
        # 18 wins of +0.016, 42 losses of -0.02  =>  0.016/0.02 = 0.8
        returns = np.array([0.016] * 18 + [-0.02] * 42)
        kelly = calculate_kelly(returns)
        assert kelly == 0.0, f"Expected Kelly == 0.0, got {kelly}"

    def test_90pct_win_rate_capped_at_max(self) -> None:
        """90% win rate -> Kelly <= max_fraction (0.25 cap enforced)."""
        # 54 wins of +0.01, 6 losses of -0.005
        returns = np.array([0.01] * 54 + [-0.005] * 6)
        kelly = calculate_kelly(returns)
        assert kelly <= 0.25, f"Expected Kelly <= 0.25, got {kelly}"
        assert kelly > 0, f"Expected Kelly > 0, got {kelly}"

    def test_all_positive_returns_zero(self) -> None:
        """ALL positive returns (no losses) -> Kelly == 0.0."""
        returns = np.array([0.01] * 60)
        kelly = calculate_kelly(returns)
        assert kelly == 0.0, f"Expected Kelly == 0.0 with no losses, got {kelly}"

    def test_all_negative_returns_zero(self) -> None:
        """ALL negative returns (no wins) -> Kelly == 0.0."""
        returns = np.array([-0.01] * 60)
        kelly = calculate_kelly(returns)
        assert kelly == 0.0, f"Expected Kelly == 0.0 with no wins, got {kelly}"

    def test_insufficient_trades(self) -> None:
        """Fewer than min_trades -> Kelly == 0.0."""
        returns = np.array([0.01] * 10 + [-0.01] * 5)
        kelly = calculate_kelly(returns, min_trades=30)
        assert kelly == 0.0, f"Expected Kelly == 0.0 with insufficient trades"


# ---------------------------------------------------------------------------
# compute_all_metrics tests
# ---------------------------------------------------------------------------


class TestComputeAllMetrics:
    """Verify the master orchestration function."""

    def test_compute_all_metrics_basic(self) -> None:
        """Basic end-to-end: BTC + one altcoin with 60 close prices."""
        np.random.seed(42)
        # Generate 60 BTC close prices
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)
        # Altcoin that amplifies BTC moves: correlated price series
        alt_close = 50 + np.cumsum(np.random.randn(60) * 3)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT/USDT": pd.DataFrame({"close": alt_close}),
        }

        result = compute_all_metrics(ohlcv_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "ALT/USDT"

        # Verify all expected columns
        for col in ["symbol", "beta", "correlation", "kelly_fraction", "data_days"]:
            assert col in result.columns, f"Missing column: {col}"

        # data_days should be count of non-NaN returns (59 max from 60 closes)
        assert result.iloc[0]["data_days"] == 59

    def test_compute_all_metrics_data_days_count(self) -> None:
        """data_days = count of non-NaN values in RETURNS series, not close."""
        btc_close = pd.Series(range(1, 61), dtype=float)
        alt_close = pd.Series(range(1, 61), dtype=float)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT/USDT": pd.DataFrame({"close": alt_close}),
        }

        result = compute_all_metrics(ohlcv_data)
        # 60 closes -> pct_change -> first is NaN -> 59 non-NaN returns
        assert result.iloc[0]["data_days"] == 59

    def test_compute_all_metrics_excludes_btc(self) -> None:
        """BTC/USDT itself should not appear in the results."""
        np.random.seed(42)
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
        }

        result = compute_all_metrics(ohlcv_data)
        assert len(result) == 0

    def test_compute_all_metrics_multiple_altcoins(self) -> None:
        """Multiple altcoins are all processed."""
        np.random.seed(42)
        btc_close = 100 + np.cumsum(np.random.randn(60) * 2)

        ohlcv_data = {
            "BTC/USDT": pd.DataFrame({"close": btc_close}),
            "ALT1/USDT": pd.DataFrame({"close": 50 + np.cumsum(np.random.randn(60))}),
            "ALT2/USDT": pd.DataFrame({"close": 30 + np.cumsum(np.random.randn(60))}),
        }

        result = compute_all_metrics(ohlcv_data)
        assert len(result) == 2
        symbols = set(result["symbol"].tolist())
        assert symbols == {"ALT1/USDT", "ALT2/USDT"}
