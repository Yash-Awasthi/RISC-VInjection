# SPDX-License-Identifier: GPL-3.0-or-later
"""The pins are recorded in versions.env and checked before a build.

`versions.env` is the record; the superproject is the truth.  These tests keep
the two together: a submodule pointer moved without editing the file (or the
reverse) fails here, before any toolchain is built.
"""

import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
ENV = REPO / "versions.env"
CHECK = REPO / "scripts" / "check-pins.sh"
SUBMODULES = ["binutils", "gcc", "newlib", "qemu", "spike"]


def git(*args):
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def read_env(path=ENV):
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        pins[key.strip()] = value.strip()
    return pins


def pinned_by_superproject():
    out = git("ls-tree", "HEAD", *SUBMODULES)
    return {line.split("\t")[1]: line.split()[2] for line in out.splitlines()}


def run_check(env_file=None):
    env = dict(os.environ)
    if env_file is not None:
        env["VERSIONS_FILE"] = str(env_file)
    return subprocess.run(
        ["bash", str(CHECK)], capture_output=True, text=True, env=env
    )


def test_versions_env_names_the_pinned_commits():
    pins = read_env()
    recorded = pinned_by_superproject()
    assert len(recorded) == len(SUBMODULES)
    for name, sha in recorded.items():
        key = name.upper() + "_SHA"
        assert pins.get(key) == sha, f"versions.env {key} is not the pinned {name}"
        assert len(sha) == 40, f"{key} is not a full 40-character SHA"


def test_check_pins_agrees_with_the_superproject():
    r = run_check()
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == len(SUBMODULES), r.stdout
    for name in SUBMODULES:
        assert any(l.startswith(name) for l in lines), f"{name} missing from {lines}"


def test_a_drifted_versions_env_is_refused(tmp_path):
    pins = read_env()
    pins["SPIKE_SHA"] = "0" * 40
    drifted = tmp_path / "versions.env"
    drifted.write_text(
        "".join(f"{k}={v}\n" for k, v in pins.items()), encoding="utf-8"
    )
    r = run_check(drifted)
    assert r.returncode == 1, r.stdout
    assert "SPIKE_SHA" in r.stderr
    assert "the superproject pins" in r.stderr


def test_a_missing_key_is_refused(tmp_path):
    pins = read_env()
    pins.pop("GCC_SHA")
    partial = tmp_path / "versions.env"
    partial.write_text(
        "".join(f"{k}={v}\n" for k, v in pins.items()), encoding="utf-8"
    )
    r = run_check(partial)
    assert r.returncode == 1, r.stdout
    assert "GCC_SHA" in r.stderr


def test_gitmodules_pins_commits_not_branches():
    """A `branch =` key only feeds `git submodule update --remote`, which would
    move a submodule to a branch tip and stop patches/ from applying."""
    text = (REPO / ".gitmodules").read_text(encoding="utf-8")
    asserts = [l.strip() for l in text.splitlines() if l.strip().startswith("branch")]
    assert asserts == [], asserts
    urls = [
        l.split(" = ", 1)[1].strip()
        for l in text.splitlines()
        if l.strip().startswith("url")
    ]
    assert len(urls) == len(SUBMODULES), urls
    for url in urls:
        assert url.startswith("https://"), url


def test_newlib_remote_is_the_canonical_source():
    url = subprocess.run(
        ["git", "-C", str(REPO), "config", "-f", ".gitmodules",
         "--get", "submodule.newlib.url"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert url == "https://sourceware.org/git/newlib-cygwin.git", url
