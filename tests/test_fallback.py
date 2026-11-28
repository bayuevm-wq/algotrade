"""Tes exchange cadangan. Offline."""

from pathlib import Path

import ccxt
import pandas as pd
import pytest

from algotrade import cli, data_cli
from algotrade.data.base import ohlcv_frame
from algotrade.data.cex import CexAdapter
from algotrade.data.store import Store
from algotrade.data.update import build_jobs, fallback_jobs, quality_report, run_jobs
from algotrade.instruments import load_data_config

CONFIG = Path(__file__).resolve().parents[1] / "config"
HOUR = 3_600_000
NOW = pd.Timestamp("2024-06-10 00:30", tz="UTC")


def bars(since, until, price=100.0):
    first = int(max(since, until - pd.Timedelta(days=3)).ceil("h").timestamp() * 1000)
    stop = int(until.floor("h").timestamp() * 1000)
    return ohlcv_frame([[t, price, price + 1, price - 1, price, 5]
                        for t in range(first, stop, HOUR)])


class Adapters:
    """Utama (OKX) mati; cadangan hidup dengan harga berbeda."""

    def __init__(self, primary_error=ccxt.NetworkError, backup_error=None):
        class Primary:
            def fetch_ohlcv(self, ins, tf, since, until):
                if primary_error:
                    raise primary_error("tidak bisa dihubungi")
                return bars(since, until)

            def fetch_funding(self, ins, since, until):
                if primary_error:
                    raise primary_error("tidak bisa dihubungi")
                return pd.DataFrame({"ts": [until - pd.Timedelta(hours=1)],
                                     "funding_rate": [0.0]})

        class Backup:
            def fetch_ohlcv(self, ins, tf, since, until):
                if backup_error:
                    raise backup_error("cadangan mati")
                return bars(since, until, price=200.0)

        class Archive:
            def fetch_funding(self, symbol, since, until):
                return pd.DataFrame({"ts": [until - pd.Timedelta(days=1)], "funding_rate": [0.0]})

        self.cex, self.fallback, self.archive = Primary(), Backup(), Archive()


@pytest.fixture
def config(tmp_path):
    return load_data_config(CONFIG / "instruments.yaml", tmp_path)


def update(config, adapters):
    store = Store(config.root, config.database)
    quiet = {"log": lambda m: None}
    results = run_jobs(build_jobs(config, store, adapters, NOW, market="cex"), **quiet)
    extra = fallback_jobs(config, store, adapters, NOW, results)
    backup = run_jobs(extra, **quiet)
    report = quality_report(config, store, NOW, "cex", extra)
    return store, results, extra, backup, report


def test_config_defines_separate_backup_instruments(config):
    assert [(i.source, i.symbol, i.kind) for i in config.fallbacks] == [
        ("indodax", "BTC/USDT", "spot"), ("indodax", "ETH/USDT", "spot")]
    assert all(i.source == "okx" for i in config.instruments if i.market == "cex")
    assert "taker_fee_pct" in config.fallbacks[0].costs["unverified"]


def test_backup_used_only_when_primary_unreachable(config):
    _, _, extra, _, _ = update(config, Adapters(primary_error=None))
    assert extra == []
    _, _, extra, _, _ = update(config, Adapters(primary_error=ValueError))   # bukan jaringan
    assert extra == []


def test_backup_stored_separately_and_not_stitched(config):
    store = Store(config.root, config.database)
    btc = next(i for i in config.instruments if i.symbol == "BTC/USDT" and i.source == "okx")
    old = bars(NOW - pd.Timedelta(days=10), NOW - pd.Timedelta(days=5))
    store.write(btc, "ohlcv_1h", old)
    store, _, extra, backup, report = update(config, Adapters())
    assert {j.instrument.source for j in extra} == {"indodax"}
    assert not any(r.error for r in backup)
    kept = store.read(btc, "ohlcv_1h")
    assert len(kept) == len(old) and (kept["close"] == 100).all()      # utama tidak disentuh
    copy = store.read(config.fallbacks[0], "ohlcv_1h")
    assert (copy["close"] == 200).all() and set(copy["source"]) == {"indodax"}
    assert store.path(config.fallbacks[0], "ohlcv_1h") != store.path(btc, "ohlcv_1h")
    assert "indodax" in set(report["source"])


def seed_primary(config):
    """Data utama lama (basi), seperti kondisi nyata saat exchange baru diblokir."""
    update(config, Adapters(primary_error=None))


def later_run(config, adapters):
    store = Store(config.root, config.database)
    later = NOW + pd.Timedelta(days=2)
    results = run_jobs(build_jobs(config, store, adapters, later, market="cex"),
                       log=lambda m: None)
    extra = fallback_jobs(config, store, adapters, later, results)
    backup = run_jobs(extra, log=lambda m: None)
    return results, backup, quality_report(config, store, later, "cex", extra)


def test_exit_codes(config):
    seed_primary(config)
    results, backup, report = later_run(config, Adapters())
    assert data_cli.exit_code("okx", results, backup, report) == 2
    results, backup, report = later_run(config, Adapters(backup_error=ccxt.NetworkError))
    assert data_cli.exit_code("okx", results, backup, report) == 1      # cadangan juga gagal
    results, backup, report = later_run(config, Adapters(primary_error=ValueError))
    assert data_cli.exit_code("okx", results, backup, report) == 1      # bukan soal akses
    clean = report.assign(status="OK", issues="")
    assert data_cli.exit_code("okx", [], [], clean) == 0
    # masalah kualitas lain tidak boleh tertutup oleh kode 2
    results, backup, report = later_run(config, Adapters())
    report.loc[report.index[0], ["source", "status", "issues"]] = [
        "yfinance", "GAGAL", "GAGAL: harga <= 0 (1)"]
    assert data_cli.exit_code("okx", results, backup, report) == 1


def test_adapter_sends_end_in_seconds_when_required(config):
    calls = []

    class Client:
        def fetch_ohlcv(self, symbol, timeframe, since, limit, params=None):
            calls.append((since, params))
            return [[since, 1, 2, 0.5, 1.5, 1]]

    adapter = CexAdapter("indodax", page_limit=500, client=Client(), end_param="to")
    adapter.fetch_ohlcv(config.fallbacks[0], "1h", NOW - pd.Timedelta(hours=3), NOW)
    since, params = calls[0]
    assert since // 1000 < params["to"] <= int(NOW.timestamp())     # detik, bukan milidetik


def test_backtest_uses_backup_only_when_asked(config, tmp_path, monkeypatch, capsys):
    store = Store(config.root, config.database)
    days = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1),
                         periods=300)
    frame = ohlcv_frame([[int(d.timestamp() * 1000), 10, 11, 9, 10, 1] for d in days])
    store.write(config.fallbacks[0], "ohlcv_1d", frame)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    base = ["algotrade", "backtest", "--config", str(CONFIG / "default.yaml"),
            "--data-config", str(CONFIG / "instruments.yaml")]
    monkeypatch.setattr("sys.argv", base)                         # utama kosong: ditolak
    with pytest.raises(SystemExit, match="DITOLAK"):
        cli.main()
    monkeypatch.setattr("sys.argv", [*base, "--source", "indodax"])
    cli.main()
    assert "CADANGAN indodax" in capsys.readouterr().out
