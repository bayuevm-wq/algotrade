"""Model biaya per pasar. Semua angka berasal dari config/instruments.yaml."""

from __future__ import annotations

from dataclasses import dataclass

from ..backtest import BacktestConfig
from ..instruments import Instrument
from .market_data import DataRejected


@dataclass(frozen=True)
class CostModel:
    """Semua pecahan (0.001 = 0,1%) per sisi, kecuali gas dalam USD per swap."""

    buy_fee: float = 0.0
    sell_fee: float = 0.0
    slippage: float = 0.0
    half_spread: float = 0.0
    mev: float = 0.0
    gas_usd: float = 0.0
    uses_pool: bool = False
    maintenance_margin: float = 0.0
    unverified: tuple[str, ...] = ()

    def impact(self, notional: float, liquidity: float | None) -> float:
        """Price impact pendekatan constant-product: order / likuiditas satu sisi pool.

        Pool Uniswap v3 / Orca memakai likuiditas terkonsentrasi, jadi ini hanya perkiraan.
        """
        if not self.uses_pool:
            return 0.0
        if liquidity is None or not liquidity > 0:
            raise ValueError("Likuiditas pool tidak tersedia.")
        return notional / (liquidity / 2)


def cost_model(instrument: Instrument) -> CostModel:
    """Gagal bila ada angka biaya yang kosong; biaya tidak pernah diam-diam jadi nol."""
    c = instrument.costs

    def pct(name: str) -> float:
        if c.get(name) is None:
            raise ValueError(f"{instrument.symbol}: biaya '{name}' belum diisi di config.")
        return float(c[name]) / 100

    common = {"slippage": pct("slippage_pct"), "unverified": tuple(c.get("unverified", ()))}
    if instrument.market == "cex":
        margin = pct("maintenance_margin_pct") if instrument.kind == "perp" else 0.0
        return CostModel(buy_fee=pct("taker_fee_pct"), sell_fee=pct("taker_fee_pct"),
                         maintenance_margin=margin, **common)
    if instrument.market == "us_equity":
        return CostModel(buy_fee=pct("commission_pct"), sell_fee=pct("commission_pct"),
                         half_spread=pct("spread_pct") / 2, **common)
    if instrument.market == "idx":
        return CostModel(buy_fee=pct("buy_fee_pct"), sell_fee=pct("sell_fee_pct"), **common)
    if c.get("gas_usd") is None:
        raise ValueError(f"{instrument.symbol}: biaya 'gas_usd' belum diisi di config.")
    fee = pct("swap_fee_pct")
    return CostModel(buy_fee=fee, sell_fee=fee, mev=pct("mev_buffer_pct"),
                     gas_usd=float(c["gas_usd"]), uses_pool=True, **common)


def vector_config(instrument: Instrument, timeframe: str, capital: float, allow_short: bool,
                  liquidity: float | None = None,
                  max_order_pct: float | None = None) -> BacktestConfig:
    """Biaya untuk backtester vektor (satu aset, selalu memakai seluruh modal).

    Gas dan price impact dinyatakan sebagai persen dari modal AWAL (pendekatan).
    """
    if instrument.kind == "perp":
        raise DataRejected(f"{instrument.symbol} adalah perpetual: funding tidak dihitung di "
                           "sini. Pakai `algotrade portfolio`.")
    m = cost_model(instrument)
    if m.uses_pool and max_order_pct is not None and liquidity is not None:
        limit = liquidity * max_order_pct / 100
        if capital > limit:
            raise DataRejected(f"{instrument.symbol}: modal ${capital:,.0f} melebihi batas order "
                             f"${limit:,.0f} ({max_order_pct}% likuiditas).")
    extra = m.slippage + m.half_spread + m.mev + m.impact(capital, liquidity)
    gas = m.gas_usd / capital if m.gas_usd else 0.0
    return BacktestConfig(
        initial_capital=capital, allow_short=allow_short and instrument.kind == "perp",
        buy_fee_pct=(m.buy_fee + gas) * 100, sell_fee_pct=(m.sell_fee + gas) * 100,
        slippage_pct=extra * 100, periods_per_year=instrument.bars_per_year(timeframe))
