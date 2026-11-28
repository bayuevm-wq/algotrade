"""Uji overfitting satu kasus yang SUDAH ditetapkan di config/research.yaml."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from ..backtest import BacktestConfig, apply_costs, run_backtest
from ..data.store import Store
from ..engine.costs import cost_model, vector_config
from ..engine.market_data import DataRejected, find_instrument, load_bars
from ..instruments import DataConfig
from ..metrics import compute_metrics
from ..strategies import get_strategy
from ..walkforward import expand_grid, walk_forward
from . import journal, stats
from .pbo import PboResult, cscv


@dataclass
class Validation:
    name: str
    fingerprint: str
    start: pd.Timestamp
    end: pd.Timestamp
    variants: pd.DataFrame          # per kombinasi: parameter & Sharpe tahunan
    best: dict
    dsr: dict[int, float]           # jumlah percobaan -> DSR
    dsr_required: int
    pbo: PboResult
    walkforward: dict               # metrik strategi & Buy and Hold (biaya normal)
    info: dict                      # uji tambahan, tidak menentukan kelulusan
    criteria: list[tuple[str, str, bool]]
    unverified: tuple[str, ...]
    periods_per_year: int

    @property
    def passed(self) -> bool:
        return all(ok for _, _, ok in self.criteria)


def load_case(config: DataConfig, store: Store, case: dict):
    """Data beku sesuai config. Menolak bila datanya berubah sejak ditetapkan."""
    ins = find_instrument(config, case["symbol"], case["market"])
    # Periode lampau yang dibekukan, jadi "data basi" tidak relevan
    bars = load_bars(config, store, ins, case["timeframe"], str(case["start"]),
                     str(case["end"]), allow_stale=True)
    found = journal.fingerprint(bars.df)
    expected = case.get("data_fingerprint")
    if expected and found != expected:
        raise DataRejected(f"Data berubah sejak kasus ditetapkan (sidik jari {found}, "
                           f"seharusnya {expected}). Hasil tidak bisa dibandingkan.")
    return ins, bars.df, found


def variant_returns(df: pd.DataFrame, strategy_name: str, grid: dict,
                    bt: BacktestConfig) -> tuple[pd.DataFrame, list[dict]]:
    """Return bersih tiap kombinasi pada tanggal yang SAMA (setelah warmup terpanjang)."""
    params_list, strategies = [], []
    for params in expand_grid(grid):
        try:
            strategies.append(get_strategy(strategy_name, **params))
        except ValueError:
            continue
        params_list.append(params)
    first = max(s.warmup for s in strategies) + 1
    asset_ret = df["close"].pct_change().fillna(0.0)
    columns = {}
    for number, strategy in enumerate(strategies):
        position = run_backtest(df, strategy, bt).data["position"].iloc[first:]
        _, columns[number] = apply_costs(position, asset_ret.iloc[first:], bt)
    return pd.DataFrame(columns), params_list


def _dsr_table(matrix: pd.DataFrame, trials: list[int], variance: float | None = None):
    sharpes = np.array([stats.sharpe_per_bar(matrix[c]) for c in matrix])
    best = int(sharpes.argmax())
    skew, kurtosis = stats.skew_kurtosis(matrix[best])
    measured = float(sharpes.var(ddof=1))
    table = {n: stats.deflated_sharpe(sharpes[best], measured if variance is None else variance,
                                      n, len(matrix), skew, kurtosis) for n in trials}
    return sharpes, best, skew, kurtosis, measured, table


def _walk(df, case: dict, bt: BacktestConfig):
    wf = case["walkforward"]
    table, returns, metrics, bench = walk_forward(
        df, case["strategy"], case["param_grid"], bt, wf["train_years"], wf["test_years"],
        wf["metric"])
    asset_ret = df["close"].pct_change().fillna(0.0).loc[returns.index]
    _, hold = apply_costs(pd.Series(1.0, index=returns.index), asset_ret, bt)
    return table, returns, hold, metrics, bench


def validate(config: DataConfig, store: Store, name: str, case: dict, rules: dict) -> Validation:
    ins, df, found = load_case(config, store, case)
    capital = float(case["initial_capital"])
    bt = vector_config(ins, case["timeframe"], capital, False)
    annual = np.sqrt(bt.periods_per_year)
    matrix, params = variant_returns(df, case["strategy"], case["param_grid"], bt)

    trials = sorted({len(params), *rules["dsr_trials_report"], rules["dsr_trials_required"]})
    sharpes, best, skew, kurtosis, variance, dsr = _dsr_table(matrix, trials)
    pbo = cscv(matrix.to_numpy(), rules["pbo_blocks"])
    windows, wf_ret, hold_ret, wf_metrics, bench = _walk(df, case, bt)

    # ----- tambahan (informasi saja) -----
    stress = rules["cost_stress_multiplier"]
    costly = replace(bt, buy_fee_pct=bt.buy_fee_pct * stress,
                     sell_fee_pct=bt.sell_fee_pct * stress,
                     slippage_pct=bt.slippage_pct * stress)
    costly_matrix, _ = variant_returns(df, case["strategy"], case["param_grid"], costly)
    required = rules["dsr_trials_required"]
    _, _, _, _, _, costly_dsr = _dsr_table(costly_matrix, [required])
    _, _, _, costly_wf, costly_bench = _walk(df, case, costly)
    null_variance = 1 / len(matrix)          # sebaran Sharpe murni akibat panjang data
    wide = _dsr_table(matrix, [required], null_variance)[-1]
    excess = (wf_ret - hold_ret).to_numpy()
    ex_skew, ex_kurtosis = stats.skew_kurtosis(excess)
    wf_skew, wf_kurtosis = stats.skew_kurtosis(wf_ret.to_numpy())
    info = {
        "dsr_biaya_x": costly_dsr[required],
        "wf_sharpe_biaya_x": costly_wf["sharpe"],
        "bh_sharpe_biaya_x": costly_bench["sharpe"],
        "dsr_sebaran_lebar": wide[required],
        "psr_selisih_vs_bh": stats.probabilistic_sharpe(
            stats.sharpe_per_bar(excess), 0.0, len(excess), ex_skew, ex_kurtosis),
        "psr_wf_di_atas_nol": stats.probabilistic_sharpe(
            stats.sharpe_per_bar(wf_ret), 0.0, len(wf_ret), wf_skew, wf_kurtosis),
        "wf_jendela": windows,
    }
    criteria = [
        (f"DSR (percobaan = {required}) >= {rules['dsr_threshold']:.2f}",
         f"{dsr[required]:.3f}", dsr[required] >= rules["dsr_threshold"]),
        (f"PBO <= {rules['pbo_threshold']:.2f}", f"{pbo.pbo:.3f}",
         pbo.pbo <= rules["pbo_threshold"]),
        ("Sharpe walk-forward > Buy & Hold",
         f"{wf_metrics['sharpe']:.3f} vs {bench['sharpe']:.3f}",
         wf_metrics["sharpe"] > bench["sharpe"]),
    ]
    variants = pd.DataFrame(params).assign(sharpe_tahunan=sharpes * annual)
    variants["total_return"] = [
        compute_metrics(matrix[c], None, bt.periods_per_year)["total_return"] for c in matrix]
    return Validation(
        name=name, fingerprint=found, start=matrix.index[0], end=matrix.index[-1],
        variants=variants,
        best={**params[best], "sharpe_tahunan": float(sharpes[best] * annual),
              "skew": skew, "kurtosis": kurtosis, "bar": len(matrix),
              "var_sharpe_tahunan": variance * bt.periods_per_year},
        dsr=dsr, dsr_required=required, pbo=pbo,
        walkforward={"strategi": wf_metrics, "buy_hold": bench,
                     "mulai": wf_ret.index[0], "akhir": wf_ret.index[-1]},
        info=info, criteria=criteria, unverified=cost_model(ins).unverified,
        periods_per_year=bt.periods_per_year)


def _params(row: dict) -> str:
    """Parameter variasi apa pun, mis. 'fast=10, slow=100'."""
    skip = {"sharpe_tahunan", "total_return", "skew", "kurtosis", "bar", "var_sharpe_tahunan"}
    return ", ".join(f"{k}={value}" for k, value in row.items() if k not in skip)


def report(v: Validation, rules: dict, recorded_variants: int) -> str:
    """Laporan teks (markdown)."""
    annual = np.sqrt(v.periods_per_year)
    s, b = v.walkforward["strategi"], v.walkforward["buy_hold"]
    lines = [
        f"# Laporan riset: {v.name}", "",
        (f"Data beku {v.start:%Y-%m-%d} s/d {v.end:%Y-%m-%d} ({v.best['bar']} bar dinilai), "
        f"sidik jari `{v.fingerprint}`."), "",
        f"## Putusan: {'LOLOS' if v.passed else 'TIDAK LOLOS'} uji overfitting", "",
        "| Kriteria (ditetapkan sebelum hasil) | Hasil | Lolos |", "|---|---|---|",
        *[f"| {n} | {value} | {'ya' if ok else 'TIDAK'} |" for n, value, ok in v.criteria],
        "", "## Deflated Sharpe Ratio",
        (f"Variasi terbaik: {_params(v.best)}; Sharpe {v.best['sharpe_tahunan']:.2f} per "
         f"tahun, skew {v.best['skew']:.2f}, kurtosis {v.best['kurtosis']:.1f}."), "",
        "| Jumlah percobaan | DSR |", "|---|---|",
        *[f"| {n} | {value:.3f} |" for n, value in v.dsr.items()],
        "", "## PBO",
        (f"PBO {v.pbo.pbo:.3f} dari {v.pbo.n_splits:,} pembagian ({len(v.variants)} variasi). "
        f"Pilihan terbaik: Sharpe median {v.pbo.median_is * annual:.2f} dalam sampel, "
        f"{v.pbo.median_oos * annual:.2f} di luar sampel; rugi di luar sampel "
        f"{v.pbo.prob_loss:.1%}; kemiringan {v.pbo.slope:.2f}."),
        "", (f"## Walk-forward {v.walkforward['mulai']:%Y-%m-%d} s/d "
        f"{v.walkforward['akhir']:%Y-%m-%d}"), "",
        "| | Total return | Sharpe | Max drawdown |", "|---|---|---|---|",
        f"| Strategi | {s['total_return']:.1%} | {s['sharpe']:.3f} | {s['max_drawdown']:.1%} |",
        (f"| Buy & Hold | {b['total_return']:.1%} | {b['sharpe']:.3f} | "
        f"{b['max_drawdown']:.1%} |"),
        "", "## Tambahan (tidak menentukan kelulusan)", "",
        (f"- Biaya x{rules['cost_stress_multiplier']:g}: DSR {v.info['dsr_biaya_x']:.3f}; "
        f"Sharpe walk-forward {v.info['wf_sharpe_biaya_x']:.3f} vs Buy & Hold "
        f"{v.info['bh_sharpe_biaya_x']:.3f}."),
        (f"- DSR bila sebaran antar percobaan selebar ketidakpastian data: "
        f"{v.info['dsr_sebaran_lebar']:.3f}."),
        f"- Keyakinan Sharpe walk-forward di atas nol: {v.info['psr_wf_di_atas_nol']:.3f}.",
        (f"- Keyakinan strategi lebih baik daripada Buy & Hold (selisih return harian): "
        f"{v.info['psr_selisih_vs_bh']:.3f}."),
        "", "## Semua variasi", "", "| Parameter | Sharpe | Total return |", "|---|---|---|",
        *[f"| {_params(r)} | {r['sharpe_tahunan']:.2f} | {r['total_return']:.1%} |"
          for r in v.variants.to_dict("records")],
        "", "## Batasan", "",
        f"- Biaya belum diverifikasi: {', '.join(v.unverified) or 'tidak ada'}.",
        (f"- Variasi strategi ini yang tercatat di pencatat: {recorded_variants} (pencatatan "
        "baru dimulai 28 Nov 2026; percobaan sebelumnya tidak tercatat)."),
        ("- Sebaran Sharpe diukur dari variasi bertetangga yang sangat berkorelasi, sehingga "
        "DSR utama cenderung optimis."),
        "- Satu aset dan satu periode. Hasil backtest bukan jaminan; bukan nasihat keuangan.",
    ]
    return "\n".join(lines) + "\n"
