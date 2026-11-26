"""Update bertahap semua instrumen di config, lalu laporan kualitasnya."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property

import pandas as pd

from ..instruments import DataConfig, Instrument, timeframe_delta
from . import quality
from .archive import BinanceFundingArchive
from .cex import CexAdapter
from .dex import DexAdapter
from .equity import EquityAdapter
from .resample import resample_ohlcv
from .store import Store

OVERLAP_BARS = 3                       # ambil ulang beberapa bar terakhir (bisa direvisi)
CHUNK = pd.Timedelta(days=180)         # simpan bertahap supaya gangguan tidak membuang semua


class Adapters:
    """Dibuat hanya saat dibutuhkan."""

    def __init__(self, config: DataConfig):
        self.sources = config.sources

    @cached_property
    def cex(self) -> CexAdapter:
        src = self.sources["cex"]
        return CexAdapter(src["exchange"], src.get("page_limit", 300))

    @cached_property
    def equity(self) -> EquityAdapter:
        return EquityAdapter()

    @cached_property
    def dex(self) -> DexAdapter:
        src = self.sources["dex"]
        return DexAdapter(history_days=src.get("history_days", 180),
                          request_interval=src.get("request_interval_sec", 7))

    @cached_property
    def archive(self) -> BinanceFundingArchive:
        return BinanceFundingArchive()


@dataclass(frozen=True)
class Job:
    instrument: Instrument
    dataset: str
    run: Callable[[], int]             # return jumlah baris bertambah


@dataclass(frozen=True)
class Result:
    market: str
    source: str
    symbol: str
    dataset: str
    added: int
    error: str = ""


def _archive_of(config: DataConfig, instrument: Instrument) -> tuple[Instrument, str, dict] | None:
    """Instrumen bayangan untuk funding arsip (disimpan di folder sumber sendiri)."""
    if instrument.kind != "perp":
        return None
    archive = config.sources["cex"].get("funding", {}).get("archive", {})
    name = archive.get("symbols", {}).get(instrument.symbol)
    if not archive.get("enabled") or not name:
        return None
    return replace(instrument, source=archive["name"]), name, archive


def _bars(store: Store, adapter, instrument: Instrument, timeframe: str, now: pd.Timestamp,
          full: bool) -> int:
    dataset = f"ohlcv_{timeframe}"
    old = store.read(instrument, dataset)
    if instrument.market in ("us_equity", "idx"):
        # Harga disesuaikan berubah ke belakang -> selalu unduh ulang seluruh riwayat
        new = adapter.fetch_ohlcv(instrument, timeframe, instrument.start, now)
        if old is not None and not full and (
                new.empty or len(new) < 0.99 * len(old)
                or new["ts"].min() > old["ts"].min() + pd.Timedelta(days=7)):
            raise ValueError(f"Unduhan baru lebih pendek ({len(new)} vs {len(old)} baris); "
                             "data lama dipertahankan. Pakai --full bila memang disengaja.")
        return store.write(instrument, dataset, new, replace=True)

    earliest = instrument.start
    if earliest is None:               # DEX: sejauh yang disediakan API
        earliest = now - pd.Timedelta(days=getattr(adapter, "history_days", 180))
    since = earliest
    if old is not None and not full:
        since = old["ts"].max() - OVERLAP_BARS * timeframe_delta(timeframe)
    if instrument.market == "dex":
        return store.write(instrument, dataset,
                           adapter.fetch_ohlcv(instrument, timeframe, since, now))
    added = 0
    while since < now:
        until = min(since + CHUNK, now)
        added += store.write(instrument, dataset,
                             adapter.fetch_ohlcv(instrument, timeframe, since, until))
        since = until
    return added


def _derive(store: Store, instrument: Instrument, timeframe: str) -> int:
    source = instrument.timeframes[0]
    base = store.read(instrument, f"ohlcv_{source}")
    if base is None:
        raise ValueError(f"Data {source} belum ada.")
    return store.write(instrument, f"ohlcv_{timeframe}",
                       resample_ohlcv(base, source, timeframe), replace=True)


def _funding(store: Store, fetch: Callable, instrument: Instrument, start: pd.Timestamp,
             now: pd.Timestamp, full: bool) -> int:
    old = store.read(instrument, "funding")
    since = start if old is None or full else old["ts"].max() + pd.Timedelta(milliseconds=1)
    return store.write(instrument, "funding", fetch(since, now))


def build_jobs(config: DataConfig, store: Store, adapters: Adapters, now: pd.Timestamp,
               market: str | None = None, full: bool = False) -> list[Job]:
    jobs = []
    for ins in config.instruments:
        if market and ins.market != market:
            continue
        kind = "equity" if ins.market in ("us_equity", "idx") else ins.market
        for tf in ins.timeframes:
            jobs.append(Job(ins, f"ohlcv_{tf}", lambda i=ins, t=tf, k=kind: _bars(
                store, getattr(adapters, k), i, t, now, full)))
        for tf in ins.derived:
            jobs.append(Job(ins, f"ohlcv_{tf}", lambda i=ins, t=tf: _derive(store, i, t)))
        if ins.kind == "perp" and config.sources["cex"].get("funding", {}).get("enabled"):
            jobs.append(Job(ins, "funding", lambda i=ins: _funding(
                store, lambda a, b: adapters.cex.fetch_funding(i, a, b), i, i.start, now, full)))
        if (found := _archive_of(config, ins)) is not None:
            shadow, name, archive = found
            start = pd.Timestamp(archive["start"], tz="UTC")
            jobs.append(Job(shadow, "funding", lambda i=shadow, n=name, s=start: _funding(
                store, lambda a, b: adapters.archive.fetch_funding(n, a, b), i, s, now, full)))
        if ins.market == "dex":
            jobs.append(Job(ins, "liquidity", lambda i=ins: store.write(
                i, "liquidity", adapters.dex.fetch_liquidity(i, now))))
    return jobs


def run_jobs(jobs: list[Job], log: Callable[[str], None] = print) -> list[Result]:
    """Satu kegagalan tidak menghentikan yang lain."""
    results = []
    for n, job in enumerate(jobs, 1):
        i = job.instrument
        label = f"[{n}/{len(jobs)}] {i.market}/{i.source} {i.symbol} {job.dataset}"
        try:
            added, error = job.run(), ""
            log(f"{label}: +{added} baris")
        except Exception as e:  # noqa: BLE001 - dicatat, lalu lanjut ke job berikutnya
            added, error = 0, f"{type(e).__name__}: {e}"
            log(f"{label}: GAGAL {error}")
        results.append(Result(i.market, i.source, i.symbol, job.dataset, added, error))
    return results


def instrument_table(config: DataConfig) -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": i.symbol, "market": i.market, "source": i.source, "kind": i.kind,
        "quote": i.quote, "session": i.session, "periods_per_year": i.periods_per_year,
        "tick_size": i.tick_size, "lot_size": i.lot_size, "contract_size": float("nan"),
        "costs": str(i.costs),
    } for i in config.instruments])


def quality_report(config: DataConfig, store: Store, now: pd.Timestamp,
                   market: str | None = None) -> pd.DataFrame:
    """Satu baris per dataset yang SEHARUSNYA ada menurut config."""
    rows = []

    def add(ins: Instrument, dataset: str, df, issues) -> None:
        empty = df is None or df.empty
        rows.append({
            "market": ins.market, "source": ins.source, "symbol": ins.symbol,
            "dataset": dataset, "rows": 0 if empty else len(df),
            "first": None if empty else df["ts"].min(),
            "last": None if empty else df["ts"].max(),
            "status": quality.status_of(issues),
            "issues": "; ".join(f"{i.level}: {i.check} ({i.count}) {i.detail}".strip()
                                for i in issues),
        })

    for job in build_jobs(config, store, Adapters(config), now, market):
        ins, dataset = job.instrument, job.dataset
        rules = config.markets[ins.market]["quality"]
        df = store.read(ins, dataset)
        if dataset.startswith("ohlcv_"):
            tf = dataset.removeprefix("ohlcv_")
            issues = quality.check_ohlcv(df, ins, tf, now, rules,
                                         expect_start=tf in ins.timeframes)
        elif dataset == "funding":
            is_archive = ins.source != config.sources["cex"]["exchange"]
            # Arsip bulanan: boleh tertinggal sampai sekitar satu setengah bulan
            limit = pd.Timedelta(days=45) if is_archive else pd.Timedelta(hours=24)
            issues = quality.check_funding(df, now, limit, rules["funding_extreme"])
        else:
            issues = quality.check_liquidity(df, now, rules)
        add(ins, dataset, df, issues)
    return pd.DataFrame(rows)
