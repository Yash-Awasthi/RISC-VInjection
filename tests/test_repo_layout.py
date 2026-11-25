# SPDX-License-Identifier: GPL-3.0-or-later
"""Governance: .github/CODEOWNERS and the review checklist for attn_core.h.

The checklist is only worth having if its commands still run, so these tests
read docs/review.md, look up every `make` target it cites in the Makefile and
every scripts/<name> it cites on disk.  No toolchain is needed.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
CODEOWNERS = REPO / ".github" / "CODEOWNERS"
REVIEW = REPO / "docs" / "review.md"
MAKEFILE = REPO / "Makefile"

OWNER = re.compile(r"@[A-Za-z0-9_-]+")
BACKTICK = re.compile(r"`([^`]+)`")


def rules():
    """(pattern, owners) for every rule line, in file order."""
    out = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        out.append((fields[0], fields[1:]))
    return out


def directory_rule(name):
    """Owners of the explicit rule for one directory, or None.

    The rules here are plain paths, so a rule for a directory is the one
    whose pattern is that directory with its slashes trimmed.
    """
    want = name.strip("/")
    for pattern, owners in rules():
        if pattern == "*":
            continue
        if pattern.strip("/") == want:
            return owners
    return None


def test_codeowners_is_present():
    assert CODEOWNERS.is_file(), ".github/CODEOWNERS is missing"


def test_codeowners_has_a_default_rule_with_an_owner():
    defaults = [owners for pattern, owners in rules() if pattern == "*"]
    assert defaults, "no default * rule"
    assert defaults[0], "the default * rule names no owner"
    assert any(OWNER.fullmatch(o) for o in defaults[0]), defaults[0]


def test_codeowners_gates_patches_include_and_scripts():
    for name in ("patches/", "include/", "scripts/"):
        owners = directory_rule(name)
        assert owners, f"no explicit CODEOWNERS rule for /{name}"
        assert any(OWNER.fullmatch(o) for o in owners), \
            f"the /{name} rule has no @handle owner: {owners}"


def review_text():
    assert REVIEW.is_file(), "docs/review.md is missing"
    return REVIEW.read_text(encoding="utf-8")


def test_review_covers_the_header_its_spec_and_the_vectors():
    text = review_text()
    for needle in ("include/attn_core.h", "docs/spec.md", "tests/vectors"):
        assert needle in text, f"docs/review.md never mentions {needle}"


def test_review_covers_the_three_executions():
    low = review_text().lower()
    for word in ("spike", "qemu"):
        assert word in low, f"docs/review.md never mentions {word}"
    assert "libgcc" in low or "host" in low, \
        "docs/review.md never mentions the libgcc copy or the host"


def makefile_targets():
    """Every target the Makefile defines, including .PHONY names."""
    targets = set()
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if not line or line[0] in "\t#" or line.lstrip().startswith("#"):
            continue
        if line.startswith(".PHONY:"):
            targets.update(line.split(":", 1)[1].split())
            continue
        m = re.match(r"([A-Za-z0-9_.%-]+)\s*:(?!=)", line)
        if m:
            targets.add(m.group(1))
    return targets


def test_review_make_commands_are_real_targets():
    targets = makefile_targets()
    cited = [c.strip() for c in BACKTICK.findall(review_text())
             if c.strip().startswith("make ")]
    assert cited, "docs/review.md cites no make command"
    for command in cited:
        assert command.split()[1] in targets, f"{command} is not a Makefile target"


def test_review_scripts_exist():
    for command in BACKTICK.findall(review_text()):
        for word in command.split():
            word = word.strip("\"'(),;")
            if word.startswith("scripts/"):
                assert (REPO / word).exists(), f"{word} does not exist"
