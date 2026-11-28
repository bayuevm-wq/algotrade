"""Tes pencatat percobaan, Deflated Sharpe Ratio, PBO, dan validasi. Offline."""

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from algotrade.backtest import BacktestConfig, run_backtest
from algotrade.data import synthetic_prices
from algotrade.data.base import ohlcv_frame
from algotrade.data.store import Store
from algotrade.engine.market_data import DataRejected, find_instrument, load_bars
from algotrade.engine.runner import plan, prepare, run_period
from algotrade.instruments import load_data_config
from algotrade.research import journal, stats
from algotrade.research.pbo import cscv
from algotrade.research.validate import load_case, report, validate, variant_returns
from algotrade.strategies import get_strategy
from algotrade.walkforward import walk_forward

CONFIG = Path(__file__).resolve().parents[1] / "config"


# ---------- DSR ----------

def test_dsr_matches_paper_example():
    """Bailey & Lopez de Prado (2014): SR 2,5 tahunan, 5 tahun (1250 bar), 100 percobaan,
    varians antar percobaan 0,5 tahunan, skew -3, kurtosis 10 -> DSR sekitar 0,9004."""
    value = stats.deflated_sharpe(2.5 / np.sqrt(250), 0.5 / 250, 100, 1250, -3, 10)
    assert value == pytest.approx(0.9004, abs=5e-4)


def test_dsr_properties():
    assert stats.expected_max_sharpe(0.01, 1) == 0
    assert stats.expected_max_sharpe(0.01, 100) > stats.expected_max_sharpe(0.01, 10) > 0
    assert stats.probabilistic_sharpe(0.1, 0.1, 500) == pytest.approx(0.5)
    values = [stats.deflated_sharpe(0.08, 0.001, n, 1000) for n in (1, 9, 50, 100)]
    assert values == sorted(values, reverse=True)


def test_moments():
    skew, kurtosis = stats.skew_kurtosis(np.random.default_rng(1).normal(size=200_000))
    assert skew == pytest.approx(0, abs=0.03) and kurtosis == pytest.approx(3, abs=0.06)


# ---------- PBO ----------

def test_pbo_near_half_for_pure_noise():
    values = [cscv(np.random.default_rng(s).normal(0, 0.01, (1000, 9)), 10).pbo
              for s in range(20)]
    assert 0.35 < np.mean(values) < 0.65


def test_pbo_zero_when_one_variant_truly_better():
    r = np.random.default_rng(0).normal(0, 0.01, (2000, 6))
    r[:, 2] += 0.006
    result = cscv(r, 8)
    assert result.pbo == 0 and result.n_splits == 70 and result.prob_loss == 0


def test_pbo_high_when_winner_reverses():
    """Tiap variasi hanya bagus di satu blok: juara masa lalu buruk di sisanya."""
    r = np.random.default_rng(0).normal(0, 0.001, (800, 8))
    for k in range(8):
        r[:, k] -= 0.002
        r[k * 100:(k + 1) * 100, k] += 0.016
    assert cscv(r, 8).pbo > 0.9


def test_pbo_rejects_bad_input():
    with pytest.raises(ValueError):
        cscv(np.zeros((100, 1)))
    with pytest.raises(ValueError):
        cscv(np.zeros((100, 3)), 7)


# ---------- pencatat percobaan ----------

def seeded(tmp_path, n=1500):
    config = load_data_config(CONFIG / "instruments.yaml", tmp_path)
    store = Store(config.root, config.database)
    prices = synthetic_prices(n=n)
    days = pd.date_range("2019-01-01", periods=n, tz="UTC")
    rows = [[int(d.timestamp() * 1000), *map(float, v)] for d, v in zip(
        days, prices[["open", "high", "low", "close", "volume"]].to_numpy())]
    frame = ohlcv_frame(rows)
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    store.write(find_instrument(config, "BTC/USDT"), "ohlcv_1d", frame)
    return config, store, config.database.parent / journal.FILENAME


def bars(config, store):
    return load_bars(config, store, find_instrument(config, "BTC/USDT"), "1d",
                     allow_stale=True).df


