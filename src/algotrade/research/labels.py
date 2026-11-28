"""Label (target) riset ML. Label SENGAJA melihat ke depan: hanya boleh dipakai sebagai target,
tidak pernah sebagai fitur atau sinyal.

Keputusan diambil saat bar t tutup, masuk di harga BUKA bar t+1 (sama dengan backtester).
Setiap label membawa `t_end` (kapan label diketahui) untuk purging. Bar yang jendelanya belum
lengkap di akhir data diberi label kosong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _empty(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame({
        "label": np.nan, "ret": np.nan,
        "t_end": pd.Series(pd.NaT, index=index, dtype="datetime64[ns, UTC]"),
        "reason": None}, index=index)


def forward_return(bars: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Return dari buka bar t+1 sampai tutup bar t+horizon."""
    if horizon < 1:
        raise ValueError("horizon minimal 1.")
    out = _empty(bars.index)
    opens, closes = bars["open"].to_numpy(), bars["close"].to_numpy()
    ends = bars["close_time"].array
    for t in range(len(bars) - horizon):
        value = closes[t + horizon] / opens[t + 1] - 1
        out.iloc[t] = [np.sign(value), value, ends[t + horizon], "waktu"]
    return out


def triple_barrier(bars: pd.DataFrame, horizon: int, up: float, down: float,
                   vol_window: int) -> pd.DataFrame:
    """+1 bila batas atas tersentuh dulu, -1 batas bawah, tanda return bila waktu habis.

    Jarak batas = up/down x volatilitas harian yang sudah diketahui saat bar t. Bila kedua
    batas tersentuh di bar yang sama dianggap batas BAWAH (pesimis); gap diisi di harga buka.
    """
    if horizon < 1 or up <= 0 or down <= 0:
        raise ValueError("horizon, up, dan down harus positif.")
    out = _empty(bars.index)
    spread = bars["close"].pct_change(fill_method=None).rolling(vol_window).std().to_numpy()
    o, h, low, c = (bars[k].to_numpy() for k in ["open", "high", "low", "close"])
    ends = bars["close_time"].array
    for t in range(len(bars) - horizon):
        if not spread[t] > 0:
            continue
        entry = o[t + 1]
        top, bottom = entry * (1 + up * spread[t]), entry * (1 - down * spread[t])
        label, price, k, reason = None, c[t + horizon], t + horizon, "waktu"
        for j in range(t + 1, t + horizon + 1):
            if o[j] <= bottom or o[j] >= top:                  # gap
                label, price = (-1.0 if o[j] <= bottom else 1.0), o[j]
            elif low[j] <= bottom:
                label, price = -1.0, bottom
            elif h[j] >= top:
                label, price = 1.0, top
            if label is not None:
                k, reason = j, "bawah" if label < 0 else "atas"
                break
        value = price / entry - 1
        out.iloc[t] = [np.sign(value) if label is None else label, value, ends[k], reason]
    return out
