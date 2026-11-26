"""Mesin portofolio bar demi bar dengan modal bersama (USD; USDT/USDC dianggap = USD).

Urutan kejadian pada waktu yang sama:
1. bar ditutup : cek stop / likuidasi / take-profit di dalam bar, lalu baca sinyal baru
2. funding     : dibayar/diterima oleh posisi yang SEDANG dipegang
3. bar dibuka  : cek gap, lalu isi order di harga buka (jual dulu, baru beli)

Sinyal dari bar t baru dieksekusi di harga buka bar berikutnya (tidak ada look-ahead).
Order hanya dibuat saat sinyal berubah; porsi tidak disesuaikan ulang tiap bar.
Perpetual memakai margin terisolasi: funding dipotong dari margin posisi, dan kas lain tidak
dipakai untuk menambah margin. Kolom `liquidation` = sisa nilai posisi yang hangus.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import groupby

import numpy as np
import pandas as pd

from ..instruments import Instrument
from ..metrics import compute_metrics
from .costs import CostModel

CLOSE, FUNDING, OPEN = 0, 1, 2
COSTS = ["fee", "slippage", "spread", "impact", "mev", "gas", "funding", "liquidation"]
TRADE_COLUMNS = ["time", "symbol", "market", "reason", "qty", "price", "fill", "notional", *COSTS]


@dataclass
class Asset:
    instrument: Instrument
    bars: pd.DataFrame                      # open, high, low, close, open_time, close_time
    signal: pd.Series                       # index sama dengan bars; 1 long, 0 kosong, -1 short
    weight: float
    costs: CostModel
    lot: float | None = None
    allow_short: bool = False
    funding: pd.DataFrame | None = None     # ts, funding_rate (hanya perpetual)
    liquidity: object | None = None         # punya .at(t) (hanya DEX)


@dataclass(frozen=True)
class Settings:
    capital: float
    leverage: float = 1.0
    stop_loss: float | None = None          # pecahan dari harga masuk, mis. 0.05
    take_profit: float | None = None
    max_order_pct: float | None = None      # pecahan likuiditas pool, mis. 0.005
    funding_cost_mult: float = 1.0
    funding_income_mult: float = 1.0


@dataclass
class Result:
    equity: pd.Series                       # satu nilai per hari
    metrics: dict
    trades: pd.DataFrame
    capped_orders: int = 0
    liquidations: int = 0
    exposure: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


@dataclass
class _State:
    asset: Asset
    qty: float = 0.0
    entry: float = 0.0
    margin: float = 0.0
    mark: float = math.nan
    signal: float = 0.0
    target: float = 0.0                     # porsi modal yang diinginkan
    pending: bool = False
    blocked: float | None = None            # sinyal saat kena stop; tunggu sampai berubah

    @property
    def perp(self) -> bool:
        return self.asset.instrument.kind == "perp"

    @property
    def value(self) -> float:
        if not self.qty:
            return 0.0
        if self.perp:
            return self.margin + self.qty * (self.mark - self.entry)
        return self.qty * self.mark


def _floor_lot(qty: float, lot: float | None) -> float:
    """Bulatkan mendekati nol ke kelipatan lot."""
    if not lot:
        return qty
    return math.copysign(math.floor(abs(qty) / lot + 1e-9) * lot, qty)


class _Engine:
    def __init__(self, assets: list[Asset], settings: Settings):
        self.s = settings
        self.cash = settings.capital
        self.states = [_State(a) for a in assets]
        self.rows: list[dict] = []
        self.capped = self.liquidations = 0

    @property
    def equity(self) -> float:
        return self.cash + sum(s.value for s in self.states)

    def _record(self, st: _State, t, reason: str, **values) -> None:
        row = dict.fromkeys(TRADE_COLUMNS, 0.0)
        row.update(time=t, symbol=st.asset.instrument.symbol,
                   market=st.asset.instrument.market, reason=reason, **values)
        self.rows.append(row)

    # ---------- harga batas ----------
    def liquidation_price(self, st: _State) -> float | None:
        if not (st.perp and st.qty):
            return None
        size, mmr = abs(st.qty), st.asset.costs.maintenance_margin
        if st.qty > 0:
            price = (size * st.entry - st.margin) / (size * (1 - mmr))
            return price if price > 0 else None
        return (size * st.entry + st.margin) / (size * (1 + mmr))

    def _levels(self, st: _State) -> tuple[float | None, float | None, float | None]:
        side = math.copysign(1, st.qty)
        stop = st.entry * (1 - side * self.s.stop_loss) if self.s.stop_loss else None
        take = st.entry * (1 + side * self.s.take_profit) if self.s.take_profit else None
        return stop, take, self.liquidation_price(st)

    # ---------- order ----------
    def _impact(self, st: _State, notional: float, t) -> float:
        if not st.asset.costs.uses_pool:
            return 0.0
        return st.asset.costs.impact(notional, st.asset.liquidity.at(t))

    def _trade(self, st: _State, delta: float, price: float, t, reason: str) -> None:
        """Isi satu order. Untuk perpetual, order harus murni menutup ATAU murni membuka."""
        m, side = st.asset.costs, math.copysign(1, delta)
        notional = abs(delta) * price
        impact = self._impact(st, notional, t)
        fill = price * (1 + side * (m.slippage + m.half_spread + m.mev + impact))
        fee = abs(delta) * fill * (m.buy_fee if side > 0 else m.sell_fee)
        opening = st.qty == 0 or st.qty * delta > 0
        if st.perp:
            if opening:
                added = abs(delta) * fill / self.s.leverage
                self.cash -= added
                st.margin += added
            else:
                share = abs(delta) / abs(st.qty)
                self.cash += st.margin * share - (fill - st.entry) * delta
                st.margin *= 1 - share
        else:
            self.cash -= delta * fill
        self.cash -= fee + m.gas_usd
        if opening:
            st.entry = (abs(st.qty) * st.entry + abs(delta) * fill) / (abs(st.qty) + abs(delta))
        st.qty += delta
        if abs(st.qty) < 1e-12:
            st.qty = st.margin = st.entry = 0.0
        self._record(st, t, reason, qty=delta, price=price, fill=fill, notional=notional,
                     fee=fee, slippage=notional * m.slippage, spread=notional * m.half_spread,
                     impact=notional * impact, mev=notional * m.mev, gas=m.gas_usd)

    def _affordable(self, st: _State, qty: float, price: float, t) -> float:
        """Batasi pembukaan posisi sesuai kas (termasuk biaya)."""
        m, side = st.asset.costs, math.copysign(1, qty)
        adjust = m.slippage + m.half_spread + m.mev + self._impact(st, abs(qty) * price, t)
        fill = price * (1 + side * adjust)
        fee = m.buy_fee if side > 0 else m.sell_fee
        per_unit = fill * (fee + (1 / self.s.leverage if st.perp else 1))
        limit = max(self.cash - m.gas_usd, 0.0) / per_unit
        if abs(qty) <= limit:
            return qty
        return _floor_lot(side * limit, st.asset.lot)

    def execute(self, st: _State, price: float, t, reason: str = "sinyal") -> None:
        """Gerakkan posisi menuju target di harga `price`."""
        st.pending = False
        if st.target == 0:
            delta = -st.qty
        else:
            leverage = self.s.leverage if st.perp else 1.0
            desired = st.target * max(self.equity, 0.0) * leverage / price
            delta = _floor_lot(desired - st.qty, st.asset.lot)
        if abs(delta) * price < 1e-9:
            return
        if st.asset.costs.uses_pool and self.s.max_order_pct:
            limit = self.s.max_order_pct * st.asset.liquidity.at(t) / price
            if abs(delta) > limit:
                delta = _floor_lot(math.copysign(limit, delta), st.asset.lot)
                st.pending = True                   # sisanya dicoba di bar berikutnya
                self.capped += 1
                if not delta:
                    return
        closing = 0.0
        if st.qty * delta < 0:
            closing = math.copysign(min(abs(delta), abs(st.qty)), delta)
            self._trade(st, closing, price, t, reason)
        remaining = delta - closing
        if abs(remaining) * price >= 1e-9:
            remaining = self._affordable(st, remaining, price, t)
            if abs(remaining) * price >= 1e-9:
                self._trade(st, remaining, price, t, reason)

    def _forced_exit(self, st: _State, price: float, t, reason: str) -> None:
        st.blocked, st.target = st.signal, 0.0
        self.execute(st, price, t, reason)

    def _liquidate(self, st: _State, price: float, t) -> None:
        # Margin terisolasi: seluruh posisi hangus, kas lain tidak tersentuh. Margin bisa
        # sudah negatif (terkuras funding) tetapi tertutup keuntungan yang belum direalisasi.
        forfeited = max(st.margin + st.qty * (price - st.entry), 0.0)
        self._record(st, t, "likuidasi", qty=-st.qty, price=price, fill=price,
                     notional=abs(st.qty) * price, liquidation=forfeited)
        st.qty = st.margin = st.entry = 0.0
        st.blocked, st.target, st.pending = st.signal, 0.0, False
        self.liquidations += 1

    # ---------- kejadian ----------
    def on_close(self, st: _State, k: int, t) -> None:
        bar = st.asset.bars.iloc[k]
        if st.qty:
            long = st.qty > 0
            side = 1 if long else -1
            worst, best = (bar["low"], bar["high"]) if long else (bar["high"], bar["low"])
            stop, take, liq = self._levels(st)
            stop_hit = stop is not None and side * (worst - stop) <= 0
            # Bila stop dan take-profit tersentuh di bar yang sama: dianggap stop (pesimis)
            if stop_hit and (liq is None or side * (stop - liq) > 0):
                self._forced_exit(st, stop, t, "stop")
            elif liq is not None and side * (worst - liq) <= 0:
                self._liquidate(st, liq, t)
            elif take is not None and side * (best - take) >= 0:
                self._forced_exit(st, take, t, "take-profit")
        st.mark = bar["close"]
        st.signal = float(st.asset.signal.iloc[k])
        self.set_target(st)

    def set_target(self, st: _State) -> None:
        if st.blocked is not None and st.signal != st.blocked:
            st.blocked = None
        wanted = 0.0 if st.blocked is not None else st.signal
        if not (st.perp and st.asset.allow_short):
            wanted = max(wanted, 0.0)
        target = float(np.clip(wanted, -1, 1)) * st.asset.weight
        if target != st.target:
            st.target, st.pending = target, True

    def on_funding(self, st: _State, rate: float, t) -> None:
        if not st.qty:
            return
        payment = st.qty * st.mark * rate           # positif = posisi ini membayar
        payment *= self.s.funding_cost_mult if payment > 0 else self.s.funding_income_mult
        st.margin -= payment
        self._record(st, t, "funding", price=st.mark, funding=payment)
        if st.value <= st.asset.costs.maintenance_margin * abs(st.qty) * st.mark:
            self._liquidate(st, st.mark, t)

    def on_opens(self, events: list[tuple[_State, int]], t) -> None:
        for st, k in events:
            price = st.asset.bars["open"].iat[k]
            st.mark = price
            if not st.qty:
                continue
            side = math.copysign(1, st.qty)
            stop, take, liq = self._levels(st)
            if liq is not None and side * (price - liq) <= 0:
                self._liquidate(st, price, t)
            elif stop is not None and side * (price - stop) <= 0:
                self._forced_exit(st, price, t, "stop (gap)")
            elif take is not None and side * (price - take) >= 0:
                self._forced_exit(st, price, t, "take-profit (gap)")
        waiting = [st for st, _ in events if st.pending]
        # Pengurangan posisi lebih dulu supaya kasnya bisa dipakai aset lain
        waiting.sort(key=lambda s: abs(s.target) * self.equity > abs(s.qty) * s.mark)
        for st in waiting:
            self.execute(st, st.mark, t)


def _events(assets: list[Asset], start: pd.Timestamp, end: pd.Timestamp) -> list[tuple]:
    events = []
    for i, a in enumerate(assets):
        opens, closes = a.bars["open_time"], a.bars["close_time"]
        for k in np.flatnonzero(((opens >= start) & (closes <= end)).to_numpy()):
            events.append((opens.iat[k], OPEN, i, int(k)))
            events.append((closes.iat[k], CLOSE, i, int(k)))
        if a.funding is not None:
            inside = a.funding[(a.funding["ts"] > start) & (a.funding["ts"] <= end)]
            events += [(ts, FUNDING, i, float(rate))
                       for ts, rate in zip(inside["ts"], inside["funding_rate"])]
    return sorted(events, key=lambda e: (e[0], e[1], e[2]))


def run_portfolio(assets: list[Asset], settings: Settings, start: pd.Timestamp,
                  end: pd.Timestamp) -> Result:
    """Jalankan bar dengan buka >= start dan tutup <= end."""
    engine = _Engine(assets, settings)
    for st in engine.states:
        known = np.flatnonzero((st.asset.bars["close_time"] <= start).to_numpy())
        if len(known):                      # sinyal yang sudah diketahui saat periode mulai
            k = int(known[-1])
            st.mark = st.asset.bars["close"].iat[k]
            st.signal = float(st.asset.signal.iat[k])
            engine.set_target(st)
    events = _events(assets, start, end)
    if not events:
        raise ValueError("Tidak ada bar pada periode ini.")
    samples: dict[pd.Timestamp, tuple[float, float]] = {}

    def sample(t) -> None:
        day = (t - pd.Timedelta(1, "ns")).floor("D")
        equity = engine.equity
        held = sum(abs(s.qty) * s.mark for s in engine.states if s.qty)
        samples[day] = (equity, held / equity if equity > 0 else 0.0)

    for t, group in groupby(events, key=lambda e: e[0]):
        batch = list(group)
        closes = [e for e in batch if e[1] == CLOSE]
        for _, _, i, k in closes:
            engine.on_close(engine.states[i], k, t)
        if closes:
            sample(t)
        for _, kind, i, rate in batch:
            if kind == FUNDING:
                engine.on_funding(engine.states[i], rate, t)
        opens = [(engine.states[i], k) for _, kind, i, k in batch if kind == OPEN]
        if opens:
            engine.on_opens(opens, t)
    equity = pd.Series({d: v[0] for d, v in samples.items()}).sort_index()
    exposure = pd.Series({d: v[1] for d, v in samples.items()}).sort_index()
    returns = equity / equity.shift(1).fillna(settings.capital) - 1
    periods = 365 if any(a.instrument.session == "24/7" for a in assets) else 252
    metrics = compute_metrics(returns, None, periods)
    trades = pd.DataFrame(engine.rows, columns=TRADE_COLUMNS)
    metrics["exposure"] = float((exposure > 0).mean())
    metrics["n_trades"] = int((trades["qty"] != 0).sum())
    return Result(equity, metrics, trades, engine.capped, engine.liquidations, exposure)
