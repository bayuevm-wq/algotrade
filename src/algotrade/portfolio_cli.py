"""Perintah `algotrade portfolio`: backtest multi-aset dengan modal bersama."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from .data.store import Store
from .engine import funding as fund
from .engine import tearsheet
from .engine.liquidity import load_liquidity
from .engine.runner import plan, prepare, run_period
from .instruments import load_data_config

ROOT = Path(__file__).resolve().parents[2]


def _load_config(args) -> dict:
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if args.symbols:
        cfg["instruments"] = [{"symbol": s, "weight": 1 / len(args.symbols)}
                              for s in args.symbols]
    if args.strategy:
        cfg["strategy"] = {"name": args.strategy, "params": {}}
    for key in ["timeframe", "start", "end"]:
        if getattr(args, key):
            cfg[key] = getattr(args, key)
    if args.capital:
        cfg["capital_usd"] = args.capital
    if args.leverage:
        cfg["perp"]["leverage"] = args.leverage
    if args.allow_short:
        cfg["allow_short"] = True
    stops = cfg.get("stops") or {}
    if args.stop_loss:
        stops["stop_loss_pct"] = args.stop_loss
    if args.take_profit:
        stops["take_profit_pct"] = args.take_profit
    cfg["stops"] = stops
    return cfg


def _line(label: str, run) -> str:
    s, b = run.strategy.metrics, run.benchmark.metrics
    return (f"  {label:<28} strategi {s['total_return']:>9.2%} (Sharpe {s['sharpe']:5.2f}, "
            f"likuidasi {run.strategy.liquidations}) | B&H {b['total_return']:>9.2%}")


def cmd_portfolio(args):
    cfg = _load_config(args)
    data = load_data_config(args.data_config, ROOT)
    store = Store(data.root, data.database)
    p = prepare(data, store, cfg, args.allow_stale)
    periods, overlap = plan(data, store, p)
    folder = Path(args.reports)
    indicative = any("INDIKATIF" in n for n in p.notes)
    has_perp = any(a.instrument.kind == "perp" for a in p.assets)
    names = ", ".join(f"{a.instrument.symbol} {a.weight:.0%}" for a in p.assets)
    print(f"\nPortofolio: {names} | modal ${p.settings.capital:,.0f} | "
          f"{cfg['strategy']['name']} {cfg['strategy'].get('params') or {}} | "
          f"{cfg['timeframe']} | leverage {p.settings.leverage:g}")
    if indicative:
        print("*** HASIL INDIKATIF (mengandung DEX tanpa riwayat likuiditas cukup) ***")
    for number, period in enumerate(periods, 1):
        run = run_period(data, store, p, period)
        title = f"{period.name}: {period.start:%Y-%m-%d} s/d {period.end:%Y-%m-%d}"
        if period.source:
            title += f" | funding: {fund.source_names(data)[period.source]}"
        if indicative:
            title = "INDIKATIF - " + title
        print(f"\n=== {title}")
        print(tearsheet.comparison(run.strategy, run.benchmark))
        if run.strategy.metrics["sharpe"] > 2:
            print("  !! Sharpe > 2: anggap BUG sampai terbukti tidak (cek look-ahead & biaya).")
        print("\n  Biaya strategi per pasar (USD):")
        table = tearsheet.cost_table(run.strategy)
        print(table.round(2).to_string() if not table.empty else "  (tidak ada transaksi)")
        paths = tearsheet.save(run.strategy, run.benchmark, p.settings.capital, folder,
                               f"portfolio_{number}_{period.source or 'penuh'}", title)
        print(f"  Berkas: {paths[0].parent / paths[0].stem.rsplit('_', 1)[0]}_*")
        if period.source:
            perp = cfg["perp"]
            stressed = replace(p.settings,
                               funding_cost_mult=perp["stress_cost_multiplier"],
                               funding_income_mult=perp["stress_income_multiplier"])
            print(f"\n  Uji funding lebih mahal (bayar x{stressed.funding_cost_mult:g}, "
                  f"terima x{stressed.funding_income_mult:g}):")
            print(_line("funding normal", run))
            print(_line("funding lebih mahal",
                        run_period(data, store, p, period, stressed)))
    if has_perp and overlap:
        print(f"\n=== Pembanding sumber funding pada periode yang sama "
              f"({overlap.start:%Y-%m-%d} s/d {overlap.end:%Y-%m-%d}, dijalankan terpisah)")
        for source in (fund.ARCHIVE, fund.NATIVE):
            run = run_period(data, store, p, replace(overlap, source=source))
            paid = run.strategy.trades["funding"].sum()
            print(_line(fund.source_names(data)[source], run) + f" | funding ${paid:,.2f}")
    if any(a.instrument.market == "dex" for a in p.assets):
        print("\n=== Sensitivitas likuiditas pool (INDIKATIF, seluruh periode terakhir)")
        for haircut in cfg["dex"]["sensitivity_haircuts"]:
            assets = [replace(a, liquidity=load_liquidity(store, a.instrument, haircut))
                      if a.instrument.market == "dex" else a for a in p.assets]
            run = run_period(data, store, replace(p, assets=assets), periods[-1])
            impact = run.strategy.trades["impact"].sum()
            print(_line(f"likuiditas {haircut:.0%}", run)
                  + f" | impact ${impact:,.2f}, dibatasi {run.strategy.capped_orders}")
    print()
    for note in p.notes:
        print(f"! {note}")
    print("! 1 kombinasi parameter tanpa optimasi; backtest historis, bukan walk-forward.")


def add_portfolio_parser(sub) -> None:
    s = sub.add_parser("portfolio", help="backtest multi-aset dengan modal bersama")
    s.add_argument("--config", default=str(ROOT / "config" / "backtest.yaml"))
    s.add_argument("--data-config", default=str(ROOT / "config" / "instruments.yaml"))
    s.add_argument("--symbols", nargs="+", help="ganti daftar instrumen (porsi sama rata)")
    s.add_argument("--strategy")
    s.add_argument("--timeframe")
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--capital", type=float)
    s.add_argument("--leverage", type=float)
    s.add_argument("--allow-short", action="store_true")
    s.add_argument("--stop-loss", type=float, help="persen dari harga masuk")
    s.add_argument("--take-profit", type=float, help="persen dari harga masuk")
    s.add_argument("--allow-stale", action="store_true")
    s.add_argument("--reports", default=str(ROOT / "reports"))
    s.set_defaults(func=cmd_portfolio)
