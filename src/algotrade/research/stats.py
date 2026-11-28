"""Probabilistic & Deflated Sharpe Ratio (Bailey & López de Prado, 2014; ML4T bab 16).

Semua Sharpe di sini PER BAR (belum disetahunkan). Kurtosis memakai definisi Pearson
(normal = 3).
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

EULER_MASCHERONI = 0.5772156649015329
_NORMAL = NormalDist()


def sharpe_per_bar(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    spread = r.std(ddof=1)
    return float(r.mean() / spread) if spread > 0 else 0.0


def skew_kurtosis(returns: np.ndarray) -> tuple[float, float]:
    r = np.asarray(returns, dtype=float)
    centered = r - r.mean()
    m2 = np.mean(centered**2)
    if m2 <= 0:
        return 0.0, 3.0
    return float(np.mean(centered**3) / m2**1.5), float(np.mean(centered**4) / m2**2)


def expected_max_sharpe(variance_trials: float, n_trials: int) -> float:
    """Sharpe tertinggi yang diharapkan dari N percobaan TANPA keunggulan apa pun."""
    if n_trials <= 1 or variance_trials <= 0:
        return 0.0
    first = _NORMAL.inv_cdf(1 - 1 / n_trials)
    second = _NORMAL.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(variance_trials) * ((1 - EULER_MASCHERONI) * first
                                         + EULER_MASCHERONI * second)


def probabilistic_sharpe(sharpe: float, benchmark: float, n_obs: int, skew: float = 0.0,
                         kurtosis: float = 3.0) -> float:
    """Peluang Sharpe sebenarnya di atas `benchmark`."""
    if n_obs < 2:
        raise ValueError("Butuh minimal 2 pengamatan.")
    variance = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    z = (sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(max(variance, 1e-12))
    return _NORMAL.cdf(z)


def deflated_sharpe(sharpe: float, variance_trials: float, n_trials: int, n_obs: int,
                    skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """PSR dengan pembanding = Sharpe tertinggi yang diharapkan dari keberuntungan."""
    return probabilistic_sharpe(sharpe, expected_max_sharpe(variance_trials, n_trials),
                                n_obs, skew, kurtosis)
