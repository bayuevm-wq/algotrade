"""Command line.

Contoh:
  python -m algotrade.cli data update
  python -m algotrade.cli backtest
  python -m algotrade.cli backtest --symbol SPY --strategy rsi_meanrev
  python -m algotrade.cli walkforward
  python -m algotrade.cli compare --market us_equity --symbols SPY AAPL
  python -m algotrade.cli backtest --synthetic     # tanpa data
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .backtest import BacktestConfig, run_backtest
from .compare import compare_tickers, format_table, save_csv
from .data import synthetic_prices
from .data.store import Store
from .data_cli import add_data_parser
from .engine.costs import cost_model, vector_config
from .engine.liquidity import INDICATIVE, load_liquidity
from .engine.market_data import DataRejected, find_instrument, load_bars
from .instruments import MARKETS, load_data_config
from .metrics import format_metrics
from .portfolio_cli import add_portfolio_parser
from .report import plot_result
from .research_cli import add_research_parser
from .strategies import get_strategy
from .walkforward import expand_grid, walk_forward

ROOT = Path(__file__).resolve().parents[2]


def _read_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _prepare(args, cfg, symbol: str, market: str | None, timeframe: str,
             haircut: float | None = None):
    """Return (data, konfigurasi biaya, catatan) untuk satu instrumen dari store."""
    data = load_data_config(args.data_config, ROOT)
    store = Store(data.root, data.database)
    ins = find_instrument(data, symbol, market)
    source_note = []
    if args.source and args.source != ins.source:
        backup = [i for i in data.fallbacks if i.symbol == symbol and i.source == args.source]
        if not backup:
            raise DataRejected(f"{symbol} tidak punya sumber '{args.source}' di config.")
        ins = backup[0]
        source_note = [(f"Data {symbol} dari sumber CADANGAN {args.source}; hasilnya tidak "
                        "sama dengan data sumber utama.")]
    bars = load_bars(data, store, ins, timeframe, args.start, args.end, args.allow_stale)
    settings = cfg["backtest"]
    capital = float(settings["initial_capital"])
    notes = source_note
    if bars.warnings:
        notes.append(f"Peringatan data {symbol}: {', '.join(bars.warnings)}")
    liquidity = limit = None
    if ins.market == "dex":
        dex = _read_config(args.portfolio_config)["dex"]
        pool = load_liquidity(store, ins, haircut or dex["liquidity_haircut"])
        liquidity, limit = pool.at(bars.df.index[-1]), dex["max_order_pct_of_liquidity"]
        if not pool.covers(bars.df.index[0], dex["liquidity_history_days"]):
            notes.append(INDICATIVE)
    bt = vector_config(ins, timeframe, capital, settings.get("allow_short", False),
                       liquidity, limit)
    unverified = cost_model(ins).unverified
    if unverified:
        notes.append(f"Biaya PERLU DICEK ({symbol}): {', '.join(unverified)}")
    return bars.df, bt, notes


def _load(args):
    """Config, data, biaya, label, dan catatan untuk `backtest` dan `walkforward`."""
    cfg = _read_config(args.config)
    if args.strategy:
        cfg["strategy"] = {"name": args.strategy, "params": {}}
    if args.synthetic:
        return cfg, synthetic_prices(), BacktestConfig(), "SYNTHETIC", []
    base = cfg["instrument"]
    symbol = args.symbol or base["symbol"]
    market = args.market or (None if args.symbol else base["market"])
    timeframe = args.timeframe or base["timeframe"]
    df, bt, notes = _prepare(args, cfg, symbol, market, timeframe)
    return cfg, df, bt, symbol, notes


def _safe_name(label: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in label)


def cmd_backtest(args):
    cfg, df, bt, label, notes = _load(args)
    strat = get_strategy(cfg["strategy"]["name"], **(cfg["strategy"].get("params") or {}))
    res = run_backtest(df, strat, bt)
    print(f"\n{label} | {strat} | {df.index[0].date()} s/d {df.index[-1].date()}")
    print(f"Dinilai mulai {res.extra['eval_start'].date()} (setelah pemanasan indikator)")
    print("\nStrategi:")
    print(format_metrics(res.metrics))
    print("\nBuy & Hold:")
    print(format_metrics(res.benchmark_metrics))
    print(f"\nTotal biaya transaksi: {res.extra['total_cost_pct']:.2%} dari modal (kumulatif)")
    out = plot_result(res, ROOT / "reports" / f"{_safe_name(label)}_{strat.name}.png",
                      f"{label} — {strat}")
    print(f"Grafik: {out}")
    _print_notes(notes)
    _dex_sensitivity(args, cfg, label, strat)


def _print_notes(notes):
    for note in notes:
        print(f"! {note}")


def _dex_sensitivity(args, cfg, label, strat):
    """Hasil backtest DEX pada beberapa asumsi likuiditas."""
    if args.synthetic:
        return
    data = load_data_config(args.data_config, ROOT)
    market = args.market or (None if args.symbol else cfg["instrument"]["market"])
    if find_instrument(data, label, market).market != "dex":
        return
    print("\nSensitivitas likuiditas pool (INDIKATIF):")
    timeframe = args.timeframe or cfg["instrument"]["timeframe"]
    for haircut in _read_config(args.portfolio_config)["dex"]["sensitivity_haircuts"]:
        try:
            df, bt, _ = _prepare(args, cfg, label, market, timeframe, haircut)
            m = run_backtest(df, strat, bt).metrics
        except ValueError as e:
            print(f"  likuiditas {haircut:.0%}: {e}")
            continue
        print(f"  likuiditas {haircut:.0%}: return {m['total_return']:.2%}, "
              f"Sharpe {m['sharpe']:.2f}")


def cmd_walkforward(args):
    cfg, df, bt, _, notes = _load(args)
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
    _print_notes(notes)


def cmd_compare(args):
    cfg = _read_config(args.config)
    name = args.strategy or cfg["strategy"]["name"]
    # Parameter di config hanya berlaku untuk strategi yang tertulis di config
    same = name == cfg["strategy"]["name"]
    strat = get_strategy(name, **((cfg["strategy"].get("params") or {}) if same else {}))
    base = cfg.get("compare", {})
    market = args.market or base.get("market")
    symbols = args.symbols
    if not symbols and not args.market:
        symbols = base.get("symbols")
    notes: list[str] = []
    configs: dict[str, BacktestConfig] = {}

    if args.synthetic:
        data = {f"SYNTHETIC-{t}": synthetic_prices(seed=42 + i)
                for i, t in enumerate(symbols or ["A", "B"])}
        tickers, loader, costs = list(data), data.__getitem__, BacktestConfig()
    else:
        if not symbols:
            config = load_data_config(args.data_config, ROOT)
            symbols = [i.symbol for i in config.instruments
                       if i.market == market and i.kind != "perp"]
        timeframe = args.timeframe or cfg["instrument"]["timeframe"]
        tickers, costs = symbols, configs.__getitem__

        def loader(t):
            df, configs[t], extra = _prepare(args, cfg, t, market, timeframe)
            notes.extend(extra)
            return df

    table, errors = compare_tickers(tickers, loader, strat, costs)
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
    _print_notes(notes)
    print(f"CSV: {save_csv(table, args.output)}")


def _add_common(s):
    s.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    s.add_argument("--data-config", default=str(ROOT / "config" / "instruments.yaml"))
    s.add_argument("--portfolio-config", default=str(ROOT / "config" / "backtest.yaml"))
    s.add_argument("--market", choices=MARKETS)
    s.add_argument("--timeframe")
    s.add_argument("--source", help="sumber cadangan, mis. indodax (tidak pernah otomatis)")
    s.add_argument("--start", help="tanggal awal data, mis. 2022-01-01")
    s.add_argument("--end", help="tanggal akhir data")
    s.add_argument("--allow-stale", action="store_true", help="izinkan data yang basi")
    s.add_argument("--strategy")
    s.add_argument("--synthetic", action="store_true", help="pakai data palsu (offline)")


def main():
    p = argparse.ArgumentParser(prog="algotrade")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("backtest", cmd_backtest), ("walkforward", cmd_walkforward)]:
        s = sub.add_parser(name)
        _add_common(s)
        s.add_argument("--symbol", help="simbol dari config/instruments.yaml")
        s.set_defaults(func=fn)
    s = sub.add_parser("compare", help="bandingkan strategi vs Buy & Hold di banyak simbol")
    _add_common(s)
    s.add_argument("--symbols", nargs="+", help="default: lihat `compare` di config")
    s.add_argument("--output", default=str(ROOT / "reports" / "compare.csv"))
    s.set_defaults(func=cmd_compare)
    add_data_parser(sub)
    add_portfolio_parser(sub)
    add_research_parser(sub)
    args = p.parse_args()
    try:
        args.func(args)
    except DataRejected as e:                    # penolakan yang disengaja: tanpa traceback
        raise SystemExit(f"DITOLAK: {e}") from e


if __name__ == "__main__":
    main()
