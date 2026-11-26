"""Likuiditas pool DEX untuk backtest, dan label "indikatif"."""

from __future__ import annotations

import pandas as pd

from ..data.store import Store
from ..instruments import Instrument

INDICATIVE = ("INDIKATIF: riwayat likuiditas pool belum cukup; dipakai potret terbaru "
              "(asumsi yang melihat ke belakang).")


class Liquidity:
    """Likuiditas pada waktu t: potret terakhir <= t; bila belum ada, potret TERBARU."""

    def __init__(self, history: pd.DataFrame, haircut: float):
        if history is None or history.empty:
            raise ValueError("Data likuiditas pool belum ada. Jalankan `data update`.")
        self.series = history.set_index("ts")["reserve_usd"].sort_index()
        self.haircut = haircut

    def at(self, t: pd.Timestamp) -> float:
        past = self.series.asof(t)
        value = self.series.iloc[-1] if pd.isna(past) else past
        return float(value) * self.haircut

    def covers(self, start: pd.Timestamp, required_days: int) -> bool:
        """True bila riwayat asli cukup panjang, rapat, dan mencakup awal backtest."""
        days = self.series.index.normalize().unique()
        span = (days[-1] - days[0]).days
        return (span >= required_days and len(days) >= 0.75 * span
                and start >= self.series.index[0])


def load_liquidity(store: Store, instrument: Instrument, haircut: float) -> Liquidity:
    return Liquidity(store.read(instrument, "liquidity"), haircut)
