"""Ubah OHLCV ke timeframe yang lebih besar (batas waktu mengikuti UTC)."""

from __future__ import annotations

import pandas as pd

from ..instruments import timeframe_delta


def resample_ohlcv(df: pd.DataFrame, source: str, target: str) -> pd.DataFrame:
    """Hanya periode utuh di awal dan akhir. Kolom n_bars = jumlah bar sumber di dalamnya."""
    small, big = timeframe_delta(source), timeframe_delta(target)
    if big <= small or big % small != pd.Timedelta(0):
        raise ValueError(f"Tidak bisa mengubah {source} menjadi {target}.")
    bucket = df["ts"].dt.floor(big)
    out = df.groupby(bucket).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), n_bars=("close", "size"),
    ).rename_axis("ts").reset_index()
    if out.empty:
        return out
    complete = (out["ts"] >= df["ts"].min()) & (out["ts"] + big <= df["ts"].max() + small)
    return out[complete].reset_index(drop=True)
