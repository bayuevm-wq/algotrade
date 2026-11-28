"""Tes pengaman repo publik.

Semua "rahasia" palsu dirakit saat tes berjalan, supaya file ini sendiri tidak diblokir.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts/check_secrets.py")
secrets_check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = secrets_check
spec.loader.exec_module(secrets_check)

WORDS = sorted(secrets_check.bip39_words())[:24]
HEX64 = "4f3c" * 16
needs_git = pytest.mark.skipif(not (ROOT / ".git").exists() or shutil.which("git") is None,
                               reason="bukan repo git")


def rules(path, text):
    return {f.rule for f in secrets_check.check_file(path, text.encode())}


@pytest.mark.parametrize("text", [
    " ".join(WORDS[:12]),
    ", ".join(WORDS),
    "\n".join(f"{i}. {w}" for i, w in enumerate(WORDS[:12], 1)),
    'phrase = "' + " ".join(WORDS[:12]).upper() + '"',
])
def test_detects_seed_phrase(text):
    assert "seed phrase" in rules("catatan.md", text)


def test_ordinary_text_is_not_a_seed_phrase():
    assert rules("a.md", " ".join(WORDS[:11])) == set()
    prose = "Strategi harus mengalahkan benchmark pasarnya secara out of sample setelah biaya."
    assert rules("a.md", prose) == set()


@pytest.mark.parametrize("text", [
    "0x" + HEX64,
    HEX64,
    "2Ana" * 22,                                    # Solana base58, 88 karakter
    "K" + "wD3n" * 12 + "abc",                      # WIF, 52 karakter
    "-----BEGIN " + "RSA PRIVATE KEY-----",
    "[" + ",".join(["17"] * 64) + "]",
    "AKIA" + "ABCD1234" * 2,
    "ghp_" + "a1B2" * 9,
    "api_key" + ' = "' + "q8Zt" * 6 + '"',
])
def test_detects_keys(text):
    assert rules("src/x.py", f"x = 1\n{text}\n")


@pytest.mark.parametrize("name", ["BINANCE_API_SECRET", "OKX_PASSPHRASE", "TELEGRAM_BOT_TOKEN"])
def test_detects_unquoted_value_in_config_files(name):
    assert rules("config/a.yaml", f"{name}: " + "zX9q" * 5)
    assert rules("run.ps1", f"$env:{name}=" + "zX9q" * 5)


@pytest.mark.parametrize("text", [
    'api_key = os.environ["OKX_API_KEY"]',
    "# BROKER_API_KEY=",
    'api_key = "${OKX_API_KEY}"',
    'api_key: "<your-api-key>"',
    'address: "0x' + "a1" * 20 + '"',               # alamat kontrak publik (40 hex)
])
def test_safe_lines_pass(text):
    assert rules("config/a.yaml", text) == set()


def test_utf16_file_is_scanned():
    assert secrets_check.check_file("a.txt", ("0x" + HEX64).encode("utf-16"))


def test_allowlist_comment():
    assert rules("a.py", f'h = "{HEX64}"  # pragma: allowlist secret') == set()


def test_finding_never_prints_the_secret(tmp_path, capsys):
    path = tmp_path / "bocor.py"
    path.write_text("k = '0x" + HEX64 + "'\n", encoding="utf-8")
    assert secrets_check.main([str(path)]) == 1
    assert HEX64 not in capsys.readouterr().err


@pytest.mark.parametrize("path", [
    ".env", ".env.local", "config/prod.env", "my-wallet.json", "bot_keypair.json",
    "certs/server.pem", "data/market/x.parquet", "reports/compare.csv",
])
def test_forbidden_paths(path):
    assert secrets_check.check_path(path)


@pytest.mark.parametrize("path", [".env.example", "data/.gitkeep", "src/algotrade/data/cex.py"])
def test_allowed_paths(path):
    assert not secrets_check.check_path(path)


def git(*args):
    return subprocess.run(["git", *args], check=False, cwd=ROOT, capture_output=True, text=True)


@needs_git
def test_env_never_tracked_now_or_in_history():
    tracked = git("ls-files").stdout.splitlines()
    history = git("log", "--all", "--pretty=format:", "--name-only").stdout.splitlines()
    bad = [p for p in {*tracked, *history} if p and any(
        f.rule == "file .env" for f in secrets_check.check_path(p))]
    assert bad == []


@needs_git
@pytest.mark.parametrize("path", [".env", ".env.local", ".env.production", "config/prod.env",
                                  "wallet.json", "bot.pem", "data/market.duckdb",
                                  ".claude/settings.local.json", "data/experiments.duckdb"])
def test_sensitive_files_are_ignored_by_git(path):
    assert git("check-ignore", "--no-index", "-q", path).returncode == 0


@needs_git
def test_env_example_is_not_ignored_and_has_no_values():
    assert git("check-ignore", "--no-index", "-q", ".env.example").returncode == 1
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert value.strip().lower() in ("", "true", "false"), name


@needs_git
def test_tracked_files_contain_no_secrets(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert [str(f) for f in secrets_check.scan_tracked()] == []
