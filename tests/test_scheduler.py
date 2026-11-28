"""Tes peluncur Task Scheduler (khusus Windows)."""

import runpy
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
launcher = runpy.run_path(str(SCRIPTS / "run_hidden.pyw"), run_name="peluncur")


@pytest.mark.parametrize("code", [0, 1, 7])
def test_exit_code_is_forwarded(code):
    assert launcher["run"]([sys.executable, "-c", f"raise SystemExit({code})"]) == code


def test_command_passes_arguments_to_update_script():
    cmd = launcher["command"](["--market", "idx"])
    assert cmd[0] == "powershell.exe" and cmd[-2:] == ["--market", "idx"]
    assert Path(cmd[-3]) == SCRIPTS / "data_update.ps1"
    text = (SCRIPTS / "data_update.ps1").read_text(encoding="utf-8")
    assert "data update @args" in text and "exit $code" in text
