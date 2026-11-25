# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/xattn.sh: remove leaves a pristine tree, and a second remove fails.

The plan's invariant: after `scripts/xattn.sh remove` a difference in
`git -C <sub> status --porcelain` is a bug; a second remove must fail
instead of silently succeeding over one.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMPONENTS = ["binutils", "gcc", "spike", "qemu"]


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=test",
                           "-c", "user.email=test@example.invalid",
                           "-C", str(root), *args],
                          capture_output=True, text=True)


def xattn(root, *args):
    return subprocess.run(["bash", str(root / "scripts" / "xattn.sh"), *args],
                          capture_output=True, text=True, cwd=root)


def pin_of(root, c):
    fields = git(root, "ls-files", "-s", "--", c).stdout.split()
    assert fields[0] == "160000", fields
    return fields[1]


@pytest.fixture
def scratch(tmp_path_factory):
    """Four submodules, each on branch xattn one commit ahead of its pin."""
    root = tmp_path_factory.mktemp("scratch")
    shutil.copytree(REPO / "scripts", root / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert git(root, "init", "-q").returncode == 0
    for c in COMPONENTS:
        sub = root / c
        sub.mkdir()
        (sub / "upstream.txt").write_text(c + " upstream\n")
        assert git(sub, "init", "-q").returncode == 0
        # No CRLF rewriting: a stat-only "M" is not a leaked change.
        assert git(sub, "config", "core.autocrlf", "false").returncode == 0
        assert git(sub, "add", "-A").returncode == 0
        assert git(sub, "commit", "-qm", "upstream").returncode == 0
        pin = git(sub, "rev-parse", "HEAD").stdout.strip()
        assert git(sub, "checkout", "-q", "-B", "xattn").returncode == 0
        (sub / "attn.txt").write_text("attn\n")
        assert git(sub, "add", "-A").returncode == 0
        assert git(sub, "commit", "-qm", "attn").returncode == 0
        # The superproject records the pin; the worktree sits on the tip.
        assert git(root, "update-index", "--add", "--cacheinfo",
                   "160000,%s,%s" % (pin, c)).returncode == 0
    return root


def test_remove_leaves_a_clean_tree(scratch):
    r = xattn(scratch, "remove", "--no-rebuild")
    assert r.returncode == 0, r.stderr
    for c in COMPONENTS:
        assert "%s: upstream " % c in r.stdout
        assert git(scratch / c, "rev-parse", "HEAD").stdout.strip() \
            == pin_of(scratch, c)
        status = git(scratch / c, "status", "--porcelain").stdout
        assert status == "", "%s dirty after remove:\n%s" % (c, status)
        assert git(scratch / c, "rev-parse", "--verify", "xattn").returncode == 0


def test_remove_twice_fails_cleanly(scratch):
    first = xattn(scratch, "remove", "--no-rebuild")
    assert first.returncode == 0, first.stderr
    heads = {c: git(scratch / c, "rev-parse", "HEAD").stdout.strip()
             for c in COMPONENTS}
    second = xattn(scratch, "remove", "--no-rebuild")
    assert second.returncode != 0
    assert "already at the pinned upstream commit" in second.stderr
    assert "nothing to remove" in second.stderr
    for c in COMPONENTS:
        assert git(scratch / c, "rev-parse", "HEAD").stdout.strip() == heads[c]
        assert git(scratch / c, "status", "--porcelain").stdout == ""


def test_remove_refuses_a_leaked_change(scratch):
    hook = scratch / "gcc" / ".git" / "hooks" / "post-checkout"
    hook.write_bytes(b"#!/bin/sh\nprintf 'leak\\n' > leak.txt\n")
    hook.chmod(0o755)
    r = xattn(scratch, "remove", "--no-rebuild")
    assert r.returncode != 0
    assert "gcc is dirty after remove" in r.stderr
    assert "leak.txt" in r.stderr
