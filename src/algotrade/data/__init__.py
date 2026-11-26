"""Data pasar.

- `cex`, `equity`, `dex`, `archive` : adapter multi-pasar.
- `store`, `resample`, `quality`, `update` : simpan, ubah timeframe, cek, dan perbarui data.
- `yahoo` : pembersih data yfinance dan data palsu untuk tes.
"""

from .yahoo import synthetic_prices

__all__ = ["synthetic_prices"]
