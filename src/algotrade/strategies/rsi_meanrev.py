"""Mean reversion: beli saat RSI oversold, keluar saat RSI pulih."""

import numpy as np
import pandas as pd

from .base import Strategy


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


class RsiMeanRev(Strategy):
    name = "rsi_meanrev"

    def __init__(self, period: int = 14, entry: float = 30, exit: float = 55):
        super().__init__(period=period, entry=entry, exit=exit)

    @property
    def warmup(self) -> int:
        return self.params["period"]

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], self.params["period"])
        pos = np.zeros(len(df))
        holding = False
        for i, v in enumerate(r.to_numpy()):
            if np.isnan(v):
                continue
            if not holding and v < self.params["entry"]:
                holding = True
            elif holding and v > self.params["exit"]:
                holding = False
            pos[i] = 1.0 if holding else 0.0
        return pd.Series(pos, index=df.index)
