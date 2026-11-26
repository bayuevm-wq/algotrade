"""Perintah `algotrade data update` dan `algotrade data quality`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data.store import Store
from .data.update import Adapters, build_jobs, instrument_table, quality_report, run_jobs
from .instruments import MARKETS, load_data_config

ROOT = Path(__file__).resolve().parents[2]


def _setup(args):
    config = load_data_config(args.data_config, ROOT)
    return config, Store(config.root, config.database)


def print_report(report: pd.DataFrame, path: Path) -> int:
    """Cetak laporan, simpan CSV. Return jumlah dataset GAGAL."""
    if report.empty:
        print("Tidak ada instrumen yang aktif.")
        return 1
    short = report[["market", "source", "symbol", "dataset", "rows", "first", "last",
                    "status"]].copy()
    for column in ["first", "last"]:
        short[column] = short[column].map(lambda t: "-" if pd.isna(t) else f"{t:%Y-%m-%d %H:%M}")
    print("\nLaporan kualitas data (waktu UTC)")
    print(short.to_string(index=False))
    flagged = report[report["status"] != "OK"]
    if not flagged.empty:
        print("\nCatatan:")
        for r in flagged.itertuples():
            print(f"- {r.source} {r.symbol} {r.dataset}")
            for issue in r.issues.split("; "):
                print(f"    {issue}")
    counts = report["status"].value_counts()
    print("\nRingkasan: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(path, index=False)
    print(f"CSV: {path}")
    return int(counts.get("GAGAL", 0))


def cmd_update(args):
    config, store = _setup(args)
    now = pd.Timestamp.now(tz="UTC")
    adapters = Adapters(config)
    jobs = build_jobs(config, store, adapters, now, args.market, args.full)
    results = run_jobs(jobs, log=lambda m: print(m, flush=True))
    instruments = instrument_table(config)
    # Tick & lot crypto diambil dari exchange; bila gagal, biarkan kosong
    for ins in (i for i in config.instruments if i.market == "cex"):
        try:
            limits = adapters.cex.limits(ins)
        except Exception as e:  # noqa: BLE001 - metadata tambahan, bukan data utama
            print(f"Peringatan: batas {ins.symbol} tidak terambil ({type(e).__name__}).")
            continue
        row = (instruments["market"] == "cex") & (instruments["symbol"] == ins.symbol)
        for column in ["tick_size", "lot_size", "contract_size"]:
            instruments.loc[row, column] = limits[column]
    store.refresh_database(instruments)
    failed = [r for r in results if r.error]
    errors = print_report(quality_report(config, store, pd.Timestamp.now(tz="UTC"), args.market),
                          Path(args.report))
    if failed or errors:
        raise SystemExit(f"Selesai dengan masalah: {len(failed)} unduhan gagal, "
                         f"{errors} dataset berstatus GAGAL.")
    print("Update selesai tanpa kegagalan.")


def cmd_quality(args):
    config, store = _setup(args)
    report = quality_report(config, store, pd.Timestamp.now(tz="UTC"), args.market)
    if print_report(report, Path(args.report)):
        raise SystemExit(1)


def add_data_parser(sub) -> None:
    data = sub.add_parser("data", help="unduh & cek data multi-pasar")
    actions = data.add_subparsers(dest="action", required=True)
    for name, fn, text in [("update", cmd_update, "unduh data baru lalu cek kualitas"),
                           ("quality", cmd_quality, "cek kualitas data tersimpan")]:
        p = actions.add_parser(name, help=text)
        p.add_argument("--data-config", default=str(ROOT / "config" / "instruments.yaml"))
        p.add_argument("--market", choices=MARKETS, help="hanya satu pasar")
        p.add_argument("--report", default=str(ROOT / "reports" / "data_quality.csv"))
        if name == "update":
            p.add_argument("--full", action="store_true", help="unduh ulang dari awal")
        p.set_defaults(func=fn)
