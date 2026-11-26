"""Ringkasan hasil portofolio: metrik, biaya, turnover, return bulanan, CSV, dan grafik."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .portfolio import COSTS, Result


def monthly_returns(equity: pd.Series, capital: float) -> pd.DataFrame:
    """Tabel tahun x bulan."""
    last = equity.groupby([equity.index.year, equity.index.month]).last()
    returns = last / last.shift(1).fillna(capital) - 1
    returns.index.names = ["tahun", "bulan"]
    return returns.unstack("bulan")


def turnover_per_year(result: Result) -> float:
    """Total nilai transaksi / rata-rata equity / lama periode (tahun)."""
    days = (result.equity.index[-1] - result.equity.index[0]).days + 1
    traded = result.trades.loc[result.trades["reason"] != "funding", "notional"].sum()
    return float(traded / result.equity.mean() / (days / 365.25))


def cost_table(result: Result) -> pd.DataFrame:
    """Biaya (USD) per pasar. Funding negatif berarti diterima."""
    return result.trades.groupby("market")[COSTS].sum()


def comparison(strategy: Result, benchmark: Result) -> str:
    rows = [("total_return", "{:.2%}"), ("cagr", "{:.2%}"), ("volatility", "{:.2%}"),
            ("sharpe", "{:.2f}"), ("sortino", "{:.2f}"), ("max_drawdown", "{:.2%}"),
            ("exposure", "{:.2%}"), ("n_trades", "{:.0f}")]
    days = (strategy.equity.index[-1] - strategy.equity.index[0]).days + 1
    lines = [f"  {'':<22}{'Strategi':>14}{'Buy & Hold':>14}"]
    for key, fmt in rows:
        if key == "cagr" and days < 365:        # CAGR dari periode pendek menyesatkan
            continue
        lines.append(f"  {key:<22}{fmt.format(strategy.metrics[key]):>14}"
                     f"{fmt.format(benchmark.metrics[key]):>14}")
    extra = [("turnover per tahun", turnover_per_year, "{:.1f}x"),
             ("equity akhir (USD)", lambda r: r.equity.iloc[-1], "{:,.2f}"),
             ("likuidasi", lambda r: r.liquidations, "{:.0f}"),
             ("order dibatasi", lambda r: r.capped_orders, "{:.0f}")]
    for label, fn, fmt in extra:
        lines.append(f"  {label:<22}{fmt.format(fn(strategy)):>14}"
                     f"{fmt.format(fn(benchmark)):>14}")
    return "\n".join(lines)


def save(strategy: Result, benchmark: Result, capital: float, folder: Path, name: str,
         title: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / name
    paths = [Path(f"{base}_{part}") for part in
             ("trades.csv", "equity.csv", "bulanan.csv", "grafik.png")]
    strategy.trades.to_csv(paths[0], index=False)
    both = pd.DataFrame({"strategi": strategy.equity, "buy_hold": benchmark.equity,
                         "exposure": strategy.exposure})
    both.rename_axis("tanggal").to_csv(paths[1])
    monthly_returns(strategy.equity, capital).to_csv(paths[2])
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
    top.plot(strategy.equity, label="Strategi")
    top.plot(benchmark.equity, label="Buy & Hold", alpha=0.6)
    top.set_title(title)
    top.set_ylabel("Equity (USD)")
    top.legend()
    top.grid(alpha=0.3)
    peak = strategy.equity.cummax().clip(lower=capital)
    bottom.fill_between(strategy.equity.index, strategy.equity / peak - 1, 0,
                        color="tab:red", alpha=0.4)
    bottom.set_ylabel("Drawdown")
    bottom.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(paths[3], dpi=120)
    plt.close(fig)
    return paths
