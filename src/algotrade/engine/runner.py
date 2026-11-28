"""Rangkai data, sinyal, biaya, funding, dan likuiditas menjadi satu atau beberapa run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import pandas as pd

from ..data.store import Store
from ..instruments import DataConfig
from ..research import journal
from ..strategies import get_strategy
from . import funding as fund
from .costs import cost_model
from .liquidity import INDICATIVE, load_liquidity
from .market_data import DataRejected, find_instrument, load_bars, lot_units
from .portfolio import Asset, Result, Settings, run_portfolio

USD_LIKE = ("USD", "USDT", "USDC")


@dataclass
class Prepared:
    assets: list[Asset]
    benchmarks: list[Asset]       # aset pembanding Buy & Hold (perpetual diganti spot)
    settings: Settings
    start: pd.Timestamp
    end: pd.Timestamp
    notes: list[str] = field(default_factory=list)
    identity: dict = field(default_factory=dict)     # untuk pencatat percobaan


@dataclass
class Run:
    period: fund.Period
    strategy: Result
    benchmark: Result


def _benchmark_asset(config, store, asset: Asset, cfg: dict, allow_stale: bool, now,
                     first: pd.Timestamp, notes: list[str]) -> Asset:
    """Buy & Hold dengan bobot sama, mulai saat strategi bisa mulai.

    Untuk perpetual dipakai SPOT pasangan yang sama (mis. BTC/USDT), karena Buy & Hold
    perpetual membayar funding dan bisa terlikuidasi sehingga bukan pembanding yang wajar.
    """
    ins = asset.instrument
    if ins.kind == "perp":
        spot_symbol = ins.symbol.split(":")[0]
        try:
            spot = find_instrument(config, spot_symbol, ins.market)
            bars = load_bars(config, store, spot, cfg["timeframe"], end=cfg.get("end"),
                             allow_stale=allow_stale, now=now).df
        except DataRejected as e:
            notes.append(f"Benchmark {ins.symbol} memakai perpetual itu sendiri karena spot "
                         f"tidak bisa dipakai: {e}")
        else:
            notes.append(f"Benchmark {ins.symbol} = Buy & Hold spot {spot_symbol}.")
            asset = replace(asset, instrument=spot, bars=bars, costs=cost_model(spot),
                            lot=lot_units(store, spot))
    signal = (asset.bars["close_time"] >= first).astype(float)
    return replace(asset, signal=signal, allow_short=False)


def prepare(config: DataConfig, store: Store, cfg: dict, allow_stale: bool = False,
            now: pd.Timestamp | None = None) -> Prepared:
    """cfg = isi config/backtest.yaml (sudah digabung opsi command line)."""
    strategy = get_strategy(cfg["strategy"]["name"], **(cfg["strategy"].get("params") or {}))
    dex, perp = cfg["dex"], cfg["perp"]
    total = sum(item["weight"] for item in cfg["instruments"])
    if total > 1 + 1e-9:
        raise DataRejected(f"Jumlah weight {total:.2f} > 1 (modal bersama tidak boleh lebih).")
    assets, benchmarks, notes, starts, ends = [], [], [], [], []
    for item in cfg["instruments"]:
        ins = find_instrument(config, item["symbol"], item.get("market"))
        if ins.quote not in USD_LIKE:
            raise DataRejected(f"{ins.symbol} bermata uang {ins.quote}; portofolio baru "
                               "mendukung USD/USDT/USDC. Pakai `backtest`.")
        bars = load_bars(config, store, ins, cfg["timeframe"], end=cfg.get("end"),
                         allow_stale=allow_stale, now=now)
        df = bars.df
        if len(df) <= strategy.warmup + 1:
            raise DataRejected(f"{ins.symbol}: hanya {len(df)} bar, butuh lebih dari "
                               f"{strategy.warmup + 1}.")
        signal = strategy.generate_signals(df).reindex(df.index).fillna(0.0)
        signal.iloc[:strategy.warmup] = 0.0
        costs = cost_model(ins)
        asset = Asset(ins, df, signal, float(item["weight"]), costs,
                      lot=lot_units(store, ins), allow_short=cfg.get("allow_short", False))
        if bars.warnings:
            notes.append(f"Peringatan data {ins.symbol}: {', '.join(bars.warnings)}")
        if costs.unverified:
            notes.append(f"Biaya PERLU DICEK ({ins.symbol}): {', '.join(costs.unverified)}")
        first = df["close_time"].iloc[strategy.warmup]
        if ins.market == "dex":
            asset.liquidity = load_liquidity(store, ins, dex["liquidity_haircut"])
            if not asset.liquidity.covers(first, dex["liquidity_history_days"]):
                notes.append(f"{ins.symbol} {INDICATIVE}")
        assets.append(asset)
        benchmarks.append(_benchmark_asset(config, store, asset, cfg, allow_stale, now,
                                           first, notes))
        starts.append(first)
        ends.append(df["close_time"].iloc[-1])
    start, end = max(starts), min(ends)
    if cfg.get("start"):
        start = max(start, pd.Timestamp(cfg["start"], tz="UTC"))
    if start >= end:
        raise DataRejected("Tidak ada periode bersama yang cukup untuk semua instrumen.")
    stops = cfg.get("stops") or {}

    def fraction(value):
        return None if value is None else float(value) / 100

    settings = Settings(
        capital=float(cfg["capital_usd"]), leverage=float(perp["leverage"]),
        stop_loss=fraction(stops.get("stop_loss_pct")),
        take_profit=fraction(stops.get("take_profit_pct")),
        max_order_pct=float(dex["max_order_pct_of_liquidity"]) / 100)
    if settings.leverage < 1:
        raise DataRejected("Leverage minimal 1.")
    identity = {"strategy": strategy.name, "params": strategy.params,
                "timeframe": cfg["timeframe"],
                "universe": {a.instrument.symbol: a.weight for a in assets},
                "allow_short": bool(cfg.get("allow_short", False))
                and any(a.instrument.kind == "perp" for a in assets),
                "journal": str(config.database.parent / journal.FILENAME)}
    return Prepared(assets, benchmarks, settings, start, end, notes, identity)


def plan(config: DataConfig, store: Store, p: Prepared):
    """Periode berdasarkan ketersediaan funding."""
    coverage: dict = {}
    for a in p.assets:
        if a.instrument.kind == "perp":
            for source in (fund.ARCHIVE, fund.NATIVE):
                ts = fund.load_funding(config, store, a.instrument, source)["ts"]
                coverage.setdefault(source, []).append((ts.iloc[0], ts.iloc[-1]))
    return fund.plan_periods(coverage, p.start, p.end)


def _with_funding(config, store, assets: list[Asset],
                  period: fund.Period) -> list[Asset]:
    out = []
    for a in assets:
        if a.instrument.kind == "perp":
            df = fund.load_funding(config, store, a.instrument, period.source)
            name = fund.source_names(config)[period.source]
            fund.check_window(df, period.start, period.end, f"{a.instrument.symbol} ({name})")
            a = replace(a, funding=df)
        out.append(a)
    return out


def _benchmark(config, store, p: Prepared, period: fund.Period) -> Result:
    """Biaya, bobot, dan tanggal sama dengan strategi; tanpa stop dan tanpa leverage."""
    assets = _with_funding(config, store, p.benchmarks, period)
    settings = replace(p.settings, leverage=1.0, stop_loss=None, take_profit=None,
                       funding_cost_mult=1.0, funding_income_mult=1.0)
    return run_portfolio(assets, settings, period.start, period.end)


def _log(p: Prepared, period: fund.Period, settings: Settings, **outcome) -> None:
    """Catat run strategi (benchmark bukan percobaan)."""
    i = p.identity
    window = p.assets[0].bars
    window = window[(window.index >= period.start) & (window.index <= period.end)]
    journal.record(
        i["journal"], engine="portofolio", strategy=i["strategy"], params=i["params"],
        universe=i["universe"], timeframe=i["timeframe"],
        modifiers={"allow_short": i["allow_short"], "leverage": settings.leverage,
                   "stop_loss": settings.stop_loss, "take_profit": settings.take_profit},
        data=window if len(window) else p.assets[0].bars,
        costs={**asdict(settings), "funding_source": period.source}, **outcome)


def run_period(config, store, p: Prepared, period: fund.Period,
               settings: Settings | None = None) -> Run:
    assets = _with_funding(config, store, p.assets, period)
    used = settings or p.settings
    try:
        strategy = run_portfolio(assets, used, period.start, period.end)
    except Exception as e:
        _log(p, period, used, error=f"{type(e).__name__}: {e}")
        raise
    _log(p, period, used, metrics=strategy.metrics)
    return Run(period, strategy, _benchmark(config, store, p, period))
