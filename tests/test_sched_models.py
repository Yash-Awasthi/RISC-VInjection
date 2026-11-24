# SPDX-License-Identifier: GPL-3.0-or-later
"""`attn` is scheduled under every pipeline model this GCC port has.

`gcc/config/riscv/riscv-cores.def` maps each `-mtune=` name to a pipeline
model, so the models are read from the compiler rather than listed by hand.
For each tuning the test compiles a two-call function with `-dp` and requires
the annotation on the `attn` lines to name the insn pattern: a type the
scheduler cannot place (no insn reservation) makes GCC crash or drop the
annotation, which is what this catches.  The table of models checked is
printed.
"""

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GCC = REPO / "out" / "toolchain" / "bin" / "riscv64-unknown-elf-gcc"
CORES_DEF = REPO / "gcc" / "gcc" / "config" / "riscv" / "riscv-cores.def"
PATTERN = "riscv_attn_di"

SOURCE = """
#include <stdint.h>
void f (float *y, const float *x, const uint64_t *w, const uint32_t *c)
{
  __builtin_riscv_attn (y, x, w, c);
  __builtin_riscv_attn (y + 1, x, w, c);
}
"""

pytestmark = pytest.mark.skipif(
    not GCC.exists(), reason="needs a built toolchain (scripts/build.sh)"
)


def tunings():
    """(tune name, pipeline model) as the compiler's own table has them."""
    text = CORES_DEF.read_text(encoding="utf-8")
    pairs = re.findall(
        r'^RISCV_TUNE\("([^"]+)",\s*([A-Za-z_0-9]+),', text, flags=re.M
    )
    assert pairs, "no RISCV_TUNE rows in riscv-cores.def"
    return pairs


def compile_with(tune, tmp_path):
    src = tmp_path / "s.c"
    src.write_text(SOURCE, encoding="utf-8")
    r = subprocess.run(
        [
            str(GCC), "-march=rv64gc_xattn", "-mabi=lp64d", "-O2",
            f"-mtune={tune}", "-dp", "-S", str(src), "-o", "-",
        ],
        capture_output=True, text=True,
    )
    return r


def test_every_pipeline_model_schedules_attn(tmp_path):
    pairs = tunings()
    models = sorted({model for _, model in pairs})
    results = {}
    for tune, model in pairs:
        r = compile_with(tune, tmp_path)
        annotated = [
            l for l in r.stdout.splitlines()
            if l.startswith("\tattn") and PATTERN in l
        ]
        results[tune] = (model, r.returncode, len(annotated), r.stderr.strip())

    print(f"\n{'pipeline model':<18} {'-mtune':<20} {'attn lines with ' + PATTERN}")
    for model in models:
        rows = [(t, v) for t, v in results.items() if v[0] == model]
        for tune, (_, rc, n, _) in rows:
            print(f"{model:<18} {tune:<20} {n}  {'ok' if rc == 0 and n == 2 else 'BAD'}")
        assert all(rc == 0 and n == 2 for _, (_, rc, n, _) in rows), (
            f"{model}: " + ", ".join(
                f"{t} rc={rc} annotated={n} {err}" for t, (_, rc, n, err) in rows
                if rc != 0 or n != 2
            )
        )
    print(f"\n{len(models)} pipeline models, {len(pairs)} tunings checked: "
          f"{', '.join(models)}")
