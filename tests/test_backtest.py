import numpy as np
import pandas as pd
import pytest

from algotrade.backtest import BacktestConfig, run_backtest
from algotrade.data import synthetic_prices
from algotrade.strategies import STRATEGIES, get_strategy
from algotrade.strategies.base import Strategy

NO_COST = BacktestConfig(buy_fee_pct=0, sell_fee_pct=0, slippage_pct=0)


@pytest.fixture
def df():
    return synthetic_prices(n=800)


class Oracle(Strategy):
    """Strategi CURANG: mengintip harga besok (shift(-1)). Tes look-ahead harus menangkapnya."""
    name = "oracle"

    def generate_signals(self, df):
        return (df["close"].shift(-1) > df["close"]).astype(float)


class SameBar(Strategy):
    """Long kalau bar ini naik. Tanpa shift eksekusi, ini = tahu return bar yang sama."""
    name = "same_bar"

    def generate_signals(self, df):
        return (df["close"].pct_change() > 0).astype(float)


def _signals_stable(strat, df, cut=500):
    full = strat.generate_signals(df).iloc[:cut]
    partial = strat.generate_signals(df.iloc[:cut])
    return full.equals(partial)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_no_lookahead(df, name):
    """Sinyal sampai bar t tidak boleh berubah kalau data setelah t diubah/dihapus."""
    assert _signals_stable(get_strategy(name), df)


def test_lookahead_detector_catches_cheater(df):
    assert not _signals_stable(Oracle(), df)


def test_execution_is_shifted(df):
    # Kalau backtester tidak menggeser sinyal, SameBar akan punya Sharpe sangat tinggi.
    res = run_backtest(df, SameBar(), NO_COST)
    assert res.metrics["sharpe"] < 3


def test_buy_and_hold_matches_asset(df):
    class Hold(Strategy):
        name = "hold"

        def generate_signals(self, df):
            return pd.Series(1.0, index=df.index)

    res = run_backtest(df, Hold(), NO_COST)
    # Sinyal bar 0 -> posisi mulai bar 1 -> menangkap return close[0]->close[1] dst.
    expected = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    assert np.isclose(res.metrics["total_return"], expected)


def test_costs_reduce_return(df):
    s = get_strategy("sma_cross", fast=5, slow=20)
    free = run_backtest(df, s, NO_COST).metrics["total_return"]
    paid = run_backtest(df, s, BacktestConfig()).metrics["total_return"]
    assert paid < free


def test_no_short_when_disabled(df):
    class Short(Strategy):
        name = "short"

        def generate_signals(self, df):
            return pd.Series(-1.0, index=df.index)

    res = run_backtest(df, Short(), BacktestConfig(allow_short=False))
    assert (res.data["position"] >= 0).all()


def test_benchmark_starts_with_strategy_and_pays_cost(df):
    res = run_backtest(df, get_strategy("sma_cross", fast=5, slow=20), BacktestConfig())
    start = res.extra["eval_start"]
    assert start == df.index[20]  # sinyal pertama di bar 19, posisi mulai bar 20
    assert (res.data.loc[res.data.index < start, "bench_ret"] == 0).all()
    assert np.isclose(res.data.loc[start, "bench_ret"], res.data.loc[start, "asset_ret"] - 0.002)
    assert res.benchmark_metrics["n_trades"] == 1


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_no_position_during_warmup(df, name):
    strat = get_strategy(name)
    res = run_backtest(df, strat, BacktestConfig())
    assert (res.data["position"].iloc[: strat.warmup + 1] == 0).all()


def test_too_short_data_rejected(df):
    with pytest.raises(ValueError):
        run_backtest(df.iloc[:50], get_strategy("sma_cross"), BacktestConfig())
