"""Pembersih data yfinance dan data palsu untuk tes.

Output selalu DataFrame dengan index DatetimeIndex (urut naik) dan kolom:
open, high, low, close, volume  (huruf kecil).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED = ["open", "high", "low", "close", "volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):  # yfinance kadang mengembalikan MultiIndex
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    if "adj close" in df.columns:
        # Pakai harga yang sudah disesuaikan (dividen/split) untuk semua kolom OHLC
        ratio = df["adj close"] / df["close"]
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c] * ratio
    df = df[REQUIRED].dropna(subset=["close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def synthetic_prices(n: int = 2500, seed: int = 42, start: str = "2015-01-01") -> pd.DataFrame:
    """Data harga palsu (random walk) untuk tes offline. JANGAN dipakai untuk kesimpulan."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    close = 1000 * np.exp(np.cumsum(rets))
    idx = pd.bdate_range(start, periods=n)
    noise = np.abs(rng.normal(0, 0.005, n))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.003, n)),
        "high": close * (1 + noise),
        "low": close * (1 - noise),
        "close": close,
        "volume": rng.integers(1_000_000, 10_000_000, n),
    }, index=idx)
