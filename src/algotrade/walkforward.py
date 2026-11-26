"""Walk-forward optimization.

Untuk tiap jendela: cari parameter terbaik di data TRAIN, lalu ukur di data TEST berikutnya
yang tidak pernah dilihat. Gabungan semua periode TEST = perkiraan performa yang lebih jujur.
"""

from __future__ import annotations

import itertools
import math

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .metrics import compute_metrics
from .strategies import get_strategy


def _grid(param_grid: dict) -> list[dict]:
    keys = list(param_grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*param_grid.values())]


def walk_forward(df: pd.DataFrame, strategy_name: str, param_grid: dict, cfg: BacktestConfig,
                 train_years: float = 3, test_years: float = 1,
                 metric: str = "sharpe") -> tuple[pd.DataFrame, pd.Series, dict]:
    """Return (tabel per jendela, return OOS gabungan, metrik OOS)."""
    rows, oos = [], []
    start = df.index[0]
    while True:
        train_end = start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if train_end >= df.index[-1]:
            break
        train = df[(df.index >= start) & (df.index < train_end)]

        best, best_score = None, -float("inf")
        for params in _grid(param_grid):
            try:
                strat = get_strategy(strategy_name, **params)
            except ValueError:  # kombinasi parameter tidak valid (mis. fast >= slow)
                continue
            score = run_backtest(train, strat, cfg).metrics.get(metric, float("nan"))
            if not math.isnan(score) and score > best_score:
                best, best_score = params, score
        if best is None:
            break

        # Jalankan di train+test agar indikator punya warm-up, lalu ambil bagian test saja
        window = df[(df.index >= start) & (df.index < test_end)]
        res = run_backtest(window, get_strategy(strategy_name, **best), cfg)
        test_ret = res.data.loc[res.data.index >= train_end, "strat_ret"]
        test_pos = res.data.loc[res.data.index >= train_end, "position"]
        if test_ret.empty:
            break
        m = compute_metrics(test_ret, test_pos, cfg.periods_per_year)
        rows.append({"train_start": start.date(), "test_start": train_end.date(),
                     "test_end": test_ret.index[-1].date(), **best,
                     f"train_{metric}": round(best_score, 3),
                     "test_sharpe": round(m["sharpe"], 3),
                     "test_return": round(m["total_return"], 4)})
        oos.append(test_ret)
        start = start + pd.DateOffset(years=test_years)

    if not oos:
        raise ValueError("Data terlalu pendek untuk walk-forward dengan pengaturan ini.")
    oos_ret = pd.concat(oos)
    return pd.DataFrame(rows), oos_ret, compute_metrics(oos_ret, None, cfg.periods_per_year)
