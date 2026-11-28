"""Jalankan data_update.ps1 tanpa jendela dan TERUSKAN kode errornya (untuk Task Scheduler).

Dijalankan dengan pythonw.exe, yang tidak membuka konsol. Argumen tambahan diteruskan ke
`algotrade data update`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("data_update.ps1")


def command(args: list[str]) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT), *args]


def run(cmd: list[str]) -> int:
    """Tunggu sampai selesai, lalu kembalikan kode keluarnya."""
    return subprocess.run(
        cmd, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).returncode


if __name__ == "__main__":
    sys.exit(run(command(sys.argv[1:])))
