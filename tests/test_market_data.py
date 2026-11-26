"""Tes pemuat data, biaya, dan likuiditas. Offline."""

from pathlib import Path

import pandas as pd
import pytest

from algotrade import cli
from algotrade.data.base import ohlcv_frame
from algotrade.data.store import Store
from algotrade.engine.costs import cost_model, vector_config
from algotrade.engine.liquidity import Liquidity
from algotrade.engine.market_data import DataRejected, find_instrument, load_bars
from algotrade.instruments import load_data_config

CONFIG = Path(__file__).resolve().parents[1] / "config"


def utc(text):
    return pd.Timestamp(text, tz="UTC")


def frame(dates, price=100.0):
    return ohlcv_frame([[int(utc(str(d)[:19]).timestamp() * 1000), price, price + 1, price - 1,
                         price, 5] for d in dates])


@pytest.fixture
def config(tmp_path):
    return load_data_config(CONFIG / "instruments.yaml", tmp_path)


def test_load_bars_rejects_bad_and_stale_data(config):
    store = Store(config.root, config.database)
    btc = find_instrument(config, "BTC/USDT")
    with pytest.raises(DataRejected, match="belum ada"):
        load_bars(config, store, btc, "1d")
    store.write(btc, "ohlcv_1d", frame(pd.date_range("2019-01-01", periods=10)))
    with pytest.raises(DataRejected, match="basi"):
        load_bars(config, store, btc, "1d", now=utc("2019-02-01"))
    bars = load_bars(config, store, btc, "1d", now=utc("2019-02-01"), allow_stale=True)
    assert bars.df["close_time"].iloc[0] == utc("2019-01-02")
    broken = frame(pd.date_range("2019-01-01", periods=10))
    broken.loc[3, "high"] = 1.0
    store.write(btc, "ohlcv_1d", broken)
    with pytest.raises(DataRejected, match="tidak masuk akal"):
        load_bars(config, store, btc, "1d", now=utc("2019-01-11 01:00"), allow_stale=True)


def test_equity_bar_is_known_only_after_exchange_closes(config):
    store = Store(config.root, config.database)
    spy = find_instrument(config, "SPY")
    store.write(spy, "ohlcv_1d", frame(["2024-01-12", "2024-01-16"]))
    df = load_bars(config, store, spy, "1d", now=utc("2024-01-16 23:00")).df
    assert df["open_time"].iloc[0] == utc("2024-01-12 14:30")
    assert df["close_time"].iloc[0] == utc("2024-01-12 21:00")


def test_costs_come_from_config(config):
    btc = cost_model(find_instrument(config, "BTC/USDT"))
    assert btc.buy_fee == pytest.approx(0.0015) and "taker_fee_pct" in btc.unverified
    spy = cost_model(find_instrument(config, "SPY"))
    assert spy.half_spread == pytest.approx(0.0001)
    sol = cost_model(find_instrument(config, "SOL-USDC-solana"))
    assert sol.buy_fee == pytest.approx(0.0004) and sol.gas_usd == 0.02
    assert "gas_usd" in sol.unverified and "swap_fee_pct" not in sol.unverified


def test_every_guessed_cost_is_marked():
    text = (CONFIG / "instruments.yaml").read_text(encoding="utf-8")
    marked = [line for line in text.splitlines() if "PERLU DICEK:" in line and ":" in line]
    assert len(marked) >= 17


def test_missing_cost_is_an_error(config):
    ins = find_instrument(config, "WETH-USDC-eth")
    ins.costs["swap_fee_pct"] = None
    with pytest.raises(ValueError, match="swap_fee_pct"):
        cost_model(ins)


def test_vector_config_dex_adds_impact_gas_and_enforces_cap(config):
    ins = find_instrument(config, "WETH-USDC-eth")
    bt = vector_config(ins, "1d", 1000, False, liquidity=1_000_000, max_order_pct=0.5)
    assert bt.buy_fee_pct == pytest.approx(0.05 + 100 * 1.0 / 1000)      # swap + gas
    assert bt.slippage_pct == pytest.approx(0.10 + 0.20 + 0.2)           # slip + MEV + impact
    assert bt.periods_per_year == 365
    with pytest.raises(ValueError, match="batas order"):
        vector_config(ins, "1d", 6000, False, liquidity=1_000_000, max_order_pct=0.5)
    with pytest.raises(ValueError, match="perpetual"):
        vector_config(find_instrument(config, "BTC/USDT:USDT"), "1d", 1000, False)


def test_liquidity_snapshot_and_indicative_rule():
    one = pd.DataFrame({"ts": [utc("2024-06-01")], "reserve_usd": [100.0]})
    pool = Liquidity(one, 0.5)
    assert pool.at(utc("2020-01-01")) == 50          # sebelum ada riwayat: potret terbaru
    assert not pool.covers(utc("2024-06-01"), 90)
    days = pd.date_range("2024-01-01", periods=100, tz="UTC")
    history = Liquidity(pd.DataFrame({"ts": days, "reserve_usd": range(100)}), 1.0)
    assert history.at(days[10] + pd.Timedelta(hours=5)) == 10
    assert history.covers(days[0], 90)
    assert not history.covers(utc("2023-01-01"), 90)  # backtest lebih awal dari riwayat


def test_cli_backtest_reads_store(config, tmp_path, monkeypatch, capsys):
    store = Store(config.root, config.database)
    btc = find_instrument(config, "BTC/USDT")
    days = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1),
                         periods=300)
    store.write(btc, "ohlcv_1d", frame(days.tz_localize(None)))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", [
        "algotrade", "backtest", "--config", str(CONFIG / "default.yaml"),
        "--data-config", str(CONFIG / "instruments.yaml")])
    cli.main()
    out = capsys.readouterr().out
    assert "BTC/USDT" in out and "PERLU DICEK" in out and "Buy & Hold" in out
