"""Trend following: long saat SMA cepat > SMA lambat."""

import pandas as pd

from .base import Strategy


class SmaCross(Strategy):
    name = "sma_cross"

    def __init__(self, fast: int = 20, slow: int = 100):
        if fast >= slow:
            raise ValueError("fast harus lebih kecil dari slow")
        super().__init__(fast=fast, slow=slow)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = df["close"].rolling(self.params["fast"]).mean()
        slow = df["close"].rolling(self.params["slow"]).mean()
        signal = (fast > slow).astype(float)
        signal[slow.isna()] = 0.0  # belum cukup data -> flat
        return signal
