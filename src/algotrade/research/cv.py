"""Purged walk-forward: data latih selalu SEBELUM data uji, tanpa label yang tumpang tindih."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PurgedWalkForward:
    """Sampel dibagi n_splits+1 bagian berurutan; bagian 2..n+1 bergantian menjadi data uji.

    Purging: sampel latih dibuang bila labelnya baru diketahui pada/ setelah keputusan uji
    pertama. Embargo: jeda tambahan sebelum data uji. train_size None = semua masa lalu.
    """

    n_splits: int = 5
    embargo: pd.Timedelta | None = None
    train_size: pd.Timedelta | None = None

    def split(self, t_start: pd.Series, t_end: pd.Series) -> Iterator[tuple]:
        """t_start = waktu keputusan tiap sampel (urut), t_end = waktu label diketahui."""
        if self.n_splits < 1 or len(t_start) <= self.n_splits:
            raise ValueError("Sampel terlalu sedikit untuk jumlah lipatan ini.")
        if not t_start.is_monotonic_increasing:
            raise ValueError("Sampel harus urut waktu.")
        if t_end.isna().any() or (t_end.to_numpy() < t_start.to_numpy()).any():
            raise ValueError("Setiap sampel butuh t_end yang tidak mendahului t_start.")
        parts = np.array_split(np.arange(len(t_start)), self.n_splits + 1)
        for test in parts[1:]:
            begin = t_start.iloc[test[0]]
            limit = begin if self.embargo is None else begin - self.embargo
            usable = (t_end < limit) & (t_start < begin)
            if self.train_size is not None:
                usable &= t_start >= begin - self.train_size
            train = np.flatnonzero(usable.to_numpy())
            if len(train):
                yield train, test
