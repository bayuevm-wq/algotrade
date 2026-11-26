"""Command line.

Contoh:
  python -m algotrade.cli backtest
  python -m algotrade.cli backtest --ticker BTC-USD --strategy rsi_meanrev
  python -m algotrade.cli walkforward
  python -m algotrade.cli compare --tickers BBCA.JK TLKM.JK
  python -m algotrade.cli backtest --synthetic     # tanpa internet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .backtest import BacktestConfig, run_backtest
from .compare import compare_tickers, format_table, save_csv
from .data import load_prices, synthetic_prices
from .data_cli import add_data_parser
from .metrics import format_metrics
from .report import plot_result
from .strategies import get_strategy
from .walkforward import expand_grid, walk_forward

ROOT = Path(__file__).resolve().parents[2]


def _read_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load(args):
    cfg = _read_config(args.config)
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
    print(f"Dinilai mulai {res.extra['eval_start'].date()} (setelah pemanasan indikator)")
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
    table, oos, m, bench = walk_forward(df, cfg["strategy"]["name"], cfg["param_grid"], bt,
                                       wf.get("train_years", 3), wf.get("test_years", 1),
                                       wf.get("optimize_metric", "sharpe"))
    print("\nHasil per jendela:")
    print(table.to_string(index=False))
    print("\nPerforma OUT-OF-SAMPLE gabungan (ini angka yang lebih jujur):")
    print(format_metrics(m))
    print(f"\nBuy & Hold, periode sama ({oos.index[0].date()} s/d {oos.index[-1].date()}):")
    print(format_metrics(bench))
    n = len(expand_grid(cfg["param_grid"]))
    print(f"\nKombinasi parameter yang dicoba per jendela: {n}")


def cmd_compare(args):
    cfg = _read_config(args.config)
    name = args.strategy or cfg["strategy"]["name"]
    # Parameter di config hanya berlaku untuk strategi yang tertulis di config
    same = name == cfg["strategy"]["name"]
    strat = get_strategy(name, **((cfg["strategy"].get("params") or {}) if same else {}))
    tickers = args.tickers or cfg.get("tickers") or [cfg["ticker"]]

    if args.synthetic:
        data = {f"SYNTHETIC-{t}": synthetic_prices(seed=42 + i) for i, t in enumerate(tickers)}
        tickers, loader = list(data), data.__getitem__
    else:
        def loader(t):
            return load_prices(t, cfg["start"], cfg.get("end"), cfg.get("interval", "1d"))

    table, errors = compare_tickers(tickers, loader, strat,
                                    BacktestConfig.from_dict(cfg["backtest"]))
    for ticker, msg in errors.items():
        print(f"GAGAL {ticker}: {msg}")
    if table.empty:
        raise SystemExit("Tidak ada ticker yang berhasil, CSV tidak ditulis.")

    print(f"\n{strat} vs Buy & Hold\n")
    print(format_table(table))
    print("\nPeriode yang dinilai:")
    for r in table.drop_duplicates("ticker").itertuples():
        print(f"  {r.ticker}: {r.start} s/d {r.end}")
    print("\nBiaya transaksi aktif di kedua versi. 1 kombinasi parameter, tanpa optimasi;")
    print("ini backtest seluruh periode, BUKAN walk-forward out-of-sample.")
    print(f"CSV: {save_csv(table, args.output)}")


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
    s = sub.add_parser("compare", help="bandingkan strategi vs Buy & Hold di banyak ticker")
    s.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    s.add_argument("--tickers", nargs="+", help="default: daftar `tickers` di config")
    s.add_argument("--strategy")
    s.add_argument("--synthetic", action="store_true", help="pakai data palsu (offline)")
    s.add_argument("--output", default=str(ROOT / "reports" / "compare.csv"))
    s.set_defaults(func=cmd_compare)
    add_data_parser(sub)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
