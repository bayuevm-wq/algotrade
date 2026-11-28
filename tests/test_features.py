"""Tes fitur, label, purged walk-forward, dan tabel riset. Offline."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from algotrade import cli, research_cli
from algotrade.data import synthetic_prices
from algotrade.data.base import ohlcv_frame
from algotrade.data.store import Store
from algotrade.engine.market_data import find_instrument
from algotrade.instruments import load_data_config
from algotrade.research import journal
from algotrade.research.cv import PurgedWalkForward
from algotrade.research.features import as_of, build_features
from algotrade.research.labels import forward_return, triple_barrier

CONFIG = Path(__file__).resolve().parents[1] / "config"
SETTINGS = yaml.safe_load((CONFIG / "research.yaml").read_text(encoding="utf-8"))["dataset"]


def utc(text):
    return pd.Timestamp(text, tz="UTC")


def bars(n=300, seed=1):
    df = synthetic_prices(n=n, seed=seed)
    df.index = pd.date_range("2024-01-01", periods=n, tz="UTC")
    return df.assign(open_time=df.index, close_time=df.index + pd.Timedelta(days=1))


def inputs(n=300):
    funding = pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n * 3, freq="8h", tz="UTC"),
                            "funding_rate": np.random.default_rng(2).normal(0, 1e-4, n * 3)})
    liquidity = pd.DataFrame({"ts": pd.date_range("2024-03-01", periods=n, tz="UTC"),
                              "reserve_usd": np.arange(n) + 1e6})
    return funding, {"btc": bars(n, 5)}, liquidity


def test_features_do_not_use_the_future():
    """Memotong atau mengacak data sesudah t tidak boleh mengubah fitur sampai t."""
    full_bars, (funding, others, liquidity), cut = bars(), inputs(), 200
    full = build_features(full_bars, SETTINGS["features"], 365, funding, others, liquidity)
    limit = full_bars["close_time"].iloc[cut - 1]
    changed_funding = funding.copy()
    changed_funding.loc[funding["ts"] > limit, "funding_rate"] = 9.0
    changed_other = others["btc"].copy()
    changed_other.loc[changed_other["close_time"] > limit, "close"] *= 50
    changed_liquidity = liquidity.copy()
    changed_liquidity.loc[liquidity["ts"] > limit, "reserve_usd"] = 1.0
    changed_bars = full_bars.copy()
    changed_bars.iloc[cut:, :5] *= 3
    again = build_features(changed_bars, SETTINGS["features"], 365, changed_funding,
                           {"btc": changed_other}, changed_liquidity)
    pd.testing.assert_frame_equal(full.iloc[:cut], again.iloc[:cut])
    short = build_features(full_bars.iloc[:cut], SETTINGS["features"], 365, funding, others,
                           liquidity)
    pd.testing.assert_frame_equal(full.iloc[:cut], short)
    assert set(full.columns) >= {"momentum_20", "volatility_20", "volume_z", "funding_avg",
                                 "corr_btc", "liquidity_usd"}


def test_liquidity_is_empty_before_history_and_stale_values_dropped():
    out = build_features(bars(), SETTINGS["features"], 365, liquidity=inputs()[2])
    assert out["liquidity_usd"].loc[: utc("2024-02-28")].isna().all()
    values = as_of(pd.Series([utc("2024-01-05")]), pd.Series([utc("2024-01-01")]),
                   pd.Series([1.0]), pd.Timedelta(days=2))
    assert values.isna().all()


def frame(rows):
    index = pd.date_range("2024-01-01", periods=len(rows), tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    return df.assign(volume=1.0, close_time=index + pd.Timedelta(days=1))


def test_forward_return_enters_at_next_open():
    df = frame([(10, 10, 10, 10), (20, 21, 19, 21), (21, 25, 20, 22), (22, 23, 21, 23)])
    out = forward_return(df, 2)
    assert out["ret"].iloc[0] == pytest.approx(22 / 20 - 1)
    assert out["t_end"].iloc[0] == utc("2024-01-04")
    assert out["ret"].iloc[-2:].isna().all()                 # jendela belum lengkap


def barrier_case(next_bars):
    # return harian +1%, -1% bergantian -> volatilitas diketahui
    history = [(100, 101, 99, c) for c in (100, 101, 100, 101, 100)]
    df = frame(history + next_bars)
    vol = df["close"].pct_change().rolling(4).std().iloc[4]
    return triple_barrier(df, len(next_bars), 2, 2, 4).iloc[4], vol


def test_triple_barrier_outcomes():
    row, vol = barrier_case([(100, 110, 99.9, 105), (105, 105, 105, 105)])
    assert row["label"] == 1 and row["reason"] == "atas"
    assert row["ret"] == pytest.approx(2 * vol) and row["t_end"] == utc("2024-01-07")
    row, vol = barrier_case([(100, 110, 90, 100), (100, 100, 100, 100)])
    assert row["label"] == -1 and row["ret"] == pytest.approx(-2 * vol)   # pesimis
    row, _ = barrier_case([(100, 100.1, 99.9, 100), (80, 81, 79, 80)])
    assert row["reason"] == "bawah" and row["ret"] == pytest.approx(-0.2)  # gap di open
    row, _ = barrier_case([(100, 100.2, 99.9, 100), (100, 100.3, 99.9, 100.2)])
    assert row["reason"] == "waktu" and row["label"] == 1


def test_purged_walk_forward_has_no_overlap():
    start = pd.Series(pd.date_range("2024-01-01", periods=120, tz="UTC"))
    end = start + pd.Timedelta(days=10)
    folds = list(PurgedWalkForward(5, pd.Timedelta(days=3)).split(start, end))
    assert len(folds) == 5
    for train, test in folds:
        begin = start.iloc[test[0]]
        assert (end.iloc[train] < begin - pd.Timedelta(days=3)).all()
        assert train.max() < test.min()
        assert len(train) == test[0] - 13                  # 10 hari label + 3 hari embargo
    rolling = PurgedWalkForward(5, train_size=pd.Timedelta(days=30))
    for train, test in rolling.split(start, end):
        assert (start.iloc[train] >= start.iloc[test[0]] - pd.Timedelta(days=30)).all()


def test_purged_rejects_bad_input():
    start = pd.Series(pd.date_range("2024-01-01", periods=20, tz="UTC"))
    with pytest.raises(ValueError):
        list(PurgedWalkForward(3).split(start[::-1], start))
    with pytest.raises(ValueError):
        list(PurgedWalkForward(3).split(start, start - pd.Timedelta(days=1)))


def test_features_module_never_touches_labels():
    source = (CONFIG.parent / "src/algotrade/research/features.py").read_text(encoding="utf-8")
    assert "shift(-" not in source and "labels" not in source and "center=True" not in source


def test_cli_dataset_end_to_end(tmp_path, monkeypatch, capsys):
    config = load_data_config(CONFIG / "instruments.yaml", tmp_path)
    store = Store(config.root, config.database)
    days = pd.date_range("2024-01-01", periods=400, tz="UTC")
    prices = synthetic_prices(n=400)[["open", "high", "low", "close", "volume"]].to_numpy()
    data = ohlcv_frame([[int(d.timestamp() * 1000), p[3], p[3] * 1.01, p[3] * 0.99, p[3], p[4]]
                        for d, p in zip(days, prices)])
    store.write(find_instrument(config, "BTC/USDT"), "ohlcv_1d", data)
    monkeypatch.setattr(research_cli, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", [
        "algotrade", "research", "dataset", "--allow-stale",
        "--config", str(CONFIG / "research.yaml"),
        "--data-config", str(CONFIG / "instruments.yaml")])
    cli.main()
    out = capsys.readouterr().out
    assert "Purged walk-forward" in out and "Fitur funding dilewati" in out
    table = pd.read_parquet(tmp_path / "data" / "research" / "cex_BTC-USDT_1d.parquet")
    assert {"momentum_20", "tb_label", "fwd_ret"} <= set(table.columns)
    assert journal.count_variants(config.database.parent / journal.FILENAME) == 0
