# SPDX-License-Identifier: GPL-3.0-or-later
"""The build writes out/BUILD-INFO, and `make check` copies it to artifacts/.

A result that does not name the sources it came from cannot be checked.  These
tests run `scripts/build.sh info`, which writes the record and builds nothing.
"""

import os
import pathlib
import re
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


def makefile_check_prereqs():
    """Prerequisites of the Makefile's check target, in order."""
    for line in (REPO / "Makefile").read_text(encoding="utf-8").splitlines():
        if line.startswith("check:"):
            return line.split(":", 1)[1].split()
    raise AssertionError("no check: target in Makefile")


def check_build_info(outdir):
    env = dict(os.environ, XATTN_OUT=str(outdir))
    return subprocess.run(
        ["bash", str(REPO / "scripts" / "check-build-info.sh")],
        cwd=str(REPO), env=env, capture_output=True, text=True,
    )


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
    assert makefile_check_prereqs()[0] == "check-build-info", "make check does not check BUILD-INFO"
    assert "artifacts/BUILD-INFO" in makefile
    assert "artifacts/BUILD-INFO" in (REPO / ".gitignore").read_text(
        encoding="utf-8"
    ), "a build record must not be committed"


def test_check_build_info_rejects_a_missing_record(tmp_path):
    r = check_build_info(tmp_path)
    assert r.returncode != 0, r.stdout
    assert "BUILD-INFO" in r.stderr


def test_check_build_info_rejects_a_record_older_than_patches(tmp_path):
    build_info(tmp_path)
    old = 946684800  # 2000-01-01, older than patches/
    os.utime(tmp_path / "BUILD-INFO", (old, old))
    r = check_build_info(tmp_path)
    assert r.returncode != 0, r.stdout
    assert "patches" in r.stderr


def test_check_build_info_rejects_a_pin_that_moved(tmp_path):
    build_info(tmp_path)
    info = tmp_path / "BUILD-INFO"
    text = info.read_text(encoding="utf-8")
    wrong = "f" * 40
    text = re.sub(r"(?m)^  gcc\s+pinned \S+", f"  gcc      pinned {wrong}", text)
    assert wrong in text, "the gcc pin line was not rewritten"
    info.write_text(text, encoding="utf-8")
    r = check_build_info(tmp_path)
    assert r.returncode != 0, r.stdout
    assert "gcc" in r.stderr


def test_check_build_info_accepts_a_fresh_record(tmp_path):
    build_info(tmp_path)
    r = check_build_info(tmp_path)
    assert r.returncode == 0, r.stderr


def test_check_build_info_is_wired_into_make_check():
    assert makefile_check_prereqs()[0] == "check-build-info"
    script = (REPO / "scripts" / "check-build-info.sh").read_bytes()
    assert script.startswith(b"#!"), "the script must be executable bash"
    assert b"\r" not in script, "no stray CR in the script"

