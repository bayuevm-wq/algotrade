"""Backtester vektor sederhana dengan biaya transaksi.

Model eksekusi:
- Sinyal dihitung di close bar t, posisi dijalankan mulai bar t+1 (shift 1).
  Ini mencegah look-ahead bias.
- Return strategi bar t = posisi(t) * return close-to-close(t) - biaya(t).
- Biaya dikenakan saat posisi berubah: kenaikan posisi kena buy_fee, penurunan kena sell_fee,
  keduanya ditambah slippage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .metrics import compute_metrics
from .strategies.base import Strategy


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000_000
    allow_short: bool = False
    buy_fee_pct: float = 0.15
    sell_fee_pct: float = 0.25
    slippage_pct: float = 0.05
    periods_per_year: int = 252

    @classmethod
    def from_dict(cls, d: dict) -> BacktestConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BacktestResult:
    data: pd.DataFrame          # kolom: close, signal, position, asset_ret, cost, strat_ret, equity
    metrics: dict
    benchmark_metrics: dict
    strategy: str = ""
    extra: dict = field(default_factory=dict)


def run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig) -> BacktestResult:
    signal = strategy.generate_signals(df).reindex(df.index).fillna(0.0)
    if not cfg.allow_short:
        signal = signal.clip(lower=0)
    signal = signal.clip(-1, 1)

    position = signal.shift(1).fillna(0.0)          # eksekusi bar berikutnya
    asset_ret = df["close"].pct_change().fillna(0.0)

    change = position.diff().fillna(position)
    buy_cost = change.clip(lower=0) * (cfg.buy_fee_pct + cfg.slippage_pct) / 100
    sell_cost = (-change).clip(lower=0) * (cfg.sell_fee_pct + cfg.slippage_pct) / 100
    cost = buy_cost + sell_cost

    strat_ret = position * asset_ret - cost
    equity = cfg.initial_capital * (1 + strat_ret).cumprod()

    out = pd.DataFrame({
        "close": df["close"], "signal": signal, "position": position,
        "asset_ret": asset_ret, "cost": cost, "strat_ret": strat_ret, "equity": equity,
    })
    return BacktestResult(
        data=out,
        metrics=compute_metrics(strat_ret, position, cfg.periods_per_year),
        benchmark_metrics=compute_metrics(asset_ret, None, cfg.periods_per_year),
        strategy=repr(strategy),
        extra={"total_cost_pct": float(cost.sum())},
    )
