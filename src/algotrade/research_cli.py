"""Perintah `algotrade research ...`: validate, dataset, fingerprint, trials."""

from __future__ import annotations

from pathlib import Path

import yaml

from .data.store import Store
from .engine.market_data import find_instrument
from .instruments import load_data_config
from .research import journal
from .research.dataset import build_dataset
from .research.validate import load_case, report, validate

ROOT = Path(__file__).resolve().parents[2]


def _setup(args):
    config = load_data_config(args.data_config, ROOT)
    return config, Store(config.root, config.database), config.database.parent / journal.FILENAME


def _research_config(args) -> dict:
    with open(args.config, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _case(cfg: dict, name: str) -> dict:
    if name not in cfg["cases"]:
        raise SystemExit(f"Kasus '{name}' tidak ada. Pilihan: {list(cfg['cases'])}")
    return cfg["cases"][name]


def cmd_validate(args):
    cfg = _research_config(args)
    names = list(cfg["cases"]) if args.all else [args.case]
    config, store, db = _setup(args)
    summary = []
    for name in names:
        case = _case(cfg, name)
        if not case.get("data_fingerprint"):
            raise SystemExit(f"Isi dulu `data_fingerprint` kasus {name} (lihat `research "
                             "fingerprint`) supaya data dan ambang ditetapkan SEBELUM hasil "
                             "dilihat.")
        result = validate(config, store, name, case, cfg["validation"])
        text = report(result, cfg["validation"], journal.count_variants(db, case["strategy"]))
        out = Path(args.reports) / f"research_{name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(text)
        print(f"Laporan: {out}")
        summary.append(f"  {name:<24} {case['strategy']:<14} "
                       f"{'LOLOS' if result.passed else 'TIDAK LOLOS'}")
    if args.all:
        print("\nRingkasan semua kasus:")
        print("\n".join(summary))


def cmd_dataset(args):
    cfg = _research_config(args)
    config, store, _ = _setup(args)
    instrument = find_instrument(config, args.symbol, args.market)
    data = build_dataset(config, store, instrument, args.timeframe, cfg["dataset"],
                         args.allow_stale)
    folder = config.database.parent / "research"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{instrument.market}_{instrument.key}_{args.timeframe}.parquet"
    data.table.to_parquet(out)
    t = data.table
    print(f"{instrument.symbol} {args.timeframe}: {len(t)} sampel, "
          f"{t['t_start'].iloc[0]:%Y-%m-%d} s/d {t['t_start'].iloc[-1]:%Y-%m-%d}")
    print("\nFitur (porsi kosong):")
    for name in data.features:
        print(f"  {name:<16} {t[name].isna().mean():>7.1%}")
    print("\nLabel triple-barrier: "
          + ", ".join(f"{k} {v}" for k, v in t["tb_reason"].value_counts().items()))
    print("\nPurged walk-forward:")
    folds = data.folds.copy()
    for column in ["latih_sampai", "uji_mulai", "uji_sampai"]:
        folds[column] = folds[column].dt.strftime("%Y-%m-%d")
    print(folds.to_string(index=False))
    for note in data.notes:
        print(f"! {note}")
    print("! Tabel ini belum menilai daya prediksi. Label hanya boleh menjadi target.")
    print(f"Tersimpan: {out}")


def cmd_fingerprint(args):
    cfg = _research_config(args)
    case = {k: v for k, v in _case(cfg, args.case).items() if k != "data_fingerprint"}
    config, store, _ = _setup(args)
    _, df, found = load_case(config, store, case)
    print(f"{args.case}: {len(df)} bar, {df.index[0]:%Y-%m-%d} s/d {df.index[-1]:%Y-%m-%d}")
    print(f"data_fingerprint: {found}")


def cmd_trials(args):
    _, _, db = _setup(args)
    table = journal.summary(db)
    if table.empty:
        print("Belum ada percobaan yang tercatat.")
        return
    print(table.to_string(index=False))
    print(f"Total variasi: {int(table['variasi'].sum())} | file: {db}")


def add_research_parser(sub) -> None:
    research = sub.add_parser("research", help="uji overfitting & daftar percobaan")
    actions = research.add_subparsers(dest="action", required=True)
    for name, fn, text in [("validate", cmd_validate, "DSR, PBO, walk-forward satu kasus"),
                           ("dataset", cmd_dataset, "tabel fitur, label, purged walk-forward"),
                           ("fingerprint", cmd_fingerprint, "sidik jari data suatu kasus"),
                           ("trials", cmd_trials, "jumlah percobaan yang tercatat")]:
        p = actions.add_parser(name, help=text)
        p.add_argument("--config", default=str(ROOT / "config" / "research.yaml"))
        p.add_argument("--data-config", default=str(ROOT / "config" / "instruments.yaml"))
        p.add_argument("--reports", default=str(ROOT / "reports"))
        if name in ("validate", "fingerprint"):
            p.add_argument("--case", default="sma_cross_btc")
        if name == "validate":
            p.add_argument("--all", action="store_true", help="semua kasus di config")
        if name == "dataset":
            p.add_argument("--symbol", default="BTC/USDT")
            p.add_argument("--market")
            p.add_argument("--timeframe", default="1d")
            p.add_argument("--allow-stale", action="store_true")
        p.set_defaults(func=fn)
