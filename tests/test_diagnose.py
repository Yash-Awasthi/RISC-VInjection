# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/diagnose.sh: the five build failures, named exactly."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "diagnose.sh"
CASES = {
    "missing-package.log": (
        5,
        "missing package",
        "install the package list in docs/build-and-test.md section 1 "
        "or run scripts/setup.sh",
    ),
    "patch-conflict.log": (
        4,
        "patch conflict",
        "rerun scripts/patches.sh apply on the pinned commit as "
        "docs/build-and-test.md section 2 says",
    ),
    "submodule-not-initialised.log": (
        4,
        "submodule not initialised",
        "run git submodule update --init gcc binutils spike qemu newlib "
        "as docs/build-and-test.md section 2 says",
    ),
    "stale-toolchain.log": (
        4,
        "stale toolchain",
        "rebuild it with scripts/build.sh and check versions.env as "
        "docs/build-and-test.md section 3 says",
    ),
    "wrong-march.log": (
        3,
        "wrong -march",
        "pass the gcc -march=rv64gc_xattn flag as docs/build-and-test.md "
        "section 5 shows",
    ),
}
BASH = shutil.which("bash")
TIMEOUT = 60


def run(*args):
    assert BASH, "bash is not on PATH; the scripts need it"
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        cwd=REPO, capture_output=True, text=True, errors="replace",
        timeout=TIMEOUT,
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_known_failure_names_file_line_and_fix(name):
    line, what, fix = CASES[name]
    rel = f"tests/data/failures/{name}"
    cp = run(rel)
    assert cp.returncode == 1, (cp.returncode, cp.stderr)
    assert cp.stdout == f"{rel}:{line}: {what}: {fix}\n"
    assert cp.stderr == ""


def test_clean_log_exits_zero(tmp_path):
    log = tmp_path / "clean-build.log"
    log.write_text(
        "== build\nall steps finished\n0 failures\n", encoding="utf-8"
    )
    arg = str(log).replace("\\", "/")
    cp = run(arg)
    assert cp.returncode == 0, (cp.returncode, cp.stderr)
    assert cp.stdout == f"no known failure in {arg}\n"
    assert cp.stderr == ""


def test_help_exits_zero():
    cp = run("--help")
    assert cp.returncode == 0
    assert "diagnose.sh" in cp.stdout
    assert "env:" in cp.stdout
    assert cp.stderr == ""


def test_missing_argument_exits_two():
    cp = run()
    assert cp.returncode == 2
    assert "diagnose.sh" in cp.stderr
    assert cp.stdout == ""


def test_unknown_option_exits_two():
    cp = run("--bogus")
    assert cp.returncode == 2
    assert "--bogus" in cp.stderr
    assert "diagnose.sh" in cp.stderr
    assert cp.stdout == ""
