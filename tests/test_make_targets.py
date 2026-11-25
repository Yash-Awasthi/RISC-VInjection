# SPDX-License-Identifier: GPL-3.0-or-later
"""The make targets that only wrap one script call.

No toolchain is needed: `make -n` prints each recipe without running it, so
these tests check the wiring, not a build.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"
MAKE = shutil.which("make") or shutil.which("gmake")

# target -> the exact command make -n must print
TARGETS = {
    "setup": "scripts/setup.sh",
    "artifacts": "scripts/artifacts.sh",
    "patches-apply": "scripts/patches.sh apply",
    "patches-export": "scripts/patches.sh export",
    "patches-remove": "scripts/patches.sh remove",
    "patches-restore": "scripts/patches.sh restore",
    "patches-check": "scripts/patches.sh check",
    "patches-status": "scripts/patches.sh status",
}

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not installed")


def dry_run(target):
    """The single command make would run for one target."""
    done = subprocess.run(
        [MAKE, "-n", target],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def phony_names():
    # .PHONY spans several lines with backslash continuations.
    text = MAKEFILE.read_text(encoding="utf-8")
    joined = text.replace("\\\r\n", " ").replace("\\\n", " ")
    names = set()
    for line in joined.splitlines():
        if line.startswith(".PHONY:"):
            names.update(line.split(":", 1)[1].split())
    return names


@pytest.mark.parametrize("target,command", sorted(TARGETS.items()))
def test_make_target_runs_its_script(target, command):
    assert dry_run(target) == command


@pytest.mark.parametrize("target,command", sorted(TARGETS.items()))
def test_make_target_script_exists(target, command):
    script = REPO / command.split()[0]
    assert script.is_file(), f"{target} runs {command} but {script} is missing"


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_make_target_is_phony(target):
    # artifacts/ is a real directory, so without .PHONY the target is up to
    # date and the script never runs.
    assert target in phony_names(), f"{target} is not in .PHONY"


def test_setup_is_exactly_the_setup_script():
    assert dry_run("setup") == "scripts/setup.sh"