def test_backtests_on_stored_data_are_logged_synthetic_are_not(tmp_path):
    config, store, db = seeded(tmp_path)
    run_backtest(synthetic_prices(n=300), get_strategy("sma_cross"), BacktestConfig())
    assert journal.count_variants(db) == 0
    df = bars(config, store)
    for _ in range(2):                                   # ulangan: run bertambah, variasi tidak
        run_backtest(df, get_strategy("sma_cross"), BacktestConfig())
    run_backtest(df.iloc[:700], get_strategy("sma_cross"), BacktestConfig(buy_fee_pct=1))
    assert journal.summary(db).iloc[0][["variasi", "run"]].tolist() == [1, 3]
    run_backtest(df, get_strategy("sma_cross", fast=10), BacktestConfig())
    run_backtest(df, get_strategy("rsi_meanrev"), BacktestConfig())
    assert journal.count_variants(db) == 3
    assert journal.count_variants(db, "sma_cross") == 2


def test_failed_run_is_logged(tmp_path):
    config, store, db = seeded(tmp_path)
    with pytest.raises(ValueError):
        run_backtest(bars(config, store).iloc[:20], get_strategy("sma_cross"), BacktestConfig())
    assert journal.summary(db).iloc[0]["gagal"] == 1


def test_walkforward_logs_every_combination(tmp_path):
    config, store, db = seeded(tmp_path)
    walk_forward(bars(config, store), "sma_cross", {"fast": [10, 20], "slow": [50, 100]},
                 BacktestConfig(), 2, 1)
    assert journal.count_variants(db) == 4


def test_portfolio_runs_are_logged_with_same_variant_id(tmp_path):
    config, store, db = seeded(tmp_path)
    run_backtest(bars(config, store), get_strategy("sma_cross"), BacktestConfig())
    cfg = yaml.safe_load((CONFIG / "backtest.yaml").read_text(encoding="utf-8"))
    cfg["instruments"] = [{"symbol": "BTC/USDT", "weight": 1.0}]
    p = prepare(config, store, cfg, allow_stale=True)
    run_period(config, store, p, plan(config, store, p)[0][0])
    assert journal.summary(db).iloc[0][["variasi", "run"]].tolist() == [1, 2]
    cfg["stops"] = {"stop_loss_pct": 5}                   # pengaturan baru = variasi baru
    p = prepare(config, store, cfg, allow_stale=True)
    run_period(config, store, p, plan(config, store, p)[0][0])
    assert journal.count_variants(db) == 2


def test_backtest_fails_if_it_cannot_be_logged(tmp_path, monkeypatch):
    config, store, _ = seeded(tmp_path)
    df = bars(config, store)

    def broken(*args, **kwargs):
        raise OSError("disk penuh")

    monkeypatch.setattr(journal, "record", broken)
    with pytest.raises(OSError):
        run_backtest(df, get_strategy("sma_cross"), BacktestConfig())


# ---------- validasi ----------

def research_config():
    return yaml.safe_load((CONFIG / "research.yaml").read_text(encoding="utf-8"))


def test_preregistered_thresholds():
    rules = research_config()["validation"]
    assert (rules["dsr_threshold"], rules["dsr_trials_required"], rules["pbo_threshold"]) \
        == (0.95, 50, 0.20)


def test_variants_share_dates_and_pay_entry_cost(tmp_path):
    config, store, _ = seeded(tmp_path)
    df = bars(config, store)
    matrix, params = variant_returns(df, "sma_cross", {"fast": [10], "slow": [50, 200]},
                                     BacktestConfig())
    assert len(params) == 2 and len(matrix) == len(df) - 200
    position = run_backtest(df, get_strategy("sma_cross", fast=10, slow=50),
                            BacktestConfig()).data["position"].iloc[200:]
    first = df["close"].pct_change().iloc[200] * position.iloc[0] - 0.002 * position.iloc[0]
    assert matrix[0].iloc[0] == pytest.approx(first)


def test_validate_end_to_end_and_frozen_data(tmp_path):
    config, store, db = seeded(tmp_path, n=2200)
    cfg = research_config()
    case = copy.deepcopy(cfg["cases"]["sma_cross_btc"])
    case.update(end="2024-12-31", data_fingerprint=None)
    _, _, mark = load_case(config, store, case)
    case["data_fingerprint"] = mark
    rules = {**cfg["validation"], "pbo_blocks": 8}
    result = validate(config, store, "uji", case, rules)
    assert len(result.variants) == 9 and set(result.dsr) == {9, 50, 100}
    assert result.passed == all(ok for _, _, ok in result.criteria)
    text = report(result, rules, journal.count_variants(db, "sma_cross"))
    assert "Putusan" in text and "PBO" in text and "belum diverifikasi" in text
    assert journal.count_variants(db, "sma_cross") == 9
    case["data_fingerprint"] = "0" * 16
    with pytest.raises(DataRejected, match="Data berubah"):
        validate(config, store, "uji", case, rules)
