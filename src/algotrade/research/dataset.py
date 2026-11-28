"""Rangkai fitur + label satu instrumen menjadi tabel riset, dan periksa pembagian purged."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..data.store import Store
from ..engine import funding as fund
from ..engine.market_data import DataRejected, find_instrument, load_bars
from ..instruments import DataConfig, Instrument
from .cv import PurgedWalkForward
from .features import build_features
from .labels import forward_return, triple_barrier


@dataclass
class Dataset:
    table: pd.DataFrame          # fitur, fwd_*, tb_*, t_start
    features: list[str]
    folds: pd.DataFrame
    notes: list[str]


def _optional(notes: list[str], label: str, load):
    try:
        return load()
    except DataRejected as e:
        notes.append(f"Fitur {label} dilewati: {e}")
        return None


def build_dataset(config: DataConfig, store: Store, instrument: Instrument, timeframe: str,
                  settings: dict, allow_stale: bool = False) -> Dataset:
    notes: list[str] = []
    bars = load_bars(config, store, instrument, timeframe, allow_stale=allow_stale).df
    features, labels, cv = settings["features"], settings["labels"], settings["cv"]

    funding = None
    if instrument.market == "cex":
        perp_symbol = instrument.symbol.split(":")[0] + ":" + instrument.quote
        funding = _optional(notes, "funding", lambda: fund.load_funding(
            config, store, find_instrument(config, perp_symbol, "cex"),
            features["funding_source"]))
        if funding is not None:
            name = fund.source_names(config)[features["funding_source"]]
            notes.append(f"Funding dari satu sumber: {name} (kosong di luar cakupannya).")
    others = {}
    for name, symbol in features["correlate_with"].items():
        if symbol == instrument.symbol:
            continue
        other = _optional(notes, f"korelasi {name}", lambda s=symbol: load_bars(
            config, store, find_instrument(config, s), timeframe if s != "SPY" else "1d",
            allow_stale=allow_stale).df)
        if other is not None:
            others[name] = other
    liquidity = store.read(instrument, "liquidity") if instrument.market == "dex" else None

    table = build_features(bars, features, instrument.bars_per_year(timeframe), funding,
                           others, liquidity)
    names = list(table.columns)
    fwd = forward_return(bars, labels["horizon"])
    barrier = triple_barrier(bars, labels["horizon"], labels["barrier_up"],
                             labels["barrier_down"], labels["vol_window"])
    table = table.join(fwd.add_prefix("fwd_")).join(barrier.add_prefix("tb_"))
    table.insert(0, "t_start", bars["close_time"])
    table = table.dropna(subset=["fwd_ret", "tb_label"])
    if table.empty:
        raise DataRejected(f"{instrument.symbol}: data terlalu pendek untuk label.")

    splitter = PurgedWalkForward(cv["n_splits"], pd.Timedelta(days=cv["embargo_days"]))
    t_end = table[["fwd_t_end", "tb_t_end"]].max(axis=1)      # label yang selesai paling akhir
    rows = []
    for number, (train, test) in enumerate(splitter.split(table["t_start"], t_end), 1):
        begin = table["t_start"].iloc[test[0]]
        rows.append({
            "lipatan": number, "latih": len(train), "uji": len(test),
            "dibuang": int((table["t_start"] < begin).sum()) - len(train),
            "latih_sampai": t_end.iloc[train].max(), "uji_mulai": begin,
            "uji_sampai": table["t_start"].iloc[test[-1]]})
    return Dataset(table, names, pd.DataFrame(rows), notes)
