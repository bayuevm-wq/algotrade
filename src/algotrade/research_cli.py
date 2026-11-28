"""Perintah `algotrade research validate` dan `algotrade research trials`."""

from __future__ import annotations

from pathlib import Path

import yaml

from .data.store import Store
from .instruments import load_data_config
from .research import journal
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
    case = _case(cfg, args.case)
    config, store, db = _setup(args)
    if not case.get("data_fingerprint"):
        raise SystemExit("Isi dulu `data_fingerprint` kasus ini (lihat `research fingerprint`) "
                         "supaya data dan ambang ditetapkan SEBELUM hasil dilihat.")
    result = validate(config, store, args.case, case, cfg["validation"])
    text = report(result, cfg["validation"], journal.count_variants(db, case["strategy"]))
    out = Path(args.reports) / f"research_{args.case}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Laporan: {out}")


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
                           ("fingerprint", cmd_fingerprint, "sidik jari data suatu kasus"),
                           ("trials", cmd_trials, "jumlah percobaan yang tercatat")]:
        p = actions.add_parser(name, help=text)
        p.add_argument("--config", default=str(ROOT / "config" / "research.yaml"))
        p.add_argument("--data-config", default=str(ROOT / "config" / "instruments.yaml"))
        p.add_argument("--reports", default=str(ROOT / "reports"))
        if name != "trials":
            p.add_argument("--case", default="sma_cross_btc")
        p.set_defaults(func=fn)
