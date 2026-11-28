"""Probability of Backtest Overfitting dengan CSCV (ML4T bab 16).

Deret waktu dibagi menjadi S blok. Untuk SETIAP cara memilih S/2 blok sebagai "masa lalu"
(in-sample): pilih variasi dengan Sharpe terbaik, lalu lihat peringkatnya di S/2 blok sisanya.
PBO = porsi pembagian ketika pilihan terbaik itu berada di median atau di bawahnya.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class PboResult:
    pbo: float
    prob_loss: float          # porsi pembagian ketika pilihan terbaik rugi di luar sampel
    slope: float              # kemiringan Sharpe luar sampel terhadap Sharpe dalam sampel
    n_splits: int
    median_is: float          # median Sharpe per bar pilihan terbaik, dalam sampel
    median_oos: float         # ... dan di luar sampel


def _sharpe(count: np.ndarray, total: np.ndarray, squares: np.ndarray) -> np.ndarray:
    mean = total / count
    variance = np.maximum((squares - total**2 / count) / (count - 1), 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(variance > 1e-18, mean / np.sqrt(variance), 0.0)


def cscv(returns: np.ndarray, n_blocks: int = 16) -> PboResult:
    """returns: matriks [bar x variasi], semua variasi pada tanggal yang sama."""
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[1] < 2:
        raise ValueError("PBO butuh minimal 2 variasi.")
    if n_blocks < 2 or n_blocks % 2 or len(r) < 2 * n_blocks:
        raise ValueError("Jumlah blok harus genap dan data cukup panjang.")
    blocks = np.array_split(r, n_blocks)
    count = np.array([len(b) for b in blocks])
    total = np.stack([b.sum(axis=0) for b in blocks])
    squares = np.stack([(b**2).sum(axis=0) for b in blocks])
    splits = np.array(list(combinations(range(n_blocks), n_blocks // 2)))
    chosen = np.zeros((len(splits), n_blocks))
    chosen[np.arange(len(splits))[:, None], splits] = 1

    def performance(mask: np.ndarray) -> np.ndarray:
        return _sharpe((mask @ count)[:, None], mask @ total, mask @ squares)

    inside, outside = performance(chosen), performance(1 - chosen)
    rows = np.arange(len(splits))
    best = inside.argmax(axis=1)
    picked = outside[rows, best]
    # Peringkat rata-rata bila seri; 1 = terburuk, N = terbaik
    below = (outside < picked[:, None]).sum(axis=1)
    ties = (outside == picked[:, None]).sum(axis=1)
    relative = (below + (ties + 1) / 2) / (r.shape[1] + 1)
    best_inside = inside[rows, best]
    slope = float(np.polyfit(best_inside, picked, 1)[0]) if best_inside.std() > 0 else 0.0
    return PboResult(
        pbo=float((relative <= 0.5).mean()), prob_loss=float((picked < 0).mean()),
        slope=slope, n_splits=len(splits), median_is=float(np.median(best_inside)),
        median_oos=float(np.median(picked)))
