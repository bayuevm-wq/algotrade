"""Kontrak dasar untuk semua strategi."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """Strategi menghasilkan *target posisi* per bar.

    Aturan penting:
    - Nilai di bar t HANYA boleh memakai data sampai dan termasuk bar t.
    - Nilai: 1 = long penuh, 0 = flat, -1 = short penuh (pecahan boleh, mis. 0.5).
    - Backtester yang akan menggeser sinyal 1 bar (eksekusi di bar berikutnya),
      jadi strategi TIDAK perlu melakukan shift sendiri.
    """

    name: str = "base"

    def __init__(self, **params):
        self.params = params

    @property
    def warmup(self) -> int:
        """Jumlah bar awal tanpa sinyal karena indikator belum cukup data."""
        return 0

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Kembalikan Series target posisi dengan index sama seperti df."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.params})"
