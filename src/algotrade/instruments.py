"""Model Instrument: satu cara seragam menggambarkan aset dari pasar mana pun."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd
import yaml

MARKETS = ("cex", "us_equity", "dex", "idx")
# Hanya cek per bar tertentu yang boleh dikecualikan (bukan data basi, ganda, dan sejenisnya)
EXCUSABLE_CHECKS = ("high/low tidak masuk akal",)
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
    fallbacks: list[Instrument] = field(default_factory=list)   # sumber cadangan


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
        base = defaults["costs"]
        return [Instrument(symbol=p["name"], source=src["provider"], kind="pool",
                           costs={**base, "swap_fee_pct": p.get("fee_pct"),
                                  "gas_usd": p.get("gas_usd"),
                                  "unverified": [*base.get("unverified", []),
                                                 *p.get("unverified", [])]},
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


def _apply_exceptions(instruments: list[Instrument], entries: list[dict],
                      sources: dict) -> list[Instrument]:
    """Tempelkan pengecualian kualitas ke instrumennya. Salah tulis = error."""
    found: dict[tuple[str, str], list[tuple]] = {}
    known = {(i.market, i.symbol) for i in instruments}
    for entry in entries:
        missing = {"market", "symbol", "date", "check", "reason"} - set(entry)
        if missing or not str(entry.get("reason", "")).strip():
            raise ValueError(f"Pengecualian kualitas kurang isian: {missing or 'reason'}.")
        if entry["check"] not in EXCUSABLE_CHECKS:
            raise ValueError(f"Cek '{entry['check']}' tidak boleh dikecualikan. "
                             f"Pilihan: {EXCUSABLE_CHECKS}")
        key = (entry["market"], entry["symbol"])
        if not sources.get(entry["market"], {}).get("enabled", True):
            continue                                 # pasarnya sedang dimatikan
        if key not in known:
            raise ValueError(f"Pengecualian untuk instrumen yang tidak ada: {key}.")
        found.setdefault(key, []).append(
            (entry["check"], _utc(str(entry["date"])), str(entry["reason"])))
    return [replace(i, extra={**i.extra, "quality_exceptions": tuple(found[i.market, i.symbol])})
            if (i.market, i.symbol) in found else i for i in instruments]


def _fallbacks(sources: dict, instruments: list[Instrument]) -> list[Instrument]:
    """Instrumen cadangan: salinan instrumen spot utama dengan sumber & biaya sendiri."""
    cex = sources.get("cex") or {}
    backup = cex.get("fallback") or {}
    if not (cex.get("enabled", True) and backup.get("enabled")):
        return []
    if backup["exchange"] == cex["exchange"]:
        raise ValueError("Exchange cadangan harus berbeda dari exchange utama.")
    spot = {i.symbol: i for i in instruments if i.market == "cex" and i.kind == "spot"}
    unknown = [s for s in backup["symbols"] if s not in spot]
    if unknown:
        raise ValueError(f"Simbol cadangan harus ada di daftar spot utama: {unknown}")
    return [replace(spot[s], source=backup["exchange"], start=_utc(backup.get("start")),
                    costs=dict(backup["costs"]), extra={})
            for s in backup["symbols"]]


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
    instruments = _apply_exceptions(instruments, cfg.get("quality_exceptions") or [],
                                    cfg["sources"])
    keys = [(i.market, i.source, i.key) for i in instruments]
    if len(keys) != len(set(keys)):
        raise ValueError("Ada simbol ganda di config instrumen.")
    base = Path(base_dir)
    return DataConfig(base / cfg["storage"]["root"], base / cfg["storage"]["database"],
                      cfg["markets"], cfg["sources"], instruments,
                      _fallbacks(cfg["sources"], instruments))
