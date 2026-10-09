# ABOUTME: Tests for the next-Mag-7 screen: pure scoring logic plus one live Yahoo fetch.
# ABOUTME: Scoring tests use synthetic frames so they run without network access.

import numpy as np
import pandas as pd
import pytest

from trading_skills.next_mag7 import (
    MAG7,
    UNIVERSE,
    WEIGHTS,
    fetch_fundamentals,
    score_universe,
    trailing_return,
)


def _frame(n=10, **overrides):
    """Synthetic universe where every metric rises with the row number."""
    base = {"symbol": [f"S{i}" for i in range(n)]}
    for col in WEIGHTS:
        base[col] = np.linspace(0.0, 1.0, n)
    base.update(overrides)
    return pd.DataFrame(base)


class TestScoreUniverse:
    def test_best_metrics_rank_first(self):
        out = score_universe(_frame())
        assert out.iloc[0].symbol == "S9"
        assert out.iloc[-1].symbol == "S0"

    def test_rank_index_is_one_based(self):
        out = score_universe(_frame())
        assert out.index[0] == 1
        assert out.index.name == "rank"

    def test_adds_z_column_per_weight(self):
        out = score_universe(_frame())
        for col in WEIGHTS:
            assert f"z_{col}" in out.columns

    def test_missing_value_is_penalised_not_dropped(self):
        roic = np.linspace(0.0, 1.0, 10)
        roic[9] = np.nan
        out = score_universe(_frame(roic=roic))
        assert len(out) == 10
        z_missing = out.loc[out.symbol == "S9", "z_roic"].iloc[0]
        assert z_missing < out["z_roic"].median()

    def test_outlier_is_winsorised(self):
        roic = np.linspace(0.0, 1.0, 20)
        roic[-1] = 1000.0
        out = score_universe(_frame(n=20, roic=roic))
        assert out["z_roic"].max() < 5

    def test_does_not_mutate_input(self):
        df = _frame()
        cols = list(df.columns)
        score_universe(df)
        assert list(df.columns) == cols

    def test_ev_sales_per_growth_skips_non_positive_growth(self):
        growth = np.linspace(-0.1, 0.4, 10)
        df = _frame(rev_cagr_3y=growth, ev_sales=np.full(10, 10.0))
        out = score_universe(df)
        neg = out[out.rev_cagr_3y <= 0]
        assert neg.ev_sales_per_growth.isna().all()


class TestTrailingReturn:
    def test_simple_return(self):
        s = pd.Series([100.0] * 10 + [110.0])
        assert trailing_return(s, 10) == pytest.approx(0.10)

    def test_short_history_is_nan(self):
        s = pd.Series([100.0, 101.0, 102.0])
        assert np.isnan(trailing_return(s, 252))


class TestUniverse:
    def test_excludes_mag7(self):
        assert not MAG7 & set(UNIVERSE)

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)


class TestFetchFundamentals:
    """Live Yahoo Finance call, matching the rest of the suite."""

    def test_returns_inputs_for_valid_symbol(self):
        out = fetch_fundamentals("AVGO")
        assert out is not None
        assert out["symbol"] == "AVGO"
        assert out["mcap_b"] > 0
        assert "rev_cagr_3y" in out
