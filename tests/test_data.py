"""Tes data multi-pasar. Semua offline: API diganti tiruan."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from algotrade import data_cli
from algotrade.data.archive import BinanceFundingArchive
from algotrade.data.base import ohlcv_frame
from algotrade.data.cex import CexAdapter
from algotrade.data.dex import DexAdapter
from algotrade.data.equity import EquityAdapter
from algotrade.data.http import Http, HttpError
from algotrade.data.quality import check_funding, check_ohlcv, status_of
from algotrade.data.resample import resample_ohlcv
from algotrade.data.store import Store
from algotrade.data.update import build_jobs, quality_report, run_jobs
from algotrade.instruments import load_data_config, timeframe_delta

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "instruments.yaml"
HOUR = 3_600_000


def utc(text):
    return pd.Timestamp(text, tz="UTC")


def hourly(start="2024-01-01", n=48):
    base = int(utc(start).timestamp() * 1000)
    return ohlcv_frame([[base + i * HOUR, 100 + i, 102 + i, 99 + i, 101 + i, 10]
                        for i in range(n)])


@pytest.fixture
def config(tmp_path):
    return load_data_config(CONFIG, tmp_path)


def pick(config, symbol):
    return next(i for i in config.instruments if i.symbol == symbol)


# ---------- instrumen & config ----------

def test_default_config_covers_phase_one(config):
    by_market = {m: [i for i in config.instruments if i.market == m]
                 for m in ("cex", "us_equity", "dex", "idx")}
    assert {"BTC/USDT", "ETH/USDT"} <= {i.symbol for i in by_market["cex"]}
    assert len(by_market["us_equity"]) == 21
    assert len(by_market["dex"]) == 3
    assert "BBCA.JK" in {i.symbol for i in by_market["idx"]}
    perp = pick(config, "BTC/USDT:USDT")
    assert perp.kind == "perp" and perp.quote == "USDT"
    assert perp.bars_per_year("1h") == 365 * 24
    assert pick(config, "SPY").bars_per_year("1d") == 252


def test_exchange_symbols_timeframes_come_from_config(tmp_path):
    text = CONFIG.read_text(encoding="utf-8")
    text = text.replace("exchange: okx", "exchange: kraken").replace(
        'symbols: [BTC/USDT, ETH/USDT, "BTC/USDT:USDT", "ETH/USDT:USDT"]', "symbols: [SOL/USD]")
    text = text.replace("timeframes: [1h]           #", "timeframes: [15m]          #")
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    ins = [i for i in load_data_config(path, tmp_path).instruments if i.market == "cex"]
    assert [(i.source, i.symbol, i.timeframes, i.quote) for i in ins] == [
        ("kraken", "SOL/USD", ("15m",), "USD")]


def test_bad_timeframe_rejected():
    with pytest.raises(ValueError):
        timeframe_delta("1w")


# ---------- resampling & penyimpanan ----------

def test_resample_only_complete_periods():
    df = hourly("2024-01-01 02:00", n=11)           # 02:00 .. 12:00
    out = resample_ohlcv(df, "1h", "4h")
    assert list(out["ts"]) == [utc("2024-01-01 04:00"), utc("2024-01-01 08:00")]
    first = out.iloc[0]                             # bar 04..07 = indeks 2..5
    assert (first.open, first.high, first.low, first.close) == (102, 107, 101, 106)
    assert first.volume == 40 and first.n_bars == 4


def test_resample_does_not_look_ahead():
    df = hourly(n=48)
    full = resample_ohlcv(df, "1h", "4h")
    partial = resample_ohlcv(df.iloc[:30], "1h", "4h")
    pd.testing.assert_frame_equal(full.iloc[: len(partial)], partial)
    with pytest.raises(ValueError):
        resample_ohlcv(df, "4h", "1h")


def test_store_incremental_merge_and_duckdb(config, tmp_path):
    import duckdb

    store = Store(config.root, config.database)
    btc = pick(config, "BTC/USDT")
    assert store.write(btc, "ohlcv_1h", hourly(n=10)) == 10
    revised = hourly("2024-01-01 08:00", n=5)       # 2 bar tumpang tindih + 3 baru
    assert store.write(btc, "ohlcv_1h", revised) == 3
    saved = store.read(btc, "ohlcv_1h")
    assert len(saved) == 13 and saved["ts"].is_monotonic_increasing
    assert saved.loc[8, "close"] == revised.loc[0, "close"]      # baris baru menang
    store.refresh_database()
    with duckdb.connect(str(config.database), read_only=True) as con:
        row = con.execute("SELECT count(*), min(symbol), min(timeframe) FROM ohlcv").fetchone()
    assert row == (13, "BTC/USDT", "1h")


# ---------- adapter ----------

class FakeExchange:
    """Data mulai 2024-01-10; maksimal 100 bar per halaman."""

    def __init__(self):
        self.bars = hourly("2024-01-10", n=500)
        self.times = (self.bars["ts"].astype("int64")).tolist()

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        window_end = since + limit * HOUR
        return [[t, 1, 2, 0.5, 1.5, 3] for t in self.times if since <= t < window_end][:100]

    def fetch_funding_rate_history(self, symbol, since, limit):
        rows = [{"timestamp": t, "fundingRate": 0.0001} for t in self.times[::8] if t >= since]
        return rows[:10]


def test_cex_paginates_past_empty_pages_and_drops_unfinished(config):
    adapter = CexAdapter("okx", page_limit=300, client=FakeExchange())
    until = utc("2024-01-15 00:30")
    df = adapter.fetch_ohlcv(pick(config, "BTC/USDT"), "1h", utc("2024-01-01"), until)
    assert df["ts"].iloc[0] == utc("2024-01-10")
    assert df["ts"].iloc[-1] == utc("2024-01-14 23:00")      # bar 00:00 belum selesai
    assert len(df) == 5 * 24 and not df["ts"].duplicated().any()


def test_cex_funding_paginates(config):
    adapter = CexAdapter("okx", client=FakeExchange())
    df = adapter.fetch_funding(pick(config, "BTC/USDT:USDT"), utc("2024-01-01"),
                               utc("2024-02-01"))
    assert len(df) == 63 and df["ts"].is_monotonic_increasing


def test_unknown_exchange_rejected():
    with pytest.raises(ValueError):
        CexAdapter("bursa_khayalan")


class FakeHttp:
    def __init__(self, handler):
        self.handler, self.urls = handler, []

    def get(self, url):
        self.urls.append(url)
        return self.handler(url)


def test_dex_pages_backwards_and_stops_at_history_limit(config):
    until = utc("2024-03-01")
    times = [int(until.timestamp()) - 3600 * i for i in range(1, 2501)]

    def handler(url):
        before = int(url.split("before_timestamp=")[1])
        if before <= times[1999]:
            raise HttpError(401, url)
        page = [[t, 1, 2, 0.5, 1.5, 9] for t in times if t < before][:1000]
        return json.dumps({"data": {"attributes": {"ohlcv_list": page}}}).encode()

    adapter = DexAdapter(http=FakeHttp(handler), history_days=180)
    df = adapter.fetch_ohlcv(pick(config, "WETH-USDC-eth"), "1h", utc("2023-01-01"), until)
    assert len(df) == 2000 and df["ts"].is_monotonic_increasing


def test_dex_liquidity_snapshot(config):
    body = {"data": {"attributes": {"reserve_in_usd": "5000000", "volume_usd": {"h24": "12"}}}}
    adapter = DexAdapter(http=FakeHttp(lambda url: json.dumps(body).encode()))
    df = adapter.fetch_liquidity(pick(config, "WETH-USDC-eth"), utc("2024-01-01"))
    assert df.iloc[0]["reserve_usd"] == 5_000_000


def test_equity_drops_session_that_has_not_closed(config):
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    raw = pd.DataFrame({"Open": [10, 11], "High": [12, 13], "Low": [9, 10], "Close": [11, 12],
                        "Adj Close": [5.5, 6], "Volume": [100, 100]}, index=idx)
    adapter = EquityAdapter(downloader=lambda *a, **k: raw.copy())
    spy = pick(config, "SPY")
    during = adapter.fetch_ohlcv(spy, "1d", utc("2024-01-01"), utc("2024-01-03 18:00"))
    after = adapter.fetch_ohlcv(spy, "1d", utc("2024-01-01"), utc("2024-01-03 22:00"))
    assert list(during["ts"]) == [utc("2024-01-02")]
    assert len(after) == 2
    assert after.iloc[0]["close"] == 5.5            # harga disesuaikan


def _zip(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("x.csv", text)
    return buffer.getvalue()


def test_funding_archive_checks_checksum_and_skips_missing_month():
    raw = _zip("calc_time,funding_interval_hours,last_funding_rate\n1704067200001,8,0.0001\n")
    good = hashlib.sha256(raw).hexdigest()

    def handler(url, digest=good):
        if "2024-02" in url:
            raise HttpError(404, url)
        return f"{digest}  x.zip".encode() if url.endswith("CHECKSUM") else raw

    df = BinanceFundingArchive(FakeHttp(handler)).fetch_funding(
        "BTCUSDT", utc("2024-01-01"), utc("2024-03-15"))
    assert list(df["ts"]) == [utc("2024-01-01")]
    bad = BinanceFundingArchive(FakeHttp(lambda url: handler(url, "0" * 64)))
    with pytest.raises(ValueError):
        bad.fetch_month("BTCUSDT", "2024-01")


def test_http_retries_rate_limit_only():
    import urllib.error

    calls, waits = [], []

    def opener(request, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 429, "slow", {}, None)
        return io.BytesIO(b"ok")

    assert Http(sleep=waits.append, opener=opener).get("https://x.test") == b"ok"
    assert waits == [15, 30]

    def missing(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(request.full_url, 404, "no", {}, None)

    calls.clear()
    with pytest.raises(HttpError):
        Http(sleep=waits.append, opener=missing).get("https://x.test")
    assert len(calls) == 1


# ---------- kualitas ----------

def rules(config, market):
    return config.markets[market]["quality"]


def test_quality_clean_data_is_ok(config):
    ins = pick(config, "WETH-USDC-eth")
    issues = check_ohlcv(hourly(n=48), ins, "1h", utc("2024-01-03 01:00"), rules(config, "dex"))
    assert status_of(issues) == "OK"


@pytest.mark.parametrize(("now", "expected"), [
    ("2024-01-05 23:00", "OK"),     # bar 5 Jan belum selesai, jadi 4 Jan masih terbaru
    ("2024-01-06 05:00", "OK"),     # masih dalam toleransi 6 jam
    ("2024-01-06 07:00", "GAGAL"),
])
def test_quality_daily_bar_staleness(config, now, expected):
    days = pd.date_range("2024-01-01", "2024-01-04", tz="UTC")
    df = ohlcv_frame([[int(d.timestamp() * 1000), 10, 11, 9, 10, 5] for d in days])
    ins = pick(config, "WETH-USDC-eth")
    issues = check_ohlcv(df, ins, "1d", utc(now), rules(config, "dex"), expect_start=False)
    assert status_of(issues) == expected


def test_quality_flags_errors_and_warnings(config):
    ins = pick(config, "WETH-USDC-eth")
    df = hourly(n=48).drop(index=[5, 6]).reset_index(drop=True)
    df.loc[10, "high"] = 1.0                        # high < low
    df.loc[20, "volume"] = 0
    issues = check_ohlcv(df, ins, "1h", utc("2024-01-10"), rules(config, "dex"))
    found = {(i.level, i.check) for i in issues}
    assert ("GAGAL", "high/low tidak masuk akal") in found
    assert ("GAGAL", "data basi") in found
    assert ("PERINGATAN", "celah waktu") in found
    assert ("PERINGATAN", "volume nol") in found
    assert status_of(check_ohlcv(None, ins, "1h", utc("2024-01-10"), rules(config, "dex"))) \
        == "GAGAL"


def test_quality_equity_uses_holiday_calendar(config):
    spy = pick(config, "SPY")
    days = ["2024-01-11", "2024-01-12", "2024-01-16"]      # 15 Jan 2024 libur bursa
    df = ohlcv_frame([[int(utc(d).timestamp() * 1000), 10, 11, 9, 10, 5] for d in days])
    issues = check_ohlcv(df, spy, "1d", utc("2024-01-16 23:00"), rules(config, "us_equity"),
                         expect_start=False)
    assert issues == []


def test_quality_funding(config):
    ts = pd.date_range("2024-01-01", periods=6, freq="8h", tz="UTC").delete(3)
    df = pd.DataFrame({"ts": ts, "funding_rate": [0.0001, np.nan, 0.01, 0.0001, 0.0001]})
    issues = check_funding(df, ts[-1], pd.Timedelta(hours=24), 0.005)
    assert {i.check for i in issues} >= {"funding kosong/tak hingga", "celah waktu",
                                         "funding ekstrem > 0.50%"}


# ---------- update ----------

class FakeAdapters:
    def __init__(self, now):
        self.calls = []
        outer = self

        class Cex:
            def fetch_ohlcv(self, ins, tf, since, until):
                outer.calls.append(since)
                start = max(since, now - pd.Timedelta(days=3)).ceil("h")
                n = max(int((until - start) / pd.Timedelta(hours=1)), 0)
                return hourly(str(start.tz_localize(None)), n=n)

            def fetch_funding(self, ins, since, until):
                raise ConnectionError("exchange mati")

        class Archive:
            def fetch_funding(self, symbol, since, until):
                return pd.DataFrame({"ts": [now - pd.Timedelta(days=1)], "funding_rate": [0.0]})

        self.cex, self.archive = Cex(), Archive()


def test_update_is_incremental_and_survives_failures(config):
    now = utc("2024-06-10")
    store = Store(config.root, config.database)
    adapters = FakeAdapters(now)
    jobs = build_jobs(config, store, adapters, now, market="cex")
    results = run_jobs(jobs, log=lambda m: None)
    failed = {(r.symbol, r.dataset) for r in results if r.error}
    assert failed == {("BTC/USDT:USDT", "funding"), ("ETH/USDT:USDT", "funding")}
    btc = pick(config, "BTC/USDT")
    assert store.read(btc, "ohlcv_4h") is not None and store.read(btc, "ohlcv_1d") is not None

    adapters.calls.clear()
    run_jobs(build_jobs(config, store, adapters, now, market="cex"), log=lambda m: None)
    last = store.read(btc, "ohlcv_1h")["ts"].max()
    assert min(adapters.calls) == last - pd.Timedelta(hours=3)      # hanya ambil yang baru

    report = quality_report(config, store, now, market="cex")
    okx = report[(report["source"] == "okx") & (report["dataset"] == "funding")]
    assert (okx["status"] == "GAGAL").all()             # data yang tidak ada = GAGAL
    assert "binance_archive" in set(report["source"])


def test_equity_update_keeps_old_data_when_download_shrinks(config):
    now = utc("2024-06-10")
    store = Store(config.root, config.database)
    spy = pick(config, "SPY")
    store.write(spy, "ohlcv_1d", hourly(n=100))

    class Adapters:
        class equity:
            @staticmethod
            def fetch_ohlcv(*args):
                return hourly(n=10)

    job = next(j for j in build_jobs(config, store, Adapters(), now, market="us_equity")
               if j.instrument.symbol == "SPY")
    result = run_jobs([job], log=lambda m: None)[0]
    assert "dipertahankan" in result.error
    assert len(store.read(spy, "ohlcv_1d")) == 100


def test_cli_quality_fails_on_empty_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(data_cli, "ROOT", tmp_path)
    from algotrade import cli

    monkeypatch.setattr("sys.argv", ["algotrade", "data", "quality", "--data-config",
                                     str(CONFIG), "--report", str(tmp_path / "q.csv")])
    with pytest.raises(SystemExit):
        cli.main()
    assert "GAGAL" in capsys.readouterr().out
    assert (tmp_path / "q.csv").exists()


# ---------- pengecualian kualitas ----------

def _bad_daily(date):
    days = pd.date_range(end=utc(date) + pd.Timedelta(days=1), periods=3)
    df = ohlcv_frame([[int(d.timestamp() * 1000), 10, 11, 9, 10, 5] for d in days])
    df.loc[df["ts"] == utc(date), "open"] = 8.0              # di bawah low
    return df


def _levels(config, symbol, date):
    issues = check_ohlcv(_bad_daily(date), pick(config, symbol), "1d",
                         utc(date) + pd.Timedelta(days=2), rules(config, "idx"),
                         expect_start=False)
    return {(i.level, i.check) for i in issues if "high/low" in i.check}


def test_exception_downgrades_only_listed_symbol_and_date(config):
    excused = {("PERINGATAN", "dikecualikan: high/low tidak masuk akal")}
    failed = {("GAGAL", "high/low tidak masuk akal")}
    assert _levels(config, "BBRI.JK", "2016-04-20") == excused
    assert _levels(config, "TLKM.JK", "2016-04-20") == excused
    assert _levels(config, "BBRI.JK", "2016-04-21") == failed      # tanggal lain
    assert _levels(config, "BBCA.JK", "2016-04-20") == failed      # simbol lain


@pytest.mark.parametrize(("old", "new"), [
    ("check: high/low tidak masuk akal", "check: data basi"),
    ("symbol: BBRI.JK\n    date", "symbol: SALAH.JK\n    date"),
    ('reason: "Yahoo: harga buka 3650 di atas high 3635 (mentah), diperiksa 2026-11-26"',
     'reason: ""'),
])
def test_bad_exception_entry_rejected(tmp_path, old, new):
    text = CONFIG.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "c.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError):
        load_data_config(path, tmp_path)
