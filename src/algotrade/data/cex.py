"""Adapter exchange crypto (CEX) lewat ccxt. Hanya data publik, tanpa API key."""

from __future__ import annotations

import time

import pandas as pd

from ..instruments import Instrument, timeframe_delta
from .base import Adapter, closed_bars, ohlcv_frame

EMPTY_STEP = 100          # saat halaman kosong (belum listing), maju sedikit-sedikit agar aman
FUNDING_COLUMNS = ["ts", "funding_rate"]


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


class CexAdapter(Adapter):
    def __init__(self, exchange: str, page_limit: int = 300, client=None, retries: int = 3):
        if client is None:
            import ccxt

            if exchange not in ccxt.exchanges:
                raise ValueError(f"Exchange '{exchange}' tidak ada di ccxt.")
            client = getattr(ccxt, exchange)({"enableRateLimit": True, "timeout": 30000})
        self.client, self.page_limit, self.retries = client, page_limit, retries

    def _call(self, method: str, *args, **kwargs):
        """Panggil ccxt dengan percobaan ulang untuk gangguan jaringan."""
        import ccxt

        for attempt in range(self.retries):
            try:
                return getattr(self.client, method)(*args, **kwargs)
            except ccxt.NetworkError:
                if attempt == self.retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def fetch_ohlcv(self, instrument: Instrument, timeframe: str, since: pd.Timestamp,
                    until: pd.Timestamp) -> pd.DataFrame:
        step = int(timeframe_delta(timeframe).total_seconds() * 1000)
        cursor, end, rows = _ms(since), _ms(until), []
        while cursor + step <= end:
            page = self._call("fetch_ohlcv", instrument.symbol, timeframe, since=cursor,
                              limit=self.page_limit)
            page = [r for r in page if r[0] >= cursor]
            if not page:
                cursor += min(EMPTY_STEP, self.page_limit) * step
                continue
            rows += [r for r in page if r[0] < end]
            cursor = max(r[0] for r in page) + step
        return closed_bars(ohlcv_frame(rows), timeframe, until)

    def fetch_funding(self, instrument: Instrument, since: pd.Timestamp,
                      until: pd.Timestamp) -> pd.DataFrame:
        """Riwayat funding rate. Sebagian exchange hanya menyimpan beberapa bulan."""
        cursor, end, rows = _ms(since), _ms(until), {}
        while cursor < end:
            page = self._call("fetch_funding_rate_history", instrument.symbol,
                              since=cursor, limit=100)
            new = {r["timestamp"]: r["fundingRate"] for r in page
                   if cursor <= r["timestamp"] < end}
            if not new:
                break
            rows.update(new)
            cursor = max(new) + 1
        df = pd.DataFrame(sorted(rows.items()), columns=FUNDING_COLUMNS)
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).astype("datetime64[ms, UTC]")
        df["funding_rate"] = df["funding_rate"].astype(float)
        return df

    def limits(self, instrument: Instrument) -> dict:
        """Tick & lot minimum menurut exchange."""
        self._call("load_markets")
        market = self.client.market(instrument.symbol)
        return {"tick_size": market["precision"].get("price"),
                "lot_size": market["limits"]["amount"].get("min"),
                "contract_size": market.get("contractSize")}
