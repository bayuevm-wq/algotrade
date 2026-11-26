"""Pemeriksa rahasia untuk repo publik. Dipakai pre-commit dan tes.

Mendeteksi: seed phrase (BIP39), private key (EVM, Solana, Bitcoin, PEM), API key/token,
dan file yang tidak boleh masuk git (.env, wallet, data, laporan).

Pakai:
  python scripts/check_secrets.py FILE...    # file tertentu (dipanggil pre-commit)
  python scripts/check_secrets.py --all      # semua file ter-track
  python scripts/check_secrets.py --history  # seluruh riwayat git

Nilai rahasianya TIDAK pernah dicetak. Untuk salah deteksi yang sudah diperiksa, tambahkan
komentar `pragma: allowlist secret` di baris tersebut.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath

ALLOW = "pragma: allowlist secret"
SEED_MIN_WORDS = 12
SKIP_CONTENT = {"uv.lock"}                  # berisi ribuan hash paket
CONFIG_SUFFIXES = {".yaml", ".yml", ".toml", ".ini", ".cfg", ".json", ".txt", ".properties",
                   ".ps1", ".sh", ".bat", ".cmd", ""}

FORBIDDEN_PATHS = [
    ("file .env", r"(^|/)\.env(\.(?!example$)[^/]*)?$|(^|/)[^/]+\.env$"),
    ("file kunci", r"\.(pem|key|p12|pfx)$|(^|/)id_(rsa|ed25519|ecdsa)$"),
    ("file wallet", r"(^|/)[^/]*(wallet|keystore|keypair|mnemonic|seed)[^/]*\.(json|txt|dat)$"),
    ("file data/laporan", r"^(data|reports)/(?!\.gitkeep$)"),
]

BASE58 = "1-9A-HJ-NP-Za-km-z"
PATTERNS = [
    ("private key PEM", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("private key 64 hex (EVM/Bitcoin)",
     r"(?<![0-9A-Za-z])(0x)?[0-9a-fA-F]{64}(?![0-9A-Za-z])"),
    ("private key Solana (base58)", rf"(?<![0-9A-Za-z])[{BASE58}]{{85,90}}(?![0-9A-Za-z])"),
    ("private key Bitcoin (WIF)", rf"(?<![0-9A-Za-z])[5KL][{BASE58}]{{50,51}}(?![0-9A-Za-z])"),
    ("kunci induk wallet (xprv)", rf"(?<![0-9A-Za-z])[xyzt]prv[{BASE58}]{{100,}}"),
    ("keypair Solana (array 64 byte)", r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]"),
    ("AWS access key", r"(?<![0-9A-Z])AKIA[0-9A-Z]{16}(?![0-9A-Z])"),
    ("token GitHub", r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}"),
    ("API key sk-", r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    ("token bot Telegram", r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
]

SECRET_NAME = (r"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|client[_-]?secret|api[_-]?pass"
               r"(?:word|phrase)?|passphrase|password|private[_-]?key|mnemonic|seed[_-]?phrase|"
               r"access[_-]?token|auth[_-]?token|bot[_-]?token|[A-Z]+_SECRET|[A-Z]+_TOKEN)")
# nama = "nilai literal"
QUOTED = re.compile(rf"(?i){SECRET_NAME}[\"']?\s*[:=]\s*[\"']([^\"'\s]{{8,}})[\"']")
# NAMA=nilai tanpa kutip (hanya untuk file konfigurasi/skrip)
BARE = re.compile(rf"(?i){SECRET_NAME}[\"']?\s*[:=]\s*([A-Za-z0-9+/_\-!@#%^&*.=]{{8,}})\s*(?:#.*)?$")
PLACEHOLDER = re.compile(r"(?i)^(\$|<|\{|%)|your|xxx|changeme|example|contoh|dummy|isi[_-]")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}  [{self.rule}]"


@lru_cache
def bip39_words() -> frozenset[str]:
    from mnemonic import Mnemonic

    return frozenset(Mnemonic("english").wordlist)


def find_seed_phrases(text: str) -> list[int]:
    """Nomor baris awal setiap deretan >= 12 kata BIP39 (boleh bernomor / dipisah koma)."""
    words = bip39_words()
    lines, run, start, previous_end = [], 0, 0, 0
    for match in re.finditer(r"[A-Za-z]+", text):
        between = text[previous_end:match.start()]
        previous_end = match.end()
        joined = re.fullmatch(r"[\s\d,.;:|\"'\[\]()\-_=*#]*", between) is not None
        if match.group().lower() not in words:
            run = 0
            continue
        if run == 0 or not joined:
            run, start = 0, match.start()
        run += 1
        if run == SEED_MIN_WORDS:
            lines.append(text.count("\n", 0, start) + 1)
    return lines


def check_path(path: str) -> list[Finding]:
    return [Finding(path, 0, rule) for rule, pattern in FORBIDDEN_PATHS
            if re.search(pattern, path, re.IGNORECASE)]


def check_text(path: str, text: str) -> list[Finding]:
    all_lines = text.splitlines()

    def allowed(number: int) -> bool:
        return 0 < number <= len(all_lines) and ALLOW in all_lines[number - 1]

    found = []
    for rule, pattern in PATTERNS:
        for match in re.finditer(pattern, text):
            number = text.count("\n", 0, match.start()) + 1
            found.append(Finding(path, number, rule))
    config_like = PurePosixPath(path).suffix.lower() in CONFIG_SUFFIXES or ".env" in path
    for number, line in enumerate(all_lines, 1):
        matches = list(QUOTED.finditer(line))
        if config_like:
            matches += list(BARE.finditer(line))
        if any(not PLACEHOLDER.search(m[1]) for m in matches):
            found.append(Finding(path, number, "nilai rahasia ditulis langsung"))
    found += [Finding(path, n, "seed phrase") for n in find_seed_phrases(text)]
    return sorted({f for f in found if not allowed(f.line)}, key=lambda f: (f.line, f.rule))


def check_file(path: str, content: bytes) -> list[Finding]:
    path = path.replace("\\", "/")
    found = check_path(path)
    if path in SKIP_CONTENT:
        return found
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):     # UTF-16 (bawaan PowerShell 5.1)
        return found + check_text(path, content.decode("utf-16", errors="replace"))
    if b"\0" in content:                                    # biner
        return found
    return found + check_text(path, content.decode("utf-8-sig", errors="replace"))


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def scan_paths(paths: list[str]) -> list[Finding]:
    found = []
    for path in paths:
        try:
            with open(path, "rb") as f:
                content = f.read()
        except (FileNotFoundError, IsADirectoryError):
            continue
        found += check_file(path, content)
    return found


def scan_tracked() -> list[Finding]:
    return scan_paths([p for p in _git("ls-files", "-z").decode().split("\0") if p])


def scan_history() -> list[Finding]:
    """Periksa setiap versi file di semua commit."""
    found, seen = [], set()
    for commit in _git("rev-list", "--all").decode().split():
        for entry in _git("ls-tree", "-r", "-z", commit).decode().split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            blob = meta.split()[2]
            if (blob, path) in seen:
                continue
            seen.add((blob, path))
            found += [Finding(f"{commit[:7]}:{f.path}", f.line, f.rule)
                      for f in check_file(path, _git("cat-file", "blob", blob))]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pemeriksa rahasia")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--all", action="store_true", help="semua file ter-track")
    parser.add_argument("--history", action="store_true", help="seluruh riwayat git")
    args = parser.parse_args(argv)
    if args.history:
        found = scan_history()
    elif args.all:
        found = scan_tracked()
    else:
        found = scan_paths(args.files)
    if not found:
        return 0
    print("DIBLOKIR: kemungkinan rahasia atau file terlarang ditemukan.", file=sys.stderr)
    for finding in found:
        print(f"  {finding}", file=sys.stderr)
    print("Hapus rahasianya (pakai environment variable). Bila sudah terlanjur ter-commit "
          "atau ter-push, GANTI kuncinya.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
