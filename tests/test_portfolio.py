"""Tes mesin portofolio. Setiap angka harapan dihitung tangan. Offline."""

from pathlib import Path

import pandas as pd
import pytest

from algotrade import cli
from algotrade.data.base import ohlcv_frame
from algotrade.data.store import Store
from algotrade.engine import funding as fund
from algotrade.engine.costs import CostModel
from algotrade.engine.liquidity import Liquidity
from algotrade.engine.market_data import DataRejected, add_bar_times, find_instrument
from algotrade.engine.portfolio import Asset, Settings, run_portfolio
from algotrade.engine.runner import plan, prepare, run_period
from algotrade.instruments import Instrument, load_data_config
from algotrade.strategies import STRATEGIES, get_strategy

CONFIG = Path(__file__).resolve().parents[1] / "config"
FREE = CostModel()


def utc(text):
    return pd.Timestamp(text, tz="UTC")


def instrument(symbol="X", market="cex", kind="spot"):
    return Instrument(symbol=symbol, market=market, source="test", kind=kind, quote="USDT",
                      session="24/7", periods_per_year=365, timeframes=("1d",))


def asset(rows, signal=None, costs=FREE, kind="spot", market="cex", weight=1.0, symbol="X",
          **extra):
    """rows = [(open, high, low, close), ...] mulai 1 Jan 2024."""
    index = pd.date_range("2024-01-01", periods=len(rows), tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    ins = instrument(symbol, market, kind)
    df = add_bar_times(df, ins, "1d")
    values = [1.0] * len(rows) if signal is None else signal
    return Asset(ins, df, pd.Series(values, index=index, dtype=float), weight, costs, **extra)


def flat(*prices):
    return [(p, p, p, p) for p in prices]


def run(assets, **settings):
    assets = assets if isinstance(assets, list) else [assets]
    start = assets[0].bars["close_time"].iloc[0]          # sinyal bar pertama sudah diketahui
    end = assets[0].bars["close_time"].iloc[-1]
    return run_portfolio(assets, Settings(**{"capital": 1000.0, **settings}), start, end)


def funding_at(*pairs):
    return pd.DataFrame({"ts": [utc(t) for t, _ in pairs],
                         "funding_rate": [r for _, r in pairs]})


# ---------- eksekusi & Buy and Hold ----------

def test_signal_fills_at_next_open_and_matches_hand_buy_and_hold():
    rows = [(90, 95, 85, 94), (100, 106, 99, 105), (105, 121, 104, 120)]
    res = run(asset(rows, costs=CostModel(buy_fee=0.001, sell_fee=0.001, slippage=0.002)))
    first = res.trades.iloc[0]
    assert first["time"] == utc("2024-01-02") and first["price"] == 100
    fill = 100 * 1.002
    qty = 1000 / (fill * 1.001)                   # seluruh kas habis termasuk fee
    assert first["qty"] == pytest.approx(qty)
    assert res.equity.iloc[-1] == pytest.approx(qty * 120)
    assert res.metrics["total_return"] == pytest.approx(qty * 120 / 1000 - 1)


def test_lot_rounding_leaves_cash():
    res = run(asset(flat(300, 300, 330), lot=1.0))
    assert res.trades.iloc[0]["qty"] == 3
    assert res.equity.iloc[-1] == pytest.approx(100 + 3 * 330)


def test_sells_free_cash_before_buys():
    a = asset(flat(100, 100, 100), [1, 0, 0], symbol="A")
    b = asset(flat(50, 50, 50), [0, 1, 1], symbol="B")
    res = run([a, b])
    assert list(res.trades["symbol"]) == ["A", "A", "B"]
    assert res.trades.iloc[-1]["qty"] == pytest.approx(20)       # kas dari A dipakai B
    assert res.equity.iloc[-1] == pytest.approx(1000)


def test_no_lookahead_in_engine():
    rows = [(100 + i, 103 + i, 97 + i, 101 + i) for i in range(30)]
    signal = [i % 7 > 2 for i in range(30)]
    full = run(asset(rows, signal))
    part = run(asset(rows[:20], signal[:20]))
    pd.testing.assert_series_equal(full.equity.iloc[: len(part.equity)], part.equity)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategy_signals_through_engine_ignore_future(name):
    from algotrade.data import synthetic_prices

    prices = synthetic_prices(n=400)
    prices.index = prices.index.tz_localize("UTC")
    results = []
    for n in (300, 400):
        df = add_bar_times(prices.iloc[:n], instrument(), "1d")
        a = Asset(instrument(), df, get_strategy(name).generate_signals(df), 1.0, FREE)
        results.append(run_portfolio([a], Settings(1000), df["close_time"].iloc[0],
                                     df["close_time"].iloc[-1]).equity)
    pd.testing.assert_series_equal(results[0], results[1].loc[: results[0].index[-1]])


# ---------- biaya DEX ----------

def pool(reserve):
    return Liquidity(pd.DataFrame({"ts": [utc("2024-01-01")], "reserve_usd": [reserve]}), 1.0)


def test_gas_and_price_impact_hand_calculation():
    costs = CostModel(buy_fee=0.003, gas_usd=2.0, uses_pool=True)
    a = asset(flat(100, 100, 100), costs=costs, market="dex", kind="pool", weight=0.5,
              liquidity=pool(1_000_000))
    res = run(a)
    trade = res.trades.iloc[0]
    # order $500 pada pool $1 juta: impact = 500 / 500000 = 0.1%
    assert trade["impact"] == pytest.approx(500 * 0.001)
    assert trade["fill"] == pytest.approx(100.1)
    assert trade["fee"] == pytest.approx(5 * 100.1 * 0.003)
    assert trade["gas"] == 2.0
    spent = 5 * 100.1 + trade["fee"] + 2.0
    assert res.equity.iloc[-1] == pytest.approx(1000 - spent + 5 * 100)


def test_order_cap_splits_orders_across_bars():
    costs = CostModel(uses_pool=True)
    a = asset(flat(100, 100, 100, 100, 100), costs=costs, market="dex", kind="pool",
              liquidity=pool(40_000))
    res = run(a, max_order_pct=0.005)                     # maksimal $200 per order
    assert list(res.trades["notional"].round(6))[:4] == [200, 200, 200, 200]
    assert res.capped_orders == 4
    assert (res.trades["notional"] <= 200 + 1e-9).all()


def test_cap_also_limits_exit():
    costs = CostModel(uses_pool=True)
    a = asset(flat(100, 100, 100, 100, 100), [1, 1, 0, 0, 0], costs=costs, market="dex",
              kind="pool", weight=0.4, liquidity=pool(60_000))
    res = run(a, max_order_pct=0.005)                     # maksimal $300
    # Order 1: 3 unit pada fill 101 (impact 1% = $3) -> equity 997.
    # Target 40% x 997 / 100 = 3,988 unit -> sisa 0,988; keluar juga dua kali.
    assert list(res.trades["qty"].round(6)) == [3, 0.988, -3, -0.988]


# ---------- perpetual ----------

def perp(rows, signal=None, mmr=0.004, **extra):
    return asset(rows, signal, costs=CostModel(maintenance_margin=mmr), kind="perp", **extra)


def test_long_pays_positive_funding_and_position_timing():
    funding = funding_at(("2024-01-02 00:00", 0.01),     # saat posisi BELUM dibuka
                         ("2024-01-02 08:00", 0.001), ("2024-01-02 16:00", -0.0004))
    res = run(perp(flat(100, 100, 100), funding=funding))
    paid = res.trades.loc[res.trades["reason"] == "funding", "funding"]
    assert list(paid.round(6)) == [1.0, -0.4]             # 10 unit x 100 x rate
    assert res.equity.iloc[-1] == pytest.approx(999.4)


def test_short_receives_positive_funding_and_stress():
    funding = funding_at(("2024-01-02 08:00", 0.001), ("2024-01-02 16:00", -0.001))
    base = {"signal": [-1, -1, -1], "funding": funding, "allow_short": True}
    res = run(perp(flat(100, 100, 100), **base))
    assert res.equity.iloc[-1] == pytest.approx(1000)     # +1 lalu -1
    harsh = run(perp(flat(100, 100, 100), **base), funding_cost_mult=2, funding_income_mult=0.5)
    assert harsh.equity.iloc[-1] == pytest.approx(1000 + 0.5 - 2)


def test_short_blocked_unless_allowed():
    res = run(perp(flat(100, 100, 100), signal=[-1, -1, -1]))
    assert res.trades.empty


def test_long_liquidation_hand_calculation():
    rows = [(100, 100, 100, 100), (100, 101, 80, 90), (90, 91, 89, 90)]
    res = run(perp(rows), leverage=5)
    event = res.trades[res.trades["reason"] == "likuidasi"].iloc[0]
    # 50 unit, margin 1000: harga likuidasi = (5000-1000) / (50*0.996)
    assert event["price"] == pytest.approx(4000 / 49.8)
    assert event["liquidation"] == pytest.approx(0.004 * 50 * 4000 / 49.8)   # sisa nilai
    assert res.liquidations == 1 and res.equity.iloc[-1] == pytest.approx(0)


def test_short_liquidation_price_and_isolated_margin():
    rows = [(100, 100, 100, 100), (100, 130, 99, 125), (125, 126, 124, 125)]
    res = run(perp(rows, signal=[-1, -1, -1], weight=0.5, allow_short=True), leverage=5)
    event = res.trades[res.trades["reason"] == "likuidasi"].iloc[0]
    assert event["price"] == pytest.approx((25 * 100 + 500) / (25 * 1.004))
    assert res.equity.iloc[-1] == pytest.approx(500)      # hanya margin yang hilang
    assert (res.trades["reason"] == "sinyal").sum() == 1  # tidak masuk lagi selama sinyal sama


def test_funding_can_trigger_liquidation():
    funding = funding_at(("2024-01-02 08:00", 0.2))
    res = run(perp(flat(100, 100, 100), funding=funding), leverage=5)
    assert res.liquidations == 1


def test_liquidation_after_funding_drained_margin_never_goes_negative():
    rows = [(100, 100, 100, 100), (100, 300, 100, 300), (300, 300, 140, 145)]
    funding = funding_at(("2024-01-03 00:00", 0.5))       # bayar 10 x 300 x 0.5 = 1500
    res = run(perp(rows, funding=funding))
    event = res.trades[res.trades["reason"] == "likuidasi"].iloc[0]
    assert event["price"] == pytest.approx((1000 + 500) / (10 * 0.996))      # margin -500
    assert res.equity.iloc[-1] == pytest.approx(0)
    assert (res.equity >= 0).all()


def test_perp_profit_with_leverage():
    res = run(perp(flat(100, 100, 110)), leverage=2)
    assert res.equity.iloc[-1] == pytest.approx(1200)     # 20 unit x +10
    short = run(perp(flat(100, 100, 90), signal=[-1, -1, -1], allow_short=True))
    assert short.equity.iloc[-1] == pytest.approx(1100)


# ---------- stop & take-profit ----------

def test_stop_wins_when_both_touched_in_same_bar():
    rows = [(100, 100, 100, 100), (100, 120, 90, 100), (100, 100, 100, 100)]
    res = run(asset(rows), stop_loss=0.05, take_profit=0.10)
    assert res.trades.iloc[-1]["reason"] == "stop"
    assert res.trades.iloc[-1]["price"] == pytest.approx(95)
    assert len(res.trades) == 2                           # tidak langsung masuk lagi


def test_gap_below_stop_fills_at_open():
    rows = [(100, 100, 100, 100), (100, 101, 99, 100), (80, 85, 78, 82)]
    res = run(asset(rows), stop_loss=0.05)
    assert res.trades.iloc[-1]["reason"] == "stop (gap)"
    assert res.trades.iloc[-1]["price"] == 80
    assert res.equity.iloc[-1] == pytest.approx(800)


def test_take_profit_and_reentry_after_signal_changes():
    rows = [(100, 100, 100, 100), (100, 115, 100, 112), (112, 112, 112, 112),
            (112, 112, 112, 112), (112, 112, 112, 112)]
    res = run(asset(rows, [1, 1, 0, 1, 1]), take_profit=0.10)
    assert list(res.trades["reason"]) == ["sinyal", "take-profit", "sinyal"]
    assert res.trades.iloc[1]["price"] == pytest.approx(110)
    assert res.trades.iloc[-1]["time"] == utc("2024-01-05")


# ---------- aturan funding ----------

def series(start, periods):
    ts = pd.date_range(start, periods=periods, freq="8h", tz="UTC")
    return pd.DataFrame({"ts": ts, "funding_rate": 0.0001})


def test_funding_gap_or_short_coverage_rejected():
    df = series("2024-01-01", 30)
    fund.check_window(df, utc("2024-01-02"), utc("2024-01-09"), "x")
    with pytest.raises(DataRejected, match="bolong"):
        fund.check_window(df.drop(index=[10, 11]), utc("2024-01-02"), utc("2024-01-09"), "x")
    with pytest.raises(DataRejected, match="tidak menutup"):
        fund.check_window(df, utc("2023-12-01"), utc("2024-01-09"), "x")


def test_periods_are_separate_never_stitched():
    coverage = {fund.ARCHIVE: [(utc("2020-01-01"), utc("2024-10-31"))],
                fund.NATIVE: [(utc("2024-08-26"), utc("2024-11-26"))]}
    periods, overlap = fund.plan_periods(coverage, utc("2021-01-01"), utc("2024-11-25"))
    assert [(p.source, p.start, p.end) for p in periods] == [
        (fund.ARCHIVE, utc("2021-01-01"), utc("2024-08-26")),
        (fund.NATIVE, utc("2024-08-26"), utc("2024-11-25"))]
    assert (overlap.start, overlap.end) == (utc("2024-08-26"), utc("2024-10-31"))
    spot, none = fund.plan_periods({}, utc("2021-01-01"), utc("2022-01-01"))
    assert len(spot) == 1 and none is None


def seeded_store(tmp_path):
    """Store kecil: perpetual BTC + SPY + dua sumber funding."""
    config = load_data_config(CONFIG / "instruments.yaml", tmp_path)
    store = Store(config.root, config.database)

    def bars(days):
        return ohlcv_frame([[int(d.timestamp() * 1000), 100 + i % 9, 111, 95, 100 + i % 7, 5]
                            for i, d in enumerate(days)])

    btc = find_instrument(config, "BTC/USDT:USDT")
    store.write(btc, "ohlcv_1d", bars(pd.date_range("2024-01-01", "2024-06-30", tz="UTC")))
    spy = find_instrument(config, "SPY")
    store.write(spy, "ohlcv_1d", bars(pd.bdate_range("2024-01-02", "2024-06-28", tz="UTC")
                                      .difference(pd.DatetimeIndex(
                                          ["2024-01-15", "2024-02-19", "2024-03-29",
                                           "2024-05-27", "2024-06-19"], tz="UTC"))))
    from dataclasses import replace

    for source, start, end in [("binance_archive", "2024-01-01", "2024-05-31"),
                               ("okx", "2024-04-01", "2024-07-02")]:
        ts = pd.date_range(start, end, freq="8h", tz="UTC")
        store.write(replace(btc, source=source), "funding",
                    pd.DataFrame({"ts": ts, "funding_rate": 0.0001}))
    liq = pd.DataFrame({"ts": [utc("2024-07-01")], "reserve_usd": [5e7],
                        "volume_24h_usd": [1.0]})
    store.write(find_instrument(config, "WETH-USDC-eth"), "liquidity", liq)
    store.write(find_instrument(config, "WETH-USDC-eth"), "ohlcv_1d",
                bars(pd.date_range("2024-01-01", "2024-06-30", tz="UTC")))
    return config, store


def portfolio_config(*symbols):
    import yaml

    cfg = yaml.safe_load((CONFIG / "backtest.yaml").read_text(encoding="utf-8"))
    cfg["instruments"] = [{"symbol": s, "weight": 1 / len(symbols)} for s in symbols]
    cfg["strategy"] = {"name": "sma_cross", "params": {"fast": 3, "slow": 8}}
    return cfg


def test_runner_splits_periods_and_benchmarks_pay_costs(tmp_path):
    config, store = seeded_store(tmp_path)
    p = prepare(config, store, portfolio_config("BTC/USDT:USDT", "SPY"), allow_stale=True)
    periods, overlap = plan(config, store, p)
    assert [x.source for x in periods] == [fund.ARCHIVE, fund.NATIVE]
    assert periods[0].end == periods[1].start == utc("2024-04-01")
    result = run_period(config, store, p, periods[1])
    first = result.benchmark.trades.iloc[0]
    assert first["fee"] + first["slippage"] > 0
    # tanpa data spot: benchmark memakai perpetual dan diberi catatan
    assert result.benchmark.trades["funding"].sum() > 0
    assert any("memakai perpetual" in n for n in p.notes)
    assert result.strategy.equity.index[0] >= utc("2024-04-01")
    assert overlap is not None


def test_perp_benchmark_is_spot_without_funding(tmp_path):
    config, store = seeded_store(tmp_path)
    perp_ins = find_instrument(config, "BTC/USDT:USDT")
    spot = find_instrument(config, "BTC/USDT")
    store.write(spot, "ohlcv_1d", store.read(perp_ins, "ohlcv_1d"))
    p = prepare(config, store, portfolio_config("BTC/USDT:USDT"), allow_stale=True)
    result = run_period(config, store, p, plan(config, store, p)[0][1])
    assert set(result.benchmark.trades["symbol"]) == {"BTC/USDT"}
    assert result.benchmark.trades["funding"].sum() == 0
    assert result.benchmark.trades["fee"].iloc[0] > 0


def test_runner_rejects_idr_and_overweight(tmp_path):
    config, store = seeded_store(tmp_path)
    with pytest.raises(DataRejected, match="IDR"):
        prepare(config, store, portfolio_config("BBCA.JK"), allow_stale=True)
    heavy = portfolio_config("SPY", "BTC/USDT:USDT")
    heavy["instruments"][0]["weight"] = 0.9
    with pytest.raises(DataRejected, match="weight"):
        prepare(config, store, heavy, allow_stale=True)


def test_cli_portfolio_end_to_end(tmp_path, monkeypatch, capsys):
    seeded_store(tmp_path)
    from algotrade import portfolio_cli

    monkeypatch.setattr(portfolio_cli, "ROOT", tmp_path)
    import yaml

    path = tmp_path / "bt.yaml"
    path.write_text(yaml.safe_dump(portfolio_config("BTC/USDT:USDT", "WETH-USDC-eth")),
                    encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "algotrade", "portfolio", "--config", str(path), "--allow-stale",
        "--data-config", str(CONFIG / "instruments.yaml"), "--reports", str(tmp_path / "r")])
    cli.main()
    out = capsys.readouterr().out
    for text in ["INDIKATIF", "ARSIP BINANCE (pengganti)", "binance_archive", "okx",
                 "funding lebih mahal", "likuiditas 25%", "likuiditas 100%", "PERLU DICEK"]:
        assert text in out
    assert len(list((tmp_path / "r").glob("portfolio_*_trades.csv"))) == 2
