"""Aturan funding perpetual.

1. Satu kali jalan memakai SATU sumber untuk seluruh periodenya. Tidak pernah disambung.
2. Periode dibagi dua dan dilaporkan terpisah:
   - ARSIP : sebelum data funding exchange tersedia -> arsip Binance (PENGGANTI, harga OKX)
   - ASLI  : sejak data funding exchange tersedia   -> funding exchange itu sendiri
3. Funding yang bolong membuat backtest ditolak, tidak diisi nol.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from ..data.store import Store
from ..instruments import DataConfig, Instrument
from .market_data import DataRejected

ARCHIVE, NATIVE = "arsip", "asli"


@dataclass(frozen=True)
class Period:
    name: str
    source: str | None            # ARSIP / NATIVE; None bila tidak ada perpetual
    start: pd.Timestamp
    end: pd.Timestamp


def source_names(config: DataConfig) -> dict[str, str]:
    cex = config.sources["cex"]
    return {ARCHIVE: cex["funding"]["archive"]["name"], NATIVE: cex["exchange"]}


def load_funding(config: DataConfig, store: Store, instrument: Instrument,
                 source: str) -> pd.DataFrame:
    name = source_names(config)[source]
    df = store.read(replace(instrument, source=name), "funding")
    if df is None or df.empty:
        raise DataRejected(f"Funding {instrument.symbol} dari {name} belum ada.")
    return df


def check_window(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, label: str) -> None:
    """Pastikan funding menutup (start, end] tanpa bolong."""
    gaps = df["ts"].diff()
    if "interval_hours" in df and df["interval_hours"].notna().all():
        usual = pd.to_timedelta(df["interval_hours"], unit="h")
    else:
        usual = pd.Series(gaps.median(), index=df.index)
    longest = usual.max() * 1.5
    first, last = df["ts"].iloc[0], df["ts"].iloc[-1]
    if first > start + longest or last < end - longest:
        raise DataRejected(f"Funding {label} hanya {first:%Y-%m-%d} s/d {last:%Y-%m-%d}; "
                           f"tidak menutup {start:%Y-%m-%d} s/d {end:%Y-%m-%d}.")
    bad = (gaps > usual * 1.5) & (df["ts"] > start) & (df["ts"] - gaps < end)
    if bad.any():
        when = df["ts"][bad].iloc[0]
        raise DataRejected(f"Funding {label} bolong sebelum {when:%Y-%m-%d %H:%M} UTC.")


def plan_periods(coverage: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]],
                 start: pd.Timestamp, end: pd.Timestamp) -> tuple[list[Period], Period | None]:
    """Return (periode terpisah, periode tumpang tindih untuk pembanding kedua sumber).

    coverage[sumber] = daftar (awal, akhir) funding tiap perpetual.
    """
    if not coverage:
        return [Period("PENUH", None, start, end)], None
    archive_start = max(a for a, _ in coverage[ARCHIVE])
    archive_end = min(b for _, b in coverage[ARCHIVE])
    native_start = max(a for a, _ in coverage[NATIVE])
    periods = []
    first, last = max(start, archive_start), min(end, native_start, archive_end)
    if first < last:
        periods.append(Period("ARSIP BINANCE (pengganti)", ARCHIVE, first, last))
    first = max(start, native_start)
    if first < end:
        periods.append(Period("FUNDING ASLI EXCHANGE", NATIVE, first, end))
    both_end = min(end, archive_end)
    overlap = Period("TUMPANG TINDIH", None, first, both_end) if first < both_end else None
    if not periods:
        raise DataRejected("Tidak ada periode yang tertutup data funding.")
    return periods, overlap
