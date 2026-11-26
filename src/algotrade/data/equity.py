"""Adapter saham (US dan IDX) lewat yfinance."""

from __future__ import annotations

import warnings

import pandas as pd

from ..instruments import Instrument, timeframe_delta
from .base import OHLCV, Adapter, closed_bars
from .calendars import session_closes
from .yahoo import _clean


class EquityAdapter(Adapter):
    def __init__(self, downloader=None):
        self.downloader = downloader

    def _download(self, symbol: str, **kwargs) -> pd.DataFrame:
        if self.downloader is None:
            import yfinance as yf

            self.downloader = yf.download
        with warnings.catch_warnings():
            # Peringatan usang dari dalam yfinance, bukan dari kode kita; agar log bersih
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            warnings.filterwarnings("ignore", message="The inplace keyword")
            return self.downloader(symbol, auto_adjust=False, progress=False, **kwargs)

    def fetch_ohlcv(self, instrument: Instrument, timeframe: str, since: pd.Timestamp,
                    until: pd.Timestamp) -> pd.DataFrame:
        """Harga disesuaikan dividen/split, jadi nilai lama bisa berubah antar unduhan."""
        raw = self._download(instrument.symbol, start=since.strftime("%Y-%m-%d"),
                             interval=timeframe)
        if raw is None or raw.empty:
            raise ValueError(f"Tidak ada data untuk {instrument.symbol}.")
        daily = timeframe_delta(timeframe) >= pd.Timedelta(days=1)
        if not daily and raw.index.tz is not None:
            raw.index = raw.index.tz_convert("UTC")
        df = _clean(raw).rename_axis("ts").reset_index()
        df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize("UTC").astype("datetime64[ms, UTC]")
        df = df[OHLCV].astype({c: float for c in OHLCV[1:]})
        df = df[(df["ts"] >= since) & (df["ts"] < until)].reset_index(drop=True)
        if not daily:
            return closed_bars(df, timeframe, until)
        # Bar harian dianggap selesai bila bursa hari itu sudah tutup
        closes = session_closes(instrument.session, since, until)
        days = df["ts"].dt.tz_localize(None)
        close_of = pd.Series(closes.reindex(days).array, index=df.index)
        unfinished = (close_of > until) | (close_of.isna() & (df["ts"] >= until.normalize()))
        return df[~unfinished].reset_index(drop=True)
