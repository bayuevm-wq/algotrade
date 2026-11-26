"""Bandingkan satu strategi dengan Buy & Hold di banyak ticker."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .strategies.base import Strategy

PCT = ["total_return", "cagr", "volatility", "max_drawdown", "exposure", "total_cost"]
METRICS = ["total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown",
           "exposure", "n_trades"]


def compare_tickers(tickers: list[str], loader: Callable[[str], pd.DataFrame],
                    strategy: Strategy, cfg: BacktestConfig
                    ) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return (tabel dua baris per ticker, pesan error per ticker yang gagal)."""
    rows, errors = [], {}
    for ticker in tickers:
        try:
            df = loader(ticker)
            res = run_backtest(df, strategy, cfg)
        except Exception as e:  # noqa: BLE001 - satu ticker gagal tidak boleh menghentikan yang lain
            errors[ticker] = str(e)
            continue
        for version, m, cost in [
            ("Strategi", res.metrics, res.extra["total_cost_pct"]),
            ("Buy & Hold", res.benchmark_metrics, res.extra["bench_cost_pct"]),
        ]:
            rows.append({"ticker": ticker, "strategy": strategy.name, "version": version,
                         "start": res.extra["eval_start"].date(), "end": df.index[-1].date(),
                         **{k: m[k] for k in METRICS}, "total_cost": cost})
    return pd.DataFrame(rows), errors


def format_table(table: pd.DataFrame) -> str:
    """Tabel ringkas untuk terminal."""
    t = table.drop(columns=["strategy", "start", "end"])
    for c in PCT:
        t[c] = t[c].map("{:.2%}".format)
    for c in ["sharpe", "sortino"]:
        t[c] = t[c].map("{:.2f}".format)
    return t.to_string(index=False)


def save_csv(table: pd.DataFrame, path: str | Path) -> Path:
    """Simpan angka mentah (pecahan, bukan persen) ke CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)
    return path
