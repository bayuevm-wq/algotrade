"""Kalender bursa (hari libur & jam tutup)."""

from __future__ import annotations

from functools import lru_cache

import pandas as pd


@lru_cache
def _calendar(code: str):
    import exchange_calendars as xc

    return xc.get_calendar(code)


def session_closes(code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Series: index = tanggal sesi (tanpa zona), nilai = jam tutup (UTC)."""
    calendar = _calendar(code)
    first = max(start.tz_localize(None).normalize(), calendar.first_session)
    last = min(end.tz_localize(None).normalize(), calendar.last_session)
    if first > last:
        return pd.Series(dtype="datetime64[ns, UTC]")
    sessions = calendar.sessions_in_range(first, last)
    return calendar.closes.loc[sessions]
