"""Pencatat percobaan otomatis (DuckDB).

Setiap backtest pada data ASLI dari store dicatat, termasuk yang gagal. Pencatatan dipicu oleh
mesin backtest sendiri, jadi berlaku untuk perintah CLI maupun skrip yang memakai `load_bars`.
Data palsu (`--synthetic`) tidak dicatat. Bila pencatatan gagal, backtest ikut gagal: lebih
baik berhenti daripada ada percobaan yang tidak terhitung.

- run     : satu kali perhitungan.
- variasi : kombinasi unik strategi + parameter + instrumen + timeframe + pengaturan posisi.
            Mengulang atau mengganti periode/biaya tidak menambah variasi. Angka inilah yang
            dipakai sebagai jumlah percobaan.

File `experiments.duckdb` berada di folder data/ (tidak di-commit). Cadangkan bila perlu.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import pandas as pd

FILENAME = "experiments.duckdb"
SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    run_at TIMESTAMPTZ, command VARCHAR, code_commit VARCHAR, engine VARCHAR,
    variant_id VARCHAR, strategy VARCHAR, params VARCHAR, universe VARCHAR,
    timeframe VARCHAR, modifiers VARCHAR, data_start TIMESTAMPTZ, data_end TIMESTAMPTZ,
    data_fingerprint VARCHAR, costs VARCHAR, metrics VARCHAR, status VARCHAR, error VARCHAR)"""


def fingerprint(df: pd.DataFrame) -> str:
    """Sidik jari pendek data harga (berubah bila ada angka atau tanggal yang berubah)."""
    columns = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    hashed = pd.util.hash_pandas_object(df[columns].astype(float), index=True)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()[:16]


def _json(value) -> str:
    def clean(v):
        if isinstance(v, Mapping):
            return {str(k): clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if hasattr(v, "item"):                       # angka numpy
            v = v.item()
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return v

    return json.dumps(clean(value), sort_keys=True, default=str)


def variant_id(strategy: str, params: Mapping, universe: Mapping, timeframe: str,
               modifiers: Mapping) -> str:
    # Pengaturan bernilai bawaan dibuang supaya dua mesin menghasilkan id yang sama
    active = {k: v for k, v in modifiers.items() if v not in (None, False, 1, 1.0)}
    text = _json([strategy, params, universe, timeframe, active])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@lru_cache
def _code_commit() -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=root,
                               check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return head + ("+ubah" if dirty else "")


def _command() -> str:
    return " ".join(sys.argv[1:3]) if "algotrade" in sys.argv[0] or "cli" in sys.argv[0] \
        else "python"


def _connect(path: Path, attempts: int = 20):
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        try:
            return duckdb.connect(str(path))
        except duckdb.IOException:                  # sedang dipakai proses lain
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def record(path: str | Path, *, engine: str, strategy: str, params: Mapping,
           universe: Mapping, timeframe: str, modifiers: Mapping, data: pd.DataFrame,
           costs: Mapping, metrics: Mapping | None = None, error: str = "") -> str:
    """Tambahkan satu run. Return variant_id."""
    vid = variant_id(strategy, params, universe, timeframe, modifiers)
    row = [pd.Timestamp.now(tz="UTC").to_pydatetime(), _command(), _code_commit(), engine, vid,
           strategy, _json(params), _json(universe), timeframe, _json(modifiers),
           data.index[0].to_pydatetime(), data.index[-1].to_pydatetime(), fingerprint(data),
           _json(costs), _json(metrics or {}), "gagal" if error else "ok", error]
    with _connect(Path(path)) as con:
        con.execute(SCHEMA)
        con.execute(f"INSERT INTO runs VALUES ({', '.join('?' * len(row))})", row)
    return vid


def summary(path: str | Path) -> pd.DataFrame:
    """Jumlah run dan variasi per strategi."""
    if not Path(path).exists():
        return pd.DataFrame(columns=["strategy", "variasi", "run", "gagal"])
    with _connect(Path(path)) as con:
        con.execute(SCHEMA)
        return con.execute(
            "SELECT strategy, count(DISTINCT variant_id) AS variasi, count(*) AS run, "
            "count(*) FILTER (WHERE status = 'gagal') AS gagal FROM runs "
            "GROUP BY strategy ORDER BY strategy").df()


def count_variants(path: str | Path, strategy: str | None = None) -> int:
    table = summary(path)
    if strategy:
        table = table[table["strategy"] == strategy]
    return int(table["variasi"].sum())
