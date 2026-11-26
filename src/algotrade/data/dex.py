"""Adapter DEX lewat API publik GeckoTerminal: OHLCV pool dan likuiditas.

API gratis hanya memberi riwayat sekitar 180 hari. Hanya membaca data, tanpa wallet.
"""

from __future__ import annotations

import json

import pandas as pd

from ..instruments import Instrument, timeframe_delta
from .base import Adapter, closed_bars, ohlcv_frame
from .http import Http, HttpError

BASE = "https://api.geckoterminal.com/api/v2/networks"
PAGE = 1000
LIQUIDITY_COLUMNS = ["ts", "reserve_usd", "volume_24h_usd"]


def _timeframe_path(timeframe: str) -> tuple[str, int]:
    supported = {"1m": ("minute", 1), "5m": ("minute", 5), "15m": ("minute", 15),
                 "1h": ("hour", 1), "4h": ("hour", 4), "12h": ("hour", 12), "1d": ("day", 1)}
    if timeframe not in supported:
        raise ValueError(f"GeckoTerminal tidak mendukung timeframe '{timeframe}'.")
    return supported[timeframe]


class DexAdapter(Adapter):
    def __init__(self, http: Http | None = None, history_days: int = 180,
                 request_interval: float = 7.0):
        self.http = http or Http(min_interval=request_interval)
        self.history_days = history_days

    def _json(self, url: str) -> dict:
        return json.loads(self.http.get(url))

    def _pool_url(self, instrument: Instrument) -> str:
        return f"{BASE}/{instrument.extra['network']}/pools/{instrument.extra['address']}"

    def fetch_ohlcv(self, instrument: Instrument, timeframe: str, since: pd.Timestamp,
                    until: pd.Timestamp) -> pd.DataFrame:
        """Mundur halaman demi halaman dari `until`. Jam tanpa transaksi tidak punya bar."""
        unit, aggregate = _timeframe_path(timeframe)
        since = max(since, until - pd.Timedelta(days=self.history_days))
        floor, before, rows = int(since.timestamp()), int(until.timestamp()), []
        while before > floor:
            url = (f"{self._pool_url(instrument)}/ohlcv/{unit}?aggregate={aggregate}"
                   f"&limit={PAGE}&currency=usd&before_timestamp={before}")
            try:
                page = self._json(url)["data"]["attributes"]["ohlcv_list"]
            except HttpError as e:
                if e.status == 401 and rows:        # melewati batas riwayat gratis
                    break
                raise
            page = [r for r in page if r[0] < before]
            if not page:
                break
            rows += page
            before = min(r[0] for r in page)
        df = ohlcv_frame(rows, unit="s")
        df = df[(df["ts"] >= since.floor(timeframe_delta(timeframe))) & (df["ts"] < until)]
        return closed_bars(df, timeframe, until)

    def fetch_liquidity(self, instrument: Instrument, now: pd.Timestamp) -> pd.DataFrame:
        """Potret likuiditas saat ini; riwayatnya terkumpul dari update harian."""
        attrs = self._json(self._pool_url(instrument))["data"]["attributes"]
        df = pd.DataFrame([[now, float(attrs["reserve_in_usd"]),
                            float(attrs["volume_usd"]["h24"])]], columns=LIQUIDITY_COLUMNS)
        df["ts"] = df["ts"].astype("datetime64[ms, UTC]")
        return df
