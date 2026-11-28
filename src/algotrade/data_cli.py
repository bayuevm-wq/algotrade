"""Perintah `algotrade data update` dan `algotrade data quality`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data.store import Store
from .data.update import (
    Adapters,
    build_jobs,
    fallback_jobs,
    instrument_table,
    quality_report,
    run_jobs,
)
from .instruments import MARKETS, load_data_config

ROOT = Path(__file__).resolve().parents[2]
EXIT_OK, EXIT_FAILED, EXIT_FALLBACK = 0, 1, 2


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


def _only_stale(issues: str) -> bool:
    failures = [part for part in issues.split("; ") if part.startswith("GAGAL")]
    return bool(failures) and all("data basi" in part for part in failures)


def exit_code(primary: str | None, results: list, backup: list, report: pd.DataFrame) -> int:
    """0 = semua beres.
    2 = exchange utama tidak bisa diakses, cadangan berhasil, dan TIDAK ada masalah lain.
    1 = selain itu.
    """
    failed = [r for r in [*results, *backup] if r.error]
    errors = report[report["status"] == "GAGAL"]
    if not failed and not backup and errors.empty:
        return EXIT_OK

    def blocked(r) -> bool:
        return r.unreachable and r.source == primary

    backup_ok = bool(backup) and not any(r.error for r in backup)
    # Dataset utama yang basi memang wajar saat exchange utama tidak bisa diakses
    unexpected = [r for r in errors.itertuples()
                  if not (r.source == primary and _only_stale(r.issues))]
    if backup_ok and failed and all(blocked(r) for r in failed) and not unexpected:
        return EXIT_FALLBACK
    return EXIT_FAILED


def cmd_update(args):
    config, store = _setup(args)
    now = pd.Timestamp.now(tz="UTC")
    adapters = Adapters(config)

    def log(message):
        print(message, flush=True)

    results = run_jobs(build_jobs(config, store, adapters, now, args.market, args.full), log=log)
    extra = fallback_jobs(config, store, adapters, now, results, args.full)
    if extra:
        print(f"\nExchange utama tidak bisa diakses. Memakai CADANGAN "
              f"{extra[0].instrument.source} (disimpan terpisah, tidak disambung).", flush=True)
    backup = run_jobs(extra, log=log)
    instruments = instrument_table(config)
    # Tick & lot crypto diambil dari exchange; bila gagal, biarkan kosong
    unreachable = any(r.unreachable and r.market == "cex" for r in results)
    for ins in (i for i in config.instruments if i.market == "cex" and not unreachable):
        try:
            limits = adapters.cex.limits(ins)
        except Exception as e:  # noqa: BLE001 - metadata tambahan, bukan data utama
            print(f"Peringatan: batas {ins.symbol} tidak terambil ({type(e).__name__}).")
            continue
        row = (instruments["market"] == "cex") & (instruments["symbol"] == ins.symbol)
        for column in ["tick_size", "lot_size", "contract_size"]:
            instruments.loc[row, column] = limits[column]
    # Saat exchange utama tidak bisa diakses, tabel instrumen lama (lot dari exchange) dipertahankan
    store.refresh_database(None if unreachable else instruments)
    report = quality_report(config, store, pd.Timestamp.now(tz="UTC"), args.market, extra)
    errors = print_report(report, Path(args.report))
    primary = config.sources.get("cex", {}).get("exchange")
    code = exit_code(primary, results, backup, report) if not report.empty else EXIT_FAILED
    if code == EXIT_FALLBACK:
        missing = sorted({f"{r.symbol} {r.dataset}" for r in results
                          if r.error and (":" in r.symbol or r.dataset == "funding")})
        print("Selesai dengan CADANGAN (kode 2): exchange utama tidak bisa diakses.")
        if missing:
            print("Tidak tercakup cadangan (menyusul saat utama bisa diakses): "
                  + ", ".join(missing))
        raise SystemExit(EXIT_FALLBACK)
    if code:
        failed = sum(bool(r.error) for r in [*results, *backup])
        print(f"Selesai dengan masalah: {failed} unduhan gagal, {errors} dataset berstatus "
              "GAGAL.")
        raise SystemExit(EXIT_FAILED)
    print("Update selesai tanpa kegagalan.")


def cmd_quality(args):
    config, store = _setup(args)
    report = quality_report(config, store, pd.Timestamp.now(tz="UTC"), args.market)
    if print_report(report, Path(args.report)):
        raise SystemExit(EXIT_FAILED)


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
