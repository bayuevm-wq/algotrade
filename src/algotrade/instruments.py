"""Model Instrument: satu cara seragam menggambarkan aset dari pasar mana pun."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

MARKETS = ("cex", "us_equity", "dex", "idx")
_UNITS = {"m": "min", "h": "h", "d": "D"}


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    """'15m' / '4h' / '1d' -> Timedelta."""
    match = re.fullmatch(r"([1-9]\d*)([mhd])", timeframe)
    if not match:
        raise ValueError(f"Timeframe '{timeframe}' tidak dikenal (contoh: 15m, 1h, 4h, 1d).")
    return pd.Timedelta(int(match[1]), unit=_UNITS[match[2]])


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str                       # cex / us_equity / dex / idx
    source: str                       # exchange atau penyedia data
    kind: str                         # spot / perp / stock / pool
    quote: str
    session: str                      # "24/7" atau kode kalender bursa (XNYS, XIDX)
    periods_per_year: int             # jumlah bar HARIAN per tahun
    timeframes: tuple[str, ...]
    derived: tuple[str, ...] = ()
    start: pd.Timestamp | None = None
    tick_size: float | None = None
    lot_size: float | None = None
    costs: dict = field(default_factory=dict, hash=False)
    extra: dict = field(default_factory=dict, hash=False)

    @property
    def key(self) -> str:
        """Nama aman untuk folder/file."""
        return re.sub(r"[^A-Za-z0-9.]+", "-", self.symbol).strip("-")

    def bars_per_year(self, timeframe: str) -> int:
        delta = timeframe_delta(timeframe)
        day = pd.Timedelta(days=1)
        if delta >= day:
            return round(self.periods_per_year / (delta / day))
        hours = 24 if self.session == "24/7" else 6.5   # perkiraan jam bursa saham
        return round(self.periods_per_year * pd.Timedelta(hours=hours) / delta)


@dataclass(frozen=True)
class DataConfig:
    root: Path
    database: Path
    markets: dict
    sources: dict
    instruments: list[Instrument]


def _utc(value: str | None) -> pd.Timestamp | None:
    return pd.Timestamp(value, tz="UTC") if value else None


def _build(market: str, src: dict, defaults: dict) -> list[Instrument]:
    common = {
        "market": market, "quote": defaults["quote"], "session": defaults["session"],
        "periods_per_year": defaults["periods_per_year"],
        "timeframes": tuple(src["timeframes"]), "derived": tuple(src.get("derived", [])),
        "tick_size": defaults.get("tick_size"), "lot_size": defaults.get("lot_size"),
    }
    if market == "dex":
        return [Instrument(symbol=p["name"], source=src["provider"], kind="pool",
                           costs={**defaults["costs"], "swap_fee_pct": p.get("fee_pct"),
                                  "gas_usd": p.get("gas_usd")},
                           extra={"network": p["network"], "address": p["address"]}, **common)
                for p in src["pools"]]
    out = []
    for symbol in src["symbols"]:
        perp = market == "cex" and ":" in symbol
        kind = ("perp" if perp else "spot") if market == "cex" else "stock"
        costs = defaults.get("perp_costs") if perp else None
        own = dict(common)
        if market == "cex" and "/" in symbol:
            own["quote"] = symbol.split("/")[1].split(":")[0]
        out.append(Instrument(symbol=symbol, source=src.get("exchange") or src["provider"],
                              kind=kind, start=_utc(src.get("start")),
                              costs=dict(costs or defaults["costs"]), **own))
    return out


def load_data_config(path: str | Path, base_dir: str | Path) -> DataConfig:
    """Baca config/instruments.yaml. Path penyimpanan relatif terhadap folder proyek."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    instruments: list[Instrument] = []
    for market, src in cfg["sources"].items():
        if market not in MARKETS:
            raise ValueError(f"Pasar '{market}' tidak dikenal. Pilihan: {MARKETS}")
        if not src.get("enabled", True):
            continue
        for tf in [*src["timeframes"], *src.get("derived", [])]:
            timeframe_delta(tf)                     # gagal lebih awal bila salah tulis
        instruments += _build(market, src, cfg["markets"][market])
    keys = [(i.market, i.source, i.key) for i in instruments]
    if len(keys) != len(set(keys)):
        raise ValueError("Ada simbol ganda di config instrumen.")
    base = Path(base_dir)
    return DataConfig(base / cfg["storage"]["root"], base / cfg["storage"]["database"],
                      cfg["markets"], cfg["sources"], instruments)
