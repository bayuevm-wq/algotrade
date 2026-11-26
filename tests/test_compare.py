import pandas as pd
import pytest

from algotrade import cli
from algotrade.backtest import BacktestConfig, run_backtest
from algotrade.compare import compare_tickers, format_table, save_csv
from algotrade.data import synthetic_prices
from algotrade.strategies import get_strategy

DATA = {"AAA": synthetic_prices(n=600, seed=1), "BBB": synthetic_prices(n=600, seed=2)}
STRAT = get_strategy("sma_cross", fast=5, slow=20)


def test_two_rows_per_ticker_match_backtest():
    table, errors = compare_tickers(list(DATA), DATA.__getitem__, STRAT, BacktestConfig())
    assert not errors
    assert list(table["version"]) == ["Strategi", "Buy & Hold"] * 2
    res = run_backtest(DATA["AAA"], STRAT, BacktestConfig())
    assert table.iloc[0]["total_return"] == res.metrics["total_return"]
    assert table.iloc[1]["total_return"] == res.benchmark_metrics["total_return"]
    assert (table["total_cost"] > 0).all()
    assert "Buy & Hold" in format_table(table)


def test_failed_ticker_does_not_stop_others():
    table, errors = compare_tickers(["XXX", "AAA"], DATA.__getitem__, STRAT, BacktestConfig())
    assert list(errors) == ["XXX"]
    assert set(table["ticker"]) == {"AAA"}


def test_save_csv_roundtrip(tmp_path):
    table, _ = compare_tickers(["AAA"], DATA.__getitem__, STRAT, BacktestConfig())
    saved = pd.read_csv(save_csv(table, tmp_path / "sub" / "compare.csv"))
    assert len(saved) == 2
    assert saved["total_return"].tolist() == pytest.approx(table["total_return"].tolist())


def test_cli_compare_offline(tmp_path, monkeypatch, capsys):
    out = tmp_path / "compare.csv"
    monkeypatch.setattr("sys.argv", ["algotrade", "compare", "--synthetic",
                                     "--tickers", "AAA", "BBB", "--output", str(out)])
    cli.main()
    saved = pd.read_csv(out)
    assert saved["ticker"].unique().tolist() == ["SYNTHETIC-AAA", "SYNTHETIC-BBB"]
    assert "walk-forward" in capsys.readouterr().out


def test_cli_compare_all_failed_writes_nothing(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("tidak ada data")

    out = tmp_path / "compare.csv"
    monkeypatch.setattr(cli, "load_prices", fail)
    monkeypatch.setattr("sys.argv", ["algotrade", "compare", "--tickers", "AAA",
                                     "--output", str(out)])
    with pytest.raises(SystemExit):
        cli.main()
    assert not out.exists()
