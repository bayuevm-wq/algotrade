import numpy as np
import pandas as pd

from algotrade.backtest import BacktestConfig
from algotrade.data import synthetic_prices
from algotrade.strategies import STRATEGIES
from algotrade.strategies.base import Strategy
from algotrade.walkforward import stitch_oos, walk_forward


class Hold(Strategy):
    name = "hold"

    def generate_signals(self, df):
        return pd.Series(1.0, index=df.index)


def test_cost_charged_at_window_boundary():
    idx = pd.bdate_range("2020-01-01", periods=4)
    flat = pd.Series(0.0, index=idx[:2])
    long = pd.Series(1.0, index=idx[2:])
    _, ret = stitch_oos([flat, long], pd.Series(0.0, index=idx), BacktestConfig())
    # Beli di bar pertama jendela kedua: 0.15% fee + 0.05% slippage
    assert np.allclose(ret.to_numpy(), [0, 0, -0.002, 0])


def test_always_long_equals_benchmark(monkeypatch):
    monkeypatch.setitem(STRATEGIES, "hold", Hold)
    df = synthetic_prices(n=1500)
    table, oos, m, bench = walk_forward(df, "hold", {}, BacktestConfig())
    assert m["total_return"] == bench["total_return"]
    assert m["n_trades"] == 1
    first = df["close"].pct_change().loc[oos.index[0]]
    assert np.isclose(oos.iloc[0], first - 0.002)  # pembelian pertama kena biaya
    assert {"test_return", "bh_return"} <= set(table.columns)
