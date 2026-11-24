# SPDX-License-Identifier: GPL-3.0-or-later
"""The build writes out/BUILD-INFO, and `make check` copies it to artifacts/.

A result that does not name the sources it came from cannot be checked.  These
tests run `scripts/build.sh info`, which writes the record and builds nothing.
"""

import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
SUBMODULES = ["binutils", "gcc", "newlib", "qemu", "spike"]


def pins():
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "HEAD", *SUBMODULES],
        check=True, capture_output=True, text=True,
    ).stdout
    return {line.split("\t")[1]: line.split()[2] for line in out.splitlines()}


def build_info(tmp_path):
    env = dict(os.environ, XATTN_OUT=str(tmp_path))
    r = subprocess.run(
        ["bash", str(REPO / "scripts" / "build.sh"), "info"],
        cwd=str(REPO), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return (tmp_path / "BUILD-INFO").read_text(encoding="utf-8")


def test_build_info_names_the_five_pins(tmp_path):
    text = build_info(tmp_path)
    for name, sha in pins().items():
        assert sha in text, f"{name} pin {sha} missing from BUILD-INFO"
    for field in ("date:", "host:", "host cc:", "python:", "numpy:", "outputs:"):
        assert field in text, f"{field} missing from BUILD-INFO"


def test_build_info_does_not_build(tmp_path):
    """`info` must not touch build/ or out/toolchain: it only records."""
    before = sorted(p.name for p in (REPO / "build").glob("*")) if (
        REPO / "build"
    ).is_dir() else []
    build_info(tmp_path)
    after = sorted(p.name for p in (REPO / "build").glob("*")) if (
        REPO / "build"
    ).is_dir() else []
    assert before == after


def test_check_copies_the_record_into_artifacts():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "check: check-info" in makefile, "make check does not copy BUILD-INFO"
    assert "artifacts/BUILD-INFO" in makefile
    assert "artifacts/BUILD-INFO" in (REPO / ".gitignore").read_text(
        encoding="utf-8"
    ), "a build record must not be committed"
