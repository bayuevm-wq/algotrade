"""Plot equity curve & drawdown ke file PNG."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .backtest import BacktestResult


def plot_result(res: BacktestResult, path: str | Path, title: str = "") -> Path:
    d = res.data
    strat = (1 + d["strat_ret"]).cumprod()
    bench = (1 + d["asset_ret"]).cumprod()
    dd = strat / strat.cummax() - 1

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(strat, label="Strategi")
    ax1.plot(bench, label="Buy & Hold", alpha=0.6)
    ax1.set_yscale("log")
    ax1.set_title(title or res.strategy)
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.fill_between(dd.index, dd, 0, color="tab:red", alpha=0.4)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
