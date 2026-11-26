"""Kontrak adapter data.

Format OHLCV seragam: kolom ts (UTC, waktu BUKA bar), open, high, low, close, volume.
Untuk bar harian saham, ts = tanggal sesi pada 00:00 UTC (bukan jam buka bursa).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..instruments import Instrument, timeframe_delta

OHLCV = ["ts", "open", "high", "low", "close", "volume"]


def ohlcv_frame(rows: list, unit: str = "ms") -> pd.DataFrame:
    """List [waktu, o, h, l, c, v] -> DataFrame rapi, urut, tanpa duplikat."""
    df = pd.DataFrame([r[:6] for r in rows], columns=OHLCV)
    df["ts"] = pd.to_datetime(df["ts"], unit=unit, utc=True).astype("datetime64[ms, UTC]")
    df[OHLCV[1:]] = df[OHLCV[1:]].astype(float)
    return df.drop_duplicates("ts", keep="last").sort_values("ts", ignore_index=True)


def closed_bars(df: pd.DataFrame, timeframe: str, until: pd.Timestamp) -> pd.DataFrame:
    """Buang bar yang belum selesai pada waktu `until`."""
    return df[df["ts"] + timeframe_delta(timeframe) <= until].reset_index(drop=True)


class Adapter(ABC):
    @abstractmethod
    def fetch_ohlcv(self, instrument: Instrument, timeframe: str, since: pd.Timestamp,
                    until: pd.Timestamp) -> pd.DataFrame:
        """Bar yang sudah selesai dengan since <= ts < until."""
