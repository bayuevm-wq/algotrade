"""Walk-forward optimization.

Untuk tiap jendela: cari parameter terbaik di data TRAIN, lalu ukur di data TEST berikutnya
yang tidak pernah dilihat. Gabungan semua periode TEST = perkiraan performa yang lebih jujur.
Biaya dihitung dari posisi gabungan, sehingga pembelian pertama dan pergantian posisi di batas
jendela ikut dikenai biaya. Buy & Hold dihitung pada tanggal yang sama dan juga kena biaya beli.
"""

from __future__ import annotations

import itertools
import math

import pandas as pd

from .backtest import BacktestConfig, apply_costs, run_backtest
from .metrics import compute_metrics
from .strategies import get_strategy


def expand_grid(param_grid: dict) -> list[dict]:
    keys = list(param_grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*param_grid.values())]


def stitch_oos(positions: list[pd.Series], asset_ret: pd.Series,
               cfg: BacktestConfig) -> tuple[pd.Series, pd.Series]:
    """Sambung posisi semua jendela test, lalu hitung biaya. Return (posisi, return bersih)."""
    position = pd.concat(positions)
    _, ret = apply_costs(position, asset_ret.loc[position.index], cfg)
    return position, ret


def walk_forward(df: pd.DataFrame, strategy_name: str, param_grid: dict, cfg: BacktestConfig,
                 train_years: float = 3, test_years: float = 1,
                 metric: str = "sharpe") -> tuple[pd.DataFrame, pd.Series, dict, dict]:
    """Return (tabel per jendela, return OOS, metrik OOS, metrik Buy & Hold OOS)."""
    rows, positions = [], []
    start = df.index[0]
    while True:
        train_end = start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if train_end >= df.index[-1]:
            break
        train = df[(df.index >= start) & (df.index < train_end)]

        best, best_score = None, -float("inf")
        for params in expand_grid(param_grid):
            try:
                strat = get_strategy(strategy_name, **params)
            except ValueError:  # kombinasi parameter tidak valid (mis. fast >= slow)
                continue
            if len(train) <= strat.warmup + 1:
                continue
            # Skor dihitung di seluruh train agar semua kombinasi dinilai pada tanggal yang sama
            d = run_backtest(train, strat, cfg).data
            score = compute_metrics(d["strat_ret"], d["position"],
                                    cfg.periods_per_year).get(metric, float("nan"))
            if not math.isnan(score) and score > best_score:
                best, best_score = params, score
        if best is None:
            break

        # Jalankan di train+test agar indikator punya warm-up, lalu ambil bagian test saja
        window = df[(df.index >= start) & (df.index < test_end)]
        res = run_backtest(window, get_strategy(strategy_name, **best), cfg)
        test_pos = res.data.loc[res.data.index >= train_end, "position"]
        if test_pos.empty:
            break
        rows.append({"train_start": start.date(), "test_start": train_end.date(),
                     "test_end": test_pos.index[-1].date(), **best,
                     f"train_{metric}": round(best_score, 3)})
        positions.append(test_pos)
        start = start + pd.DateOffset(years=test_years)

    if not positions:
        raise ValueError("Data terlalu pendek untuk walk-forward dengan pengaturan ini.")
    asset_ret = df["close"].pct_change().fillna(0.0)
    position, oos_ret = stitch_oos(positions, asset_ret, cfg)
    hold, bench_ret = stitch_oos([pd.Series(1.0, index=position.index)], asset_ret, cfg)

    for row, window_pos in zip(rows, positions):
        r = oos_ret.loc[window_pos.index]
        m = compute_metrics(r, window_pos, cfg.periods_per_year)
        row["test_sharpe"] = round(m["sharpe"], 3)
        row["test_return"] = round(m["total_return"], 4)
        row["bh_return"] = round(float((1 + bench_ret.loc[window_pos.index]).prod() - 1), 4)
    return (pd.DataFrame(rows), oos_ret,
            compute_metrics(oos_ret, position, cfg.periods_per_year),
            compute_metrics(bench_ret, hold, cfg.periods_per_year))
