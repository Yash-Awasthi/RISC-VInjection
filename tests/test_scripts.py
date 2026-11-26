# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/*.sh: known set, strict mode, no swallowed failure at the end."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
KNOWN = {
    "artifacts.sh", "attncc.sh", "build.sh", "check-artifacts.sh", "check-build-info.sh",
    "check-pins.sh", "check-summary.sh", "diagnose.sh", "patches.sh",
    "sanitize.sh", "setup.sh", "xattn.sh",
}
STRICT = re.compile(r"^set -euo pipefail$", re.M)
EXIT_STATUS = re.compile(r"\bexit\s+(\$[\w{}]+|[1-9]\d*|0)\b")
SWALLOW = re.compile(r"\|\|\s*(true|:|exit\s+0)\s*$")

BASH = shutil.which("bash")
TIMEOUT = 60
NO_ARG_SAFE = {"check-pins.sh": "binutils", "check-build-info.sh": "BUILD-INFO"}
NO_ARG_UNSAFE = {
    "artifacts.sh": "rewrites artifacts/ with the toolchain",
    "setup.sh": "installs packages and then builds",
}


def last_code_line(text):
    code = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    return code[-1]


def run(script, *args):
    assert BASH, "bash is not on PATH; the scripts need it"
    return subprocess.run(
        [BASH, str(SCRIPTS / script), *args],
        capture_output=True, text=True, errors="replace", timeout=TIMEOUT,
    )


def output(cp):
    return cp.stdout + cp.stderr


def test_script_set_is_deliberate():
    files = sorted(SCRIPTS.glob("*.sh"))
    assert len(files) == len(set(files)) == 12
    assert {p.name for p in files} == KNOWN


def test_scripts_are_strict():
    for path in sorted(SCRIPTS.glob("*.sh")):
        assert STRICT.search(path.read_text(encoding="utf-8")), path.name


# Under `set -e` a trailing `exit 0` cannot mask a failure: the failing
# command already aborted the script, so only a clean run reaches that line.
def test_last_line_preserves_failure():
    for path in sorted(SCRIPTS.glob("*.sh")):
        line = last_code_line(path.read_text(encoding="utf-8"))
        assert not SWALLOW.search(line), f"{path.name}: {line!r}"
        if "||" in line:
            assert EXIT_STATUS.search(line.split("||", 1)[1]), \
                f"{path.name}: {line!r}"
        elif re.match(r"exit\b", line):
            assert EXIT_STATUS.search(line), f"{path.name}: {line!r}"


def test_help_prints_usage_and_exits_zero():
    for path in sorted(SCRIPTS.glob("*.sh")):
        cp = run(path.name, "--help")
        assert cp.returncode == 0, (path.name, output(cp))
        text = output(cp)
        assert path.name in text and "env:" in text, (path.name, text)


def test_unknown_flag_prints_it_and_exits_two():
    for path in sorted(SCRIPTS.glob("*.sh")):
        cp = run(path.name, "--bogus")
        assert cp.returncode == 2, (path.name, cp.returncode, output(cp))
        assert "--bogus" in output(cp), (path.name, output(cp))


# Only the read-only, toolchain-free scripts: no arguments is a complete,
# cheap invocation.  The other two are skipped rather than executed.
def test_no_args_still_dispatches():
    for name, needle in NO_ARG_SAFE.items():
        cp = run(name)
        assert cp.returncode in (0, 1), (name, cp.returncode, output(cp))
        assert needle in output(cp), (name, output(cp))


@pytest.mark.parametrize("name", sorted(NO_ARG_UNSAFE))
def test_no_args_skipped_when_it_would_build_or_write(name):
    pytest.skip(f"{name} is not run with no arguments: {NO_ARG_UNSAFE[name]}")
