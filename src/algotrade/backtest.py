"""Backtester vektor sederhana dengan biaya transaksi.

Model eksekusi:
- Sinyal dihitung di close bar t, posisi dijalankan mulai bar t+1 (shift 1).
  Ini mencegah look-ahead bias.
- Return strategi bar t = posisi(t) * return close-to-close(t) - biaya(t).
- Biaya dikenakan saat posisi berubah: kenaikan posisi kena buy_fee, penurunan kena sell_fee,
  keduanya ditambah slippage.
- Buy & Hold diperlakukan sama: baru beli setelah masa pemanasan (warmup) strategi selesai
  dan membayar biaya beli. Metrik keduanya dihitung pada rentang tanggal yang sama.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from .metrics import compute_metrics
from .research import journal
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
    data: pd.DataFrame          # close, signal, position, asset_ret, cost, strat_ret, bench_ret, equity
    metrics: dict
    benchmark_metrics: dict
    strategy: str = ""
    extra: dict = field(default_factory=dict)


def apply_costs(position: pd.Series, asset_ret: pd.Series,
                cfg: BacktestConfig) -> tuple[pd.Series, pd.Series]:
    """Return (biaya, return bersih) per bar. Posisi sebelum bar pertama dianggap kosong."""
    change = position.diff().fillna(position)
    buy_cost = change.clip(lower=0) * (cfg.buy_fee_pct + cfg.slippage_pct) / 100
    sell_cost = (-change).clip(lower=0) * (cfg.sell_fee_pct + cfg.slippage_pct) / 100
    cost = buy_cost + sell_cost
    return cost, position * asset_ret - cost


def run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig) -> BacktestResult:
    """Backtest satu aset. Data asli dari store otomatis dicatat sebagai percobaan."""
    dataset = df.attrs.get("dataset")
    if not dataset:                                 # data palsu atau buatan tes
        return _run_backtest(df, strategy, cfg)

    def log(**outcome):
        journal.record(
            dataset["journal"], engine="vektor", strategy=strategy.name,
            params=strategy.params, universe={dataset["symbol"]: 1.0},
            timeframe=dataset["timeframe"], modifiers={"allow_short": cfg.allow_short},
            data=df, costs=asdict(cfg), **outcome)

    try:
        result = _run_backtest(df, strategy, cfg)
    except Exception as e:
        log(error=f"{type(e).__name__}: {e}")
        raise
    log(metrics=result.metrics)
    return result


def _run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig) -> BacktestResult:
    first = strategy.warmup + 1                     # bar pertama yang bisa memegang posisi
    if len(df) <= first:
        raise ValueError(f"Data terlalu pendek: {len(df)} bar, butuh lebih dari {first}.")

    signal = strategy.generate_signals(df).reindex(df.index).fillna(0.0)
    if not cfg.allow_short:
        signal = signal.clip(lower=0)
    signal = signal.clip(-1, 1)
    signal.iloc[:strategy.warmup] = 0.0

    position = signal.shift(1).fillna(0.0)          # eksekusi bar berikutnya
    asset_ret = df["close"].pct_change().fillna(0.0)
    cost, strat_ret = apply_costs(position, asset_ret, cfg)
    equity = cfg.initial_capital * (1 + strat_ret).cumprod()

    hold = pd.Series(0.0, index=df.index)
    hold.iloc[first:] = 1.0
    bench_cost, bench_ret = apply_costs(hold, asset_ret, cfg)

    out = pd.DataFrame({
        "close": df["close"], "signal": signal, "position": position,
        "asset_ret": asset_ret, "cost": cost, "strat_ret": strat_ret,
        "bench_ret": bench_ret, "equity": equity,
    })
    return BacktestResult(
        data=out,
        metrics=compute_metrics(strat_ret.iloc[first:], position.iloc[first:],
                                cfg.periods_per_year),
        benchmark_metrics=compute_metrics(bench_ret.iloc[first:], hold.iloc[first:],
                                          cfg.periods_per_year),
        strategy=repr(strategy),
        extra={"total_cost_pct": float(cost.sum()),
               "bench_cost_pct": float(bench_cost.sum()),
               "eval_start": df.index[first]},
    )
