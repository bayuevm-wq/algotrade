"""Cek kualitas data.

GAGAL      : data tidak boleh dipakai (ganda, urutan salah, harga mustahil, basi, kosong).
PERINGATAN : perlu dilihat (celah, lonjakan ekstrem, volume nol, riwayat pendek).
Data tidak pernah diubah atau dihapus oleh pemeriksaan ini.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..instruments import Instrument, timeframe_delta
from .calendars import session_closes

ERROR, WARN = "GAGAL", "PERINGATAN"
PRICES = ["open", "high", "low", "close"]
TOLERANCE = 1e-6          # toleransi pembulatan pada high/low


@dataclass(frozen=True)
class Issue:
    level: str
    check: str
    count: int
    detail: str = ""


def _issue(level: str, check: str, mask: pd.Series, ts: pd.Series) -> list[Issue]:
    n = int(mask.sum())
    if not n:
        return []
    examples = ", ".join(t.strftime("%Y-%m-%d %H:%M") for t in ts[mask].iloc[:3])
    return [Issue(level, check, n, f"mis. {examples}")]


def _basic(df: pd.DataFrame, now: pd.Timestamp) -> list[Issue]:
    ts = df["ts"]
    out = _issue(ERROR, "data ganda", ts.duplicated(), ts)
    out += _issue(ERROR, "urutan waktu salah", ts.diff() < pd.Timedelta(0), ts)
    return out + _issue(ERROR, "waktu di masa depan", ts > now, ts)


def _gaps_and_stale(df: pd.DataFrame, instrument: Instrument, timeframe: str,
                    now: pd.Timestamp, rules: dict) -> list[Issue]:
    ts, step = df["ts"], timeframe_delta(timeframe)
    first, last = ts.min(), ts.max()
    if instrument.session == "24/7":
        expected = pd.date_range(first, last, freq=step)
        missing = expected.difference(pd.DatetimeIndex(ts))
        # Bar berikutnya baru selesai pada last + 2*step; basi bila lewat jauh dari itu
        late = (now - (last + 2 * step)) / pd.Timedelta(hours=1)
        stale = late > rules["max_stale_hours"]
        stale_text = f"bar terakhir {last:%Y-%m-%d %H:%M} UTC, bar baru telat {late:.0f} jam"
        extra = pd.DatetimeIndex([])
    elif step == pd.Timedelta(days=1):
        closes = session_closes(instrument.session, first, now)
        done = closes[closes <= now].index
        days = pd.DatetimeIndex(ts.dt.tz_localize(None))
        missing = done[done <= days.max()].difference(days)
        behind = int((done > days.max()).sum())
        stale = behind > rules["max_stale_sessions"]
        stale_text = f"tertinggal {behind} sesi bursa (bar terakhir {last:%Y-%m-%d})"
        extra = days.difference(closes.index)
    else:
        return []                                   # kalender intraday saham: belum diperiksa
    out = [Issue(ERROR, "data basi", 1, stale_text)] if stale else []
    for check, items in [("celah waktu", missing), ("bar di hari libur", extra)]:
        if len(items):
            examples = ", ".join(f"{t:%Y-%m-%d %H:%M}" for t in items[:3])
            out.append(Issue(WARN, check, len(items), f"mis. {examples}"))
    return out


def check_ohlcv(df: pd.DataFrame | None, instrument: Instrument, timeframe: str,
                now: pd.Timestamp, rules: dict, expect_start: bool = True) -> list[Issue]:
    if df is None or df.empty:
        return [Issue(ERROR, "data kosong", 1)]
    ts = df["ts"]
    out = _basic(df, now)
    out += _issue(ERROR, "harga kosong", df[PRICES].isna().any(axis=1), ts)
    out += _issue(ERROR, "harga <= 0", (df[PRICES] <= 0).any(axis=1), ts)
    body = df[["open", "close"]]
    bad = ((df["high"] < body.max(axis=1) * (1 - TOLERANCE))
           | (df["low"] > body.min(axis=1) * (1 + TOLERANCE))
           | (df["high"] < df["low"]))
    out += _issue(ERROR, "high/low tidak masuk akal", bad, ts)
    out += _issue(ERROR, "volume negatif", df["volume"] < 0, ts)
    out += _issue(ERROR, "bar belum selesai",
                  (ts + timeframe_delta(timeframe) > now) & (instrument.session == "24/7"), ts)
    out += _gaps_and_stale(df, instrument, timeframe, now, rules)
    returns = df["close"].pct_change(fill_method=None).abs()
    out += _issue(WARN, f"lonjakan > {rules['outlier_return']:.0%}",
                  returns > rules["outlier_return"], ts)
    out += _issue(WARN, "volume nol", df["volume"] == 0, ts)
    start = instrument.start if expect_start else None
    if start is not None and ts.min() > start + pd.Timedelta(days=7):
        out.append(Issue(WARN, "riwayat mulai terlambat", 1,
                         f"mulai {ts.min():%Y-%m-%d}, diminta {start:%Y-%m-%d}"))
    return out


def check_funding(df: pd.DataFrame | None, now: pd.Timestamp, max_stale: pd.Timedelta,
                  extreme: float) -> list[Issue]:
    if df is None or df.empty:
        return [Issue(ERROR, "data kosong", 1)]
    ts = df["ts"]
    out = _basic(df, now)
    out += _issue(ERROR, "funding kosong/tak hingga", ~np.isfinite(df["funding_rate"]), ts)
    if now - ts.max() > max_stale:
        out.append(Issue(ERROR, "data basi", 1, f"terakhir {ts.max():%Y-%m-%d %H:%M} UTC"))
    gap = ts.diff()
    if "interval_hours" in df and df["interval_hours"].notna().all():
        usual = pd.to_timedelta(df["interval_hours"], unit="h")
    else:
        usual = gap.median()
    out += _issue(WARN, "celah waktu", gap > usual * 1.5, ts)
    out += _issue(WARN, f"funding ekstrem > {extreme:.2%}",
                  df["funding_rate"].abs() > extreme, ts)
    return out


def check_liquidity(df: pd.DataFrame | None, now: pd.Timestamp, rules: dict) -> list[Issue]:
    if df is None or df.empty:
        return [Issue(ERROR, "data kosong", 1)]
    out = _basic(df, now)
    latest = df.iloc[-1]
    if now - latest["ts"] > pd.Timedelta(hours=36):
        out.append(Issue(ERROR, "data basi", 1, f"terakhir {latest['ts']:%Y-%m-%d %H:%M} UTC"))
    if not latest["reserve_usd"] >= rules["min_liquidity_usd"]:
        out.append(Issue(WARN, "likuiditas rendah", 1, f"${latest['reserve_usd']:,.0f}"))
    return out


def status_of(issues: list[Issue]) -> str:
    levels = {i.level for i in issues}
    return ERROR if ERROR in levels else WARN if WARN in levels else "OK"
