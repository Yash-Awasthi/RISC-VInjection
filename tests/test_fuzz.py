# SPDX-License-Identifier: GPL-3.0-or-later
"""libFuzzer over the attn descriptors and X on the host model.

The harness is tests/host/attn_fuzz.c; the committed seed corpus lives in
tests/fuzz/corpus/ and is passed to the fuzzer unchanged, so CI reruns the
same starting point.  Skipped when clang is not on PATH.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "tests" / "host" / "attn_fuzz.c"
CORPUS = REPO / "tests" / "fuzz" / "corpus"

pytestmark = pytest.mark.skipif(
    shutil.which("clang") is None, reason="clang is not on PATH"
)


def clang_version():
    out = subprocess.run(
        ["clang", "--version"], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()[0]


def build(tmp_path):
    exe = tmp_path / "attn_fuzz"
    cmd = [
        "clang",
        "-std=c11",
        "-g",
        "-O1",
        "-fno-omit-frame-pointer",
        "-fsanitize=fuzzer,address,undefined",
        "-fno-sanitize-recover=all",
        "-I",
        str(REPO / "include"),
        str(SOURCE),
        "-lm",
        "-o",
        str(exe),
    ]
    subprocess.run(cmd, cwd=REPO, check=True, capture_output=True)
    return exe


def test_corpus_is_committed():
    seeds = sorted(CORPUS.glob("*.bin"))
    assert len(seeds) >= 8
    for seed in seeds:
        assert seed.stat().st_size >= 104
    print(f"corpus: {CORPUS} ({len(seeds)} seeds)")


def test_fuzz_campaign(tmp_path):
    exe = build(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for seed in CORPUS.glob("*.bin"):
        shutil.copy2(seed, corpus / seed.name)
    cmd = [
        str(exe),
        "-runs=20000",
        "-max_total_time=60",
        f"-artifact_prefix={artifacts}/",
        str(corpus),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    output = proc.stdout + proc.stderr
    match = re.search(r"Done (\d+) runs", output)
    runs = int(match.group(1)) if match else 0
    print(f"clang: {clang_version()}")
    print(f"runs executed: {runs}")
    print(f"corpus: {CORPUS} ({len(list(CORPUS.glob('*.bin')))} seeds)")
    crashes = sorted(artifacts.glob("crash-*"))
    timeouts = sorted(artifacts.glob("timeout-*"))
    assert proc.returncode == 0, output[-4000:]
    assert not crashes, [p.name for p in crashes]
    assert not timeouts, [p.name for p in timeouts]
    assert runs > 0, output[-4000:]
