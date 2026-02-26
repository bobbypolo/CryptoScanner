"""Tests for the screener engine: filter pipeline & ranking.

All tests mock the ingestion and math engines entirely — ZERO network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from quant_scanner.screener_engine import (
    apply_filters,
    merge_metadata,
    price_sanity_filter,
    run_screen,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TEST_DF = pd.DataFrame(
    [
        # Should PASS all filters
        {
            "symbol": "ALPHA/USDT",
            "name": "Alpha",
            "market_cap": 50_000_000,
            "volume_24h": 5_000_000,
            "beta": 2.5,
            "correlation": 0.9,
            "kelly_fraction": 0.15,
            "circulating_pct": 0.80,
            "data_days": 55,
        },
        {
            "symbol": "BRAVO/USDT",
            "name": "Bravo",
            "market_cap": 80_000_000,
            "volume_24h": 3_000_000,
            "beta": 1.8,
            "correlation": 0.75,
            "kelly_fraction": 0.10,
            "circulating_pct": 0.85,
            "data_days": 50,
        },
        # NaN circulating_pct — should NOT be excluded
        {
            "symbol": "CHARLIE/USDT",
            "name": "Charlie",
            "market_cap": 60_000_000,
            "volume_24h": 2_000_000,
            "beta": 2.0,
            "correlation": 0.80,
            "kelly_fraction": 0.08,
            "circulating_pct": float("nan"),
            "data_days": 45,
        },
        # Beta too low (1.2 < 1.5) — EXCLUDED
        {
            "symbol": "DELTA/USDT",
            "name": "Delta",
            "market_cap": 40_000_000,
            "volume_24h": 4_000_000,
            "beta": 1.2,
            "correlation": 0.85,
            "kelly_fraction": 0.12,
            "circulating_pct": 0.75,
            "data_days": 40,
        },
        # Correlation too low (0.5 < 0.7) — EXCLUDED
        {
            "symbol": "ECHO/USDT",
            "name": "Echo",
            "market_cap": 70_000_000,
            "volume_24h": 6_000_000,
            "beta": 2.0,
            "correlation": 0.5,
            "kelly_fraction": 0.11,
            "circulating_pct": 0.90,
            "data_days": 50,
        },
        # Volume too low (500k < 1M) — EXCLUDED
        {
            "symbol": "FOXTROT/USDT",
            "name": "Foxtrot",
            "market_cap": 90_000_000,
            "volume_24h": 500_000,
            "beta": 1.9,
            "correlation": 0.88,
            "kelly_fraction": 0.09,
            "circulating_pct": 0.72,
            "data_days": 55,
        },
        # data_days too low (15 < 20) — EXCLUDED
        {
            "symbol": "GOLF/USDT",
            "name": "Golf",
            "market_cap": 55_000_000,
            "volume_24h": 2_500_000,
            "beta": 2.1,
            "correlation": 0.82,
            "kelly_fraction": 0.07,
            "circulating_pct": 0.88,
            "data_days": 15,
        },
        # total_supply=0 scenario (circulating_pct=NaN from merge_metadata)
        {
            "symbol": "HOTEL/USDT",
            "name": "Hotel",
            "market_cap": 45_000_000,
            "volume_24h": 1_500_000,
            "beta": 1.7,
            "correlation": 0.78,
            "kelly_fraction": 0.06,
            "circulating_pct": float("nan"),
            "data_days": 40,
        },
    ]
)


def _filtered() -> pd.DataFrame:
    """Return the test DataFrame after apply_filters with defaults."""
    return apply_filters(_TEST_DF.copy())


# ---------------------------------------------------------------------------
# apply_filters tests
# ---------------------------------------------------------------------------


class TestApplyFilters:
    """Tests for the apply_filters() function."""

    def test_low_beta_excluded(self) -> None:
        """DELTA (beta=1.2 < 1.5) must be excluded from results."""
        result = _filtered()
        assert "DELTA/USDT" not in result["symbol"].values

    def test_low_correlation_excluded(self) -> None:
        """ECHO (correlation=0.5 < 0.7) must be excluded from results."""
        result = _filtered()
        assert "ECHO/USDT" not in result["symbol"].values

    def test_low_volume_excluded(self) -> None:
        """FOXTROT (volume=500k < 1M) must be excluded from results."""
        result = _filtered()
        assert "FOXTROT/USDT" not in result["symbol"].values

    def test_low_data_days_excluded(self) -> None:
        """GOLF (data_days=15 < 20) must be excluded from results."""
        result = _filtered()
        assert "GOLF/USDT" not in result["symbol"].values

    def test_nan_circulating_pct_not_excluded(self) -> None:
        """CHARLIE (circulating_pct=NaN) must NOT be excluded.

        The supply check is skipped when data is unavailable.
        """
        result = _filtered()
        assert "CHARLIE/USDT" in result["symbol"].values

    def test_sorted_by_beta_descending(self) -> None:
        """Output must be sorted by beta descending.

        Expected order: ALPHA (2.5), CHARLIE (2.0), BRAVO (1.8), HOTEL (1.7).
        """
        result = _filtered()
        betas = result["beta"].tolist()
        assert betas == sorted(betas, reverse=True)
        # Verify exact expected survivors and order
        expected_symbols = [
            "ALPHA/USDT",   # beta=2.5
            "CHARLIE/USDT", # beta=2.0
            "BRAVO/USDT",   # beta=1.8
            "HOTEL/USDT",   # beta=1.7
        ]
        assert result["symbol"].tolist() == expected_symbols

    def test_empty_dataframe(self) -> None:
        """apply_filters on an empty DataFrame returns an empty DataFrame."""
        empty = pd.DataFrame(columns=_TEST_DF.columns)
        result = apply_filters(empty)
        assert result.empty

    def test_all_excluded(self) -> None:
        """If min_beta is extremely high, nothing passes."""
        result = apply_filters(_TEST_DF.copy(), min_beta=100.0)
        assert result.empty

    def test_output_columns(self) -> None:
        """Result must have exactly the expected output columns."""
        result = _filtered()
        expected_cols = [
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
        assert list(result.columns) == expected_cols


# ---------------------------------------------------------------------------
# merge_metadata tests
# ---------------------------------------------------------------------------


class TestMergeMetadata:
    """Tests for the merge_metadata() function."""

    def test_zero_total_supply_circulating_pct_nan(self) -> None:
        """When total_supply=0, circulating_pct must be NaN (not ZeroDivisionError)."""
        coins = [
            {
                "symbol": "hotel",
                "name": "Hotel",
                "market_cap": 45_000_000,
                "total_volume": 1_500_000,
                "circulating_supply": 100_000_000,
                "total_supply": 0,
                "market_cap_rank": 200,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "HOTEL/USDT",
                    "beta": 1.7,
                    "correlation": 0.78,
                    "kelly_fraction": 0.06,
                    "data_days": 40,
                },
            ]
        )
        result = merge_metadata(coins, metrics)

        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "HOTEL/USDT"
        # circulating_pct must be NaN — NOT a ZeroDivisionError
        assert np.isnan(result.iloc[0]["circulating_pct"])

    def test_none_total_supply_circulating_pct_nan(self) -> None:
        """When total_supply is None, circulating_pct must be NaN."""
        coins = [
            {
                "symbol": "xtoken",
                "name": "XToken",
                "market_cap": 30_000_000,
                "total_volume": 2_000_000,
                "circulating_supply": 50_000_000,
                "total_supply": None,
                "market_cap_rank": 150,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "XTOKEN/USDT",
                    "beta": 1.9,
                    "correlation": 0.81,
                    "kelly_fraction": 0.10,
                    "data_days": 50,
                },
            ]
        )
        result = merge_metadata(coins, metrics)
        assert np.isnan(result.iloc[0]["circulating_pct"])

    def test_none_circulating_supply_circulating_pct_nan(self) -> None:
        """When circulating_supply is None, circulating_pct must be NaN."""
        coins = [
            {
                "symbol": "ytoken",
                "name": "YToken",
                "market_cap": 40_000_000,
                "total_volume": 3_000_000,
                "circulating_supply": None,
                "total_supply": 100_000_000,
                "market_cap_rank": 180,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "YTOKEN/USDT",
                    "beta": 2.1,
                    "correlation": 0.85,
                    "kelly_fraction": 0.12,
                    "data_days": 55,
                },
            ]
        )
        result = merge_metadata(coins, metrics)
        assert np.isnan(result.iloc[0]["circulating_pct"])

    def test_normal_circulating_pct(self) -> None:
        """Normal circulating_pct = circulating_supply / total_supply."""
        coins = [
            {
                "symbol": "alpha",
                "name": "Alpha",
                "market_cap": 50_000_000,
                "total_volume": 5_000_000,
                "circulating_supply": 80_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 100,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "ALPHA/USDT",
                    "beta": 2.5,
                    "correlation": 0.9,
                    "kelly_fraction": 0.15,
                    "data_days": 55,
                },
            ]
        )
        result = merge_metadata(coins, metrics)
        assert np.isclose(result.iloc[0]["circulating_pct"], 0.80)

    def test_volume_24h_from_total_volume(self) -> None:
        """volume_24h column should be mapped from CoinGecko's total_volume."""
        coins = [
            {
                "symbol": "bravo",
                "name": "Bravo",
                "market_cap": 80_000_000,
                "total_volume": 3_000_000,
                "circulating_supply": 85_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 120,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "BRAVO/USDT",
                    "beta": 1.8,
                    "correlation": 0.75,
                    "kelly_fraction": 0.10,
                    "data_days": 50,
                },
            ]
        )
        result = merge_metadata(coins, metrics)
        assert result.iloc[0]["volume_24h"] == 3_000_000

    def test_join_on_symbol(self) -> None:
        """Metrics and CG metadata join on uppercased symbol + '/USDT'."""
        coins = [
            {
                "symbol": "alpha",
                "name": "Alpha",
                "market_cap": 50_000_000,
                "total_volume": 5_000_000,
                "circulating_supply": 80_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 100,
            },
            {
                "symbol": "bravo",
                "name": "Bravo",
                "market_cap": 80_000_000,
                "total_volume": 3_000_000,
                "circulating_supply": 85_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 120,
            },
        ]
        metrics = pd.DataFrame(
            [
                {
                    "symbol": "ALPHA/USDT",
                    "beta": 2.5,
                    "correlation": 0.9,
                    "kelly_fraction": 0.15,
                    "data_days": 55,
                },
                {
                    "symbol": "BRAVO/USDT",
                    "beta": 1.8,
                    "correlation": 0.75,
                    "kelly_fraction": 0.10,
                    "data_days": 50,
                },
            ]
        )
        result = merge_metadata(coins, metrics)
        assert len(result) == 2
        assert result.iloc[0]["name"] == "Alpha"
        assert result.iloc[1]["name"] == "Bravo"

    def test_empty_metrics(self) -> None:
        """merge_metadata with empty metrics returns empty DataFrame."""
        coins = [
            {
                "symbol": "alpha",
                "name": "Alpha",
                "market_cap": 50_000_000,
                "total_volume": 5_000_000,
                "circulating_supply": 80_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 100,
            },
        ]
        metrics = pd.DataFrame(
            columns=["symbol", "beta", "correlation", "kelly_fraction", "data_days"]
        )
        result = merge_metadata(coins, metrics)
        assert result.empty


