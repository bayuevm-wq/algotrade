"""Riwayat funding rate dari arsip publik Binance (data.binance.vision).

File berbentuk ZIP bulanan. Isinya dibaca di memori (tidak diekstrak ke disk) dan dicocokkan
dengan file CHECKSUM. Bulan berjalan belum tersedia di arsip.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

import pandas as pd

from .http import Http, HttpError

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
MAX_CSV_BYTES = 5_000_000


def parse_funding_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        info = z.infolist()[0]
        if info.file_size > MAX_CSV_BYTES:
            raise ValueError("Isi ZIP terlalu besar.")
        df = pd.read_csv(io.BytesIO(z.read(info)))
    ts = pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.round("1min")
    return pd.DataFrame({
        "ts": ts.astype("datetime64[ms, UTC]"),
        "funding_rate": df["last_funding_rate"].astype(float),
        "interval_hours": df["funding_interval_hours"].astype(float),
    })


class BinanceFundingArchive:
    def __init__(self, http: Http | None = None):
        self.http = http or Http(min_interval=0.2)

    def fetch_month(self, symbol: str, month: str) -> pd.DataFrame | None:
        """None bila file bulan itu belum diterbitkan."""
        url = f"{BASE}/{symbol}/{symbol}-fundingRate-{month}.zip"
        try:
            raw = self.http.get(url)
        except HttpError as e:
            if e.status == 404:
                return None
            raise
        expected = self.http.get(url + ".CHECKSUM").decode().split()[0]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Checksum tidak cocok: {url}")
        return parse_funding_zip(raw)

    def fetch_funding(self, symbol: str, since: pd.Timestamp,
                      until: pd.Timestamp) -> pd.DataFrame:
        """Semua bulan yang SUDAH selesai dari bulan `since`."""
        month = pd.Period(since.strftime("%Y-%m"), freq="M")
        last = pd.Period(until.strftime("%Y-%m"), freq="M") - 1
        parts = []
        while month <= last:
            part = self.fetch_month(symbol, str(month))
            if part is not None:
                parts.append(part)
            month += 1
        if not parts:
            return pd.DataFrame(columns=["ts", "funding_rate", "interval_hours"])
        df = pd.concat(parts, ignore_index=True)
        return df[(df["ts"] >= since) & (df["ts"] < until)].reset_index(drop=True)
