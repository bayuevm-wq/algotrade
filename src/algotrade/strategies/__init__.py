"""Registry strategi. Tambahkan strategi baru ke STRATEGIES."""

from .base import Strategy
from .rsi_meanrev import RsiMeanRev
from .sma_cross import SmaCross

STRATEGIES: dict[str, type[Strategy]] = {
    SmaCross.name: SmaCross,
    RsiMeanRev.name: RsiMeanRev,
}


def get_strategy(name: str, **params) -> Strategy:
    if name not in STRATEGIES:
        raise KeyError(f"Strategi '{name}' tidak dikenal. Pilihan: {list(STRATEGIES)}")
    return STRATEGIES[name](**params)


__all__ = ["STRATEGIES", "RsiMeanRev", "SmaCross", "Strategy", "get_strategy"]
