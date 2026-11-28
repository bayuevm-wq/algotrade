"""Muat data dari store untuk backtest, dengan waktu buka & tutup tiap bar."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..data import quality
from ..data.calendars import session_times
from ..data.store import Store
from ..instruments import DataConfig, Instrument, timeframe_delta
from ..research import journal

PRICES = ["open", "high", "low", "close", "volume"]


class DataRejected(ValueError):
    """Data tidak boleh dipakai backtest."""


@dataclass(frozen=True)
class Bars:
    instrument: Instrument
    timeframe: str
    df: pd.DataFrame          # index = ts; open..volume, open_time, close_time
    warnings: tuple[str, ...] = ()


def find_instrument(config: DataConfig, symbol: str, market: str | None = None) -> Instrument:
    found = [i for i in config.instruments
             if i.symbol == symbol and (market is None or i.market == market)]
    if not found:
        raise DataRejected(f"Instrumen '{symbol}' ({market or 'semua pasar'}) tidak ada di "
                           "config/instruments.yaml.")
    if len(found) > 1:
        raise DataRejected(f"'{symbol}' ada di beberapa pasar; tambahkan --market.")
    return found[0]


def add_bar_times(df: pd.DataFrame, instrument: Instrument, timeframe: str) -> pd.DataFrame:
    """open_time = saat order bisa terisi; close_time = saat bar itu baru diketahui."""
    step = timeframe_delta(timeframe)
    ts = df.index
    if instrument.session == "24/7":
        return df.assign(open_time=ts, close_time=ts + step)
    if step != pd.Timedelta(days=1):
        raise DataRejected("Backtest saham baru mendukung timeframe 1d.")
    times = session_times(instrument.session, ts.min(), ts.max() + step)
    aligned = times.reindex(ts.tz_localize(None))
    # Bar di luar kalender (jarang): anggap buka 12:00 dan tutup 23:00 UTC
    opens = pd.Series(aligned["open"].array, index=ts).fillna(
        pd.Series(ts + pd.Timedelta(hours=12), index=ts))
    closes = pd.Series(aligned["close"].array, index=ts).fillna(
        pd.Series(ts + pd.Timedelta(hours=23), index=ts))
    return df.assign(open_time=opens, close_time=closes)


def load_bars(config: DataConfig, store: Store, instrument: Instrument, timeframe: str,
              start: str | None = None, end: str | None = None, allow_stale: bool = False,
              now: pd.Timestamp | None = None) -> Bars:
    """Baca satu dataset. Dataset berstatus GAGAL ditolak."""
    available = [*instrument.timeframes, *instrument.derived]
    if timeframe not in available:
        raise DataRejected(f"{instrument.symbol}: timeframe {timeframe} tidak ada di config "
                           f"(tersedia: {', '.join(available)}).")
    df = store.read(instrument, f"ohlcv_{timeframe}")
    if df is None or df.empty:
        raise DataRejected(f"{instrument.symbol} {timeframe}: data belum ada. Jalankan "
                           f"`algotrade data update --market {instrument.market}`.")
    issues = quality.check_ohlcv(df, instrument, timeframe, now or pd.Timestamp.now(tz="UTC"),
                                 config.markets[instrument.market]["quality"],
                                 expect_start=timeframe in instrument.timeframes)
    errors = [i for i in issues if i.level == quality.ERROR
              and not (allow_stale and i.check == "data basi")]
    if errors:
        text = "; ".join(f"{i.check} ({i.count}) {i.detail}" for i in errors)
        hint = " Perbarui data, atau pakai --allow-stale." if any(
            i.check == "data basi" for i in errors) else ""
        raise DataRejected(f"{instrument.symbol} {timeframe} berstatus GAGAL: {text}.{hint}")
    warnings = tuple(f"{i.check} ({i.count})" for i in issues if i.level == quality.WARN)
    out = df.set_index("ts")[PRICES]
    if start:
        out = out[out.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        out = out[out.index <= pd.Timestamp(end, tz="UTC")]
    if out.empty:
        raise DataRejected(f"{instrument.symbol}: tidak ada data pada rentang yang diminta.")
    out = add_bar_times(out, instrument, timeframe)
    # Identitas ini membuat setiap backtest atas data asli tercatat otomatis
    out.attrs["dataset"] = {
        "market": instrument.market, "symbol": instrument.symbol, "timeframe": timeframe,
        "journal": str(config.database.parent / journal.FILENAME)}
    return Bars(instrument, timeframe, out, warnings)


def lot_units(store: Store, instrument: Instrument) -> float | None:
    """Kelipatan order dalam satuan aset (kontrak perpetual dikalikan ukuran kontrak)."""
    import duckdb

    if instrument.market != "cex" or not store.database.exists():
        return instrument.lot_size
    with duckdb.connect(str(store.database), read_only=True) as con:
        try:
            row = con.execute(
                "SELECT lot_size, contract_size FROM instruments WHERE market = ? AND symbol = ?",
                [instrument.market, instrument.symbol]).fetchone()
        except duckdb.Error:
            return instrument.lot_size
    if not row or row[0] is None or pd.isna(row[0]):
        return instrument.lot_size
    size = row[1] if row[1] is not None and not pd.isna(row[1]) else 1.0
    return float(row[0]) * float(size)
