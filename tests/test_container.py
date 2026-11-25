# SPDX-License-Identifier: GPL-3.0-or-later
"""The prerequisites image is pinned, complete and documented.

No Docker daemon is needed: the checks read the Dockerfile and the doc.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "container" / "Dockerfile"
DOC = REPO / "docs" / "build-and-test.md"

HEX64 = re.compile(r"sha256:[0-9a-f]{64}")
# The doc uses the Debian short name; the package that installs it is
# libexpat1-dev. Everything else is named identically.
ALIASES = {"libexpat-dev": "libexpat1-dev"}


def section1(text):
    start = text.index("## 1. Packages")
    end = text.index("## 2. Sources")
    return text[start:end]


def ubuntu_packages(text):
    """Package names from the Ubuntu apt-get block in section 1."""
    block = re.search(r"apt-get install -y (.*?)```", section1(text), re.S)
    assert block, "no Ubuntu apt-get block in section 1"
    raw = block.group(1).replace("\\\n", " ").replace("\\", " ")
    return [ALIASES.get(p, p) for p in raw.split()]


@pytest.fixture(scope="module")
def dockerfile():
    if not DOCKERFILE.is_file():
        pytest.skip("container/Dockerfile is absent")
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc():
    if not DOC.is_file():
        pytest.skip("docs/build-and-test.md is absent")
    return DOC.read_text(encoding="utf-8")


def test_base_is_pinned(dockerfile):
    first = next(line for line in dockerfile.splitlines() if line.strip())
    assert first.startswith("FROM ubuntu:24.04@sha256:"), first
    assert HEX64.fullmatch(first.split("@", 1)[1].split()[0])


def test_every_section1_package_is_installed(dockerfile, doc):
    body = dockerfile.replace("\\\n", " ")
    missing = [p for p in ubuntu_packages(doc) if p not in body.split()]
    assert not missing, f"not installed: {missing}"


def test_no_repository_copy(dockerfile):
    commands = [
        line.split()[0].upper()
        for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "COPY" not in commands and "ADD" not in commands
    assert "/src" not in dockerfile and "RISC-VInjection" not in dockerfile


def test_doc_records_image_id(dockerfile, doc):
    digest = next(
        line.split("@", 1)[1].split()[0]
        for line in dockerfile.splitlines()
        if line.startswith("FROM ")
    )
    assert digest in doc
    ids = HEX64.findall(doc)
    assert ids, "no sha256 image id in the doc"
    assert "xattn-prereqs:24.04" in doc
