"""Penyimpanan Parquet + DuckDB.

Susunan file: <root>/<pasar>/<sumber>/<simbol>/<dataset>.parquet
Dataset: ohlcv_<timeframe>, funding, liquidity. DuckDB hanya berisi view ke file-file itu.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from ..instruments import Instrument

VIEWS = {"ohlcv": "ohlcv_*.parquet", "funding": "funding.parquet",
         "liquidity": "liquidity.parquet"}


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class Store:
    def __init__(self, root: str | Path, database: str | Path):
        self.root, self.database = Path(root), Path(database)

    def path(self, instrument: Instrument, dataset: str) -> Path:
        return (self.root / instrument.market / instrument.source / instrument.key
                / f"{dataset}.parquet")

    def read(self, instrument: Instrument, dataset: str) -> pd.DataFrame | None:
        path = self.path(instrument, dataset)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        df["ts"] = df["ts"].astype("datetime64[ms, UTC]")
        return df

    def write(self, instrument: Instrument, dataset: str, df: pd.DataFrame,
              replace: bool = False) -> int:
        """Gabungkan dengan data lama (baris baru menang). Return jumlah baris bertambah."""
        old = self.read(instrument, dataset)
        if df.empty:
            return 0
        meta = {"market": instrument.market, "source": instrument.source,
                "symbol": instrument.symbol}
        if dataset.startswith("ohlcv_"):
            meta["timeframe"] = dataset.removeprefix("ohlcv_")
        new = df.assign(**meta)
        if old is not None and not replace:
            new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates("ts", keep="last").sort_values("ts", ignore_index=True)
        new["ts"] = new["ts"].astype("datetime64[ms, UTC]")
        path = self.path(instrument, dataset)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        new.to_parquet(temp, index=False)
        os.replace(temp, path)                      # tidak meninggalkan file setengah jadi
        return len(new) - (0 if old is None else len(old))

    def refresh_database(self, instruments: pd.DataFrame | None = None) -> None:
        """Buat ulang view DuckDB (dan tabel instrumen bila diberikan)."""
        import duckdb

        self.database.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.database)) as con:
            for view, pattern in VIEWS.items():
                files = sorted(self.root.rglob(pattern))
                if not files:
                    con.execute(f"DROP VIEW IF EXISTS {view}")
                    continue
                listing = ", ".join(_quote(f.resolve().as_posix()) for f in files)
                con.execute(f"CREATE OR REPLACE VIEW {view} AS "
                            f"SELECT * FROM read_parquet([{listing}], union_by_name=true)")
            if instruments is not None:
                con.register("incoming", instruments)
                con.execute("CREATE OR REPLACE TABLE instruments AS SELECT * FROM incoming")
