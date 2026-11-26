"""Metrik performa dari deret return per bar."""

from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1).min())


def compute_metrics(returns: pd.Series, positions: pd.Series | None = None,
                    periods_per_year: int = 252) -> dict:
    r = returns.fillna(0.0)
    n = len(r)
    if n == 0:
        return {}
    equity = (1 + r).cumprod()
    total = float(equity.iloc[-1] - 1)
    years = n / periods_per_year
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else np.nan
    vol = float(r.std(ddof=0) * np.sqrt(periods_per_year))
    sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(periods_per_year)) if r.std() > 0 else 0.0
    downside = r[r < 0].std(ddof=0)
    sortino = float(r.mean() / downside * np.sqrt(periods_per_year)) if downside > 0 else 0.0
    mdd = max_drawdown(equity)

    out = {
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 and not np.isnan(cagr) else np.nan,
    }
    if positions is not None:
        pos = positions.fillna(0)
        out["exposure"] = float((pos != 0).mean())
        out["n_trades"] = int((pos.diff().fillna(pos) != 0).sum())
        active = r[pos != 0]
        out["win_rate_bars"] = float((active > 0).mean()) if len(active) else np.nan
    return out


def format_metrics(m: dict) -> str:
    pct = {"total_return", "cagr", "volatility", "max_drawdown", "exposure", "win_rate_bars"}
    lines = []
    for k, v in m.items():
        if isinstance(v, float) and k in pct:
            lines.append(f"  {k:<15} {v:>10.2%}")
        elif isinstance(v, float):
            lines.append(f"  {k:<15} {v:>10.2f}")
        else:
            lines.append(f"  {k:<15} {v:>10}")
    return "\n".join(lines)
