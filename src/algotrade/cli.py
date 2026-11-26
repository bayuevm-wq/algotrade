"""Command line.

Contoh:
  python -m algotrade.cli backtest
  python -m algotrade.cli backtest --ticker BTC-USD --strategy rsi_meanrev
  python -m algotrade.cli walkforward
  python -m algotrade.cli backtest --synthetic     # tanpa internet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .backtest import BacktestConfig, run_backtest
from .data import load_prices, synthetic_prices
from .metrics import format_metrics
from .report import plot_result
from .strategies import get_strategy
from .walkforward import walk_forward

ROOT = Path(__file__).resolve().parents[2]


def _load(args):
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if args.ticker:
        cfg["ticker"] = args.ticker
    if args.strategy:
        cfg["strategy"] = {"name": args.strategy, "params": {}}
    df = synthetic_prices() if args.synthetic else load_prices(
        cfg["ticker"], cfg["start"], cfg.get("end"), cfg.get("interval", "1d"))
    return cfg, df, BacktestConfig.from_dict(cfg["backtest"])


def cmd_backtest(args):
    cfg, df, bt = _load(args)
    strat = get_strategy(cfg["strategy"]["name"], **(cfg["strategy"].get("params") or {}))
    res = run_backtest(df, strat, bt)
    label = "SYNTHETIC" if args.synthetic else cfg["ticker"]
    print(f"\n{label} | {strat} | {df.index[0].date()} s/d {df.index[-1].date()}")
    print("\nStrategi:")
    print(format_metrics(res.metrics))
    print("\nBuy & Hold:")
    print(format_metrics(res.benchmark_metrics))
    print(f"\nTotal biaya transaksi: {res.extra['total_cost_pct']:.2%} dari modal (kumulatif)")
    out = plot_result(res, ROOT / "reports" / f"{label}_{strat.name}.png",
                      f"{label} — {strat}")
    print(f"Grafik: {out}")


def cmd_walkforward(args):
    cfg, df, bt = _load(args)
    wf = cfg.get("walkforward", {})
    table, _, m = walk_forward(df, cfg["strategy"]["name"], cfg["param_grid"], bt,
                               wf.get("train_years", 3), wf.get("test_years", 1),
                               wf.get("optimize_metric", "sharpe"))
    print("\nHasil per jendela:")
    print(table.to_string(index=False))
    print("\nPerforma OUT-OF-SAMPLE gabungan (ini angka yang lebih jujur):")
    print(format_metrics(m))


def main():
    p = argparse.ArgumentParser(prog="algotrade")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("backtest", cmd_backtest), ("walkforward", cmd_walkforward)]:
        s = sub.add_parser(name)
        s.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
        s.add_argument("--ticker")
        s.add_argument("--strategy")
        s.add_argument("--synthetic", action="store_true", help="pakai data palsu (offline)")
        s.set_defaults(func=fn)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
