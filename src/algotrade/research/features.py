"""Fitur untuk riset. Nilai di bar t hanya memakai data yang SUDAH diketahui saat bar t tutup.

Data luar (funding, benchmark, likuiditas) digabung dengan "nilai terakhir sebelum atau tepat
pada jam tutup bar" (as-of mundur), tidak pernah dari masa depan.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def momentum(close: pd.Series, window: int) -> pd.Series:
    return close / close.shift(window) - 1


def volatility(close: pd.Series, window: int, bars_per_year: int) -> pd.Series:
    returns = close.pct_change(fill_method=None)
    return returns.rolling(window).std() * np.sqrt(bars_per_year)


def volume_zscore(volume: pd.Series, window: int) -> pd.Series:
    """Volume (log) dibanding rata-rata bergulirnya sendiri."""
    log = np.log1p(volume)
    spread = log.rolling(window).std()
    return (log - log.rolling(window).mean()) / spread.where(spread > 0)


def as_of(when: pd.Series, times: pd.Series, values: pd.Series,
          max_age: pd.Timedelta) -> pd.Series:
    """Untuk tiap waktu di `when`: nilai terakhir pada `times` <= waktu itu, bila belum basi."""
    left = pd.DataFrame({"t": when.astype("datetime64[ns, UTC]"), "row": np.arange(len(when))})
    right = pd.DataFrame({"t": times.astype("datetime64[ns, UTC]").to_numpy(),
                          "value": values.to_numpy()}).dropna(subset=["t"])
    right["t"] = right["t"].astype("datetime64[ns, UTC]")
    merged = pd.merge_asof(left.sort_values("t"), right.sort_values("t"), on="t",
                           direction="backward", tolerance=max_age)
    return pd.Series(merged.sort_values("row")["value"].to_numpy(), index=when.index)


def funding_average(close_time: pd.Series, funding: pd.DataFrame, days: int) -> pd.Series:
    """Rata-rata funding `days` hari terakhir. Satu sumber saja; di luar cakupannya = kosong."""
    series = funding.set_index("ts")["funding_rate"].sort_index()
    window = pd.Timedelta(days=days)
    mean = series.rolling(window).mean()
    mean = mean[mean.index >= series.index[0] + window]       # jendela harus penuh
    return as_of(close_time, mean.index.to_series(), mean, pd.Timedelta(days=1))


def correlation(close: pd.Series, close_time: pd.Series, other: pd.DataFrame,
                window: int) -> pd.Series:
    """Korelasi return dengan aset lain (mis. BTC atau SPY), memakai harga yang sudah tutup."""
    known = as_of(close_time, other["close_time"], other["close"], pd.Timedelta(days=5))
    return close.pct_change(fill_method=None).rolling(window).corr(
        known.pct_change(fill_method=None))


def build_features(bars: pd.DataFrame, settings: dict, bars_per_year: int,
                   funding: pd.DataFrame | None = None,
                   others: dict[str, pd.DataFrame] | None = None,
                   liquidity: pd.DataFrame | None = None) -> pd.DataFrame:
    """bars: hasil `load_bars` (open..volume, close_time)."""
    close, when = bars["close"], bars["close_time"]
    out = pd.DataFrame(index=bars.index)
    for w in settings["momentum_windows"]:
        out[f"momentum_{w}"] = momentum(close, w)
    for w in settings["volatility_windows"]:
        out[f"volatility_{w}"] = volatility(close, w, bars_per_year)
    out["volume_z"] = volume_zscore(bars["volume"], settings["volume_window"])
    if funding is not None:
        out["funding_avg"] = funding_average(when, funding, settings["funding_days"])
    for name, other in (others or {}).items():
        out[f"corr_{name}"] = correlation(close, when, other, settings["correlation_window"])
    if liquidity is not None:
        # Tanpa riwayat = kosong. Tidak memakai potret masa depan seperti asumsi backtest.
        out["liquidity_usd"] = as_of(when, liquidity["ts"], liquidity["reserve_usd"],
                                     pd.Timedelta(days=2))
    return out