# ---------------------------------------------------------------------------
# run_screen integration test (fully mocked)
# ---------------------------------------------------------------------------


class TestRunScreen:
    """Integration tests for run_screen() with fully mocked dependencies."""

    async def test_run_screen_full_pipeline(self) -> None:
        """run_screen orchestrates all steps and returns filtered results."""
        # Prepare mock data
        mock_coins = [
            {
                "symbol": "alpha",
                "name": "Alpha",
                "market_cap": 50_000_000,
                "total_volume": 5_000_000,
                "circulating_supply": 80_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 100,
                "current_price": 3.0,
            },
            {
                "symbol": "bravo",
                "name": "Bravo",
                "market_cap": 80_000_000,
                "total_volume": 3_000_000,
                "circulating_supply": 85_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 120,
                "current_price": 0.8,
            },
        ]

        mock_symbols = ["ALPHA/USDT", "BRAVO/USDT"]

        # Build minimal OHLCV DataFrames (60 days of close prices)
        dates = pd.date_range("2026-01-01", periods=60, freq="D", tz="UTC")
        btc_df = pd.DataFrame(
            {"close": np.linspace(40000, 45000, 60)}, index=dates
        )
        alpha_df = pd.DataFrame(
            {"close": np.linspace(1.0, 3.0, 60)}, index=dates
        )
        bravo_df = pd.DataFrame(
            {"close": np.linspace(0.5, 0.8, 60)}, index=dates
        )
        mock_ohlcv = {
            "BTC/USDT": btc_df,
            "ALPHA/USDT": alpha_df,
            "BRAVO/USDT": bravo_df,
        }

        mock_metrics = pd.DataFrame(
            [
                {
                    "symbol": "ALPHA/USDT",
                    "beta": 2.5,
                    "correlation": 0.9,
                    "kelly_fraction": 0.15,
                    "data_days": 55,
                },
                {
                    "symbol": "BRAVO/USDT",
                    "beta": 1.8,
                    "correlation": 0.75,
                    "kelly_fraction": 0.10,
                    "data_days": 50,
                },
            ]
        )

        # Mock symbol→exchange mapping for multi-exchange path
        mock_symbol_exchange_map = {
            "ALPHA/USDT": "kucoin",
            "BRAVO/USDT": "kucoin",
        }

        # Mock exchange instances for load_markets in run_screen
        mock_exchange_inst = AsyncMock()
        mock_exchange_inst.markets = {
            "ALPHA/USDT": {},
            "BRAVO/USDT": {},
            "BTC/USDT": {},
        }

        # Patch ccxt_async so getattr(ccxt_async, exchange_id)({...})
        # returns our mock exchange instance for any exchange
        mock_ccxt_module = AsyncMock()
        for eid in ("kucoin", "okx", "gate", "binance"):
            setattr(mock_ccxt_module, eid, lambda opts, _m=mock_exchange_inst: _m)

        with (
            patch(
                "quant_scanner.screener_engine.fetch_universe",
                new_callable=AsyncMock,
                return_value=mock_coins,
            ),
            patch(
                "quant_scanner.screener_engine.map_coingecko_to_ccxt_multi",
                return_value=mock_symbol_exchange_map,
            ),
            patch(
                "quant_scanner.screener_engine.fetch_historical_data_multi",
                new_callable=AsyncMock,
                return_value=mock_ohlcv,
            ),
            patch(
                "quant_scanner.screener_engine.compute_all_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "quant_scanner.screener_engine.ccxt_async",
                mock_ccxt_module,
            ),
        ):
            result = await run_screen()

        assert not result.empty
        # Both coins should pass default filters
        assert "ALPHA/USDT" in result["symbol"].values
        assert "BRAVO/USDT" in result["symbol"].values
        # Sorted by beta descending: ALPHA first
        assert result.iloc[0]["symbol"] == "ALPHA/USDT"

    async def test_run_screen_empty_universe(self) -> None:
        """run_screen returns empty DataFrame when no coins from universe."""
        with patch(
            "quant_scanner.screener_engine.fetch_universe",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await run_screen()

        assert result.empty

    async def test_run_screen_no_symbols_mapped(self) -> None:
        """run_screen returns empty DataFrame when no symbols map to exchange."""
        mock_coins = [
            {
                "symbol": "alpha",
                "name": "Alpha",
                "market_cap": 50_000_000,
                "total_volume": 5_000_000,
                "circulating_supply": 80_000_000,
                "total_supply": 100_000_000,
                "market_cap_rank": 100,
            },
        ]

        mock_exchange_inst = AsyncMock()
        mock_exchange_inst.markets = {}

        mock_ccxt_module = AsyncMock()
        for eid in ("kucoin", "okx", "gate", "binance"):
            setattr(mock_ccxt_module, eid, lambda opts, _m=mock_exchange_inst: _m)

        with (
            patch(
                "quant_scanner.screener_engine.fetch_universe",
                new_callable=AsyncMock,
                return_value=mock_coins,
            ),
            patch(
                "quant_scanner.screener_engine.map_coingecko_to_ccxt_multi",
                return_value={},
            ),
            patch(
                "quant_scanner.screener_engine.ccxt_async",
                mock_ccxt_module,
            ),
        ):
            result = await run_screen()

        assert result.empty


# ---------------------------------------------------------------------------
# price_sanity_filter tests
# ---------------------------------------------------------------------------


class TestPriceSanityFilter:
    """Tests for the price_sanity_filter() function."""

    def _make_coins(self, symbol: str, current_price):
        return [{"symbol": symbol, "name": symbol.upper(), "current_price": current_price}]

    def _make_ohlcv(self, symbol: str, last_close: float):
        ccxt_sym = symbol.upper() + "/USDT"
        btc_df = pd.DataFrame({"close": [40000.0, 41000.0, 42000.0]})
        alt_df = pd.DataFrame({"close": [last_close - 0.1, last_close - 0.05, last_close]})
        return {"BTC/USDT": btc_df, ccxt_sym: alt_df}

    def test_matching_price_kept(self) -> None:
        """Coin with matching CG and OHLCV price is kept."""
        coins = self._make_coins("alpha", 1.0)
        ohlcv = self._make_ohlcv("alpha", 1.0)
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" in filtered_ohlcv
        assert len(filtered_coins) == 1

    def test_divergent_price_dropped(self) -> None:
        """Coin with >15% divergence is dropped from both coins and ohlcv."""
        coins = self._make_coins("alpha", 1.0)
        ohlcv = self._make_ohlcv("alpha", 2.0)  # 100% divergence
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" not in filtered_ohlcv
        assert len(filtered_coins) == 0

    def test_boundary_14pct_kept(self) -> None:
        """14% divergence is within 15% threshold — coin kept."""
        coins = self._make_coins("alpha", 1.0)
        ohlcv = self._make_ohlcv("alpha", 0.86)  # 14% divergence
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" in filtered_ohlcv

    def test_boundary_17pct_dropped(self) -> None:
        """17% divergence exceeds 15% threshold — coin dropped."""
        coins = self._make_coins("alpha", 1.0)
        ohlcv = self._make_ohlcv("alpha", 0.83)  # 17% divergence
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" not in filtered_ohlcv

    def test_none_price_kept(self) -> None:
        """Coin with current_price=None is kept (fail-open)."""
        coins = self._make_coins("alpha", None)
        ohlcv = self._make_ohlcv("alpha", 999.0)
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" in filtered_ohlcv
        assert len(filtered_coins) == 1

    def test_empty_ohlcv_kept(self) -> None:
        """Coin with empty OHLCV DataFrame is kept (fail-open)."""
        coins = self._make_coins("alpha", 1.0)
        ohlcv = {"BTC/USDT": pd.DataFrame({"close": [40000.0]}), "ALPHA/USDT": pd.DataFrame()}
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" in filtered_ohlcv

    def test_zero_price_kept(self) -> None:
        """Coin with current_price=0 is kept (fail-open)."""
        coins = self._make_coins("alpha", 0)
        ohlcv = self._make_ohlcv("alpha", 5.0)
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert "ALPHA/USDT" in filtered_ohlcv

    def test_coins_list_also_filtered(self) -> None:
        """When a symbol is dropped, the coins list is also filtered."""
        coins = [
            {"symbol": "alpha", "name": "Alpha", "current_price": 1.0},
            {"symbol": "bravo", "name": "Bravo", "current_price": 5.0},
        ]
        btc_df = pd.DataFrame({"close": [40000.0, 41000.0]})
        alpha_df = pd.DataFrame({"close": [1.0, 1.02]})  # close to CG
        bravo_df = pd.DataFrame({"close": [50.0, 50.5]})  # 10x divergence
        ohlcv = {"BTC/USDT": btc_df, "ALPHA/USDT": alpha_df, "BRAVO/USDT": bravo_df}
        filtered_coins, filtered_ohlcv = price_sanity_filter(coins, ohlcv)
        assert len(filtered_coins) == 1
        assert filtered_coins[0]["symbol"] == "alpha"
        assert "ALPHA/USDT" in filtered_ohlcv
        assert "BRAVO/USDT" not in filtered_ohlcv
        assert "BTC/USDT" in filtered_ohlcv  # BTC always preserved
