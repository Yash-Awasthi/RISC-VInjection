# Documentation index

One entry point. Each row names a document, the claims it carries, and the
command that keeps the claim true. A claim with no command here is not
maintained; fix the document or add the command.

Every document in `docs/` appears exactly once. The test column names a file
that exists; `docs/build-and-test.md` names the target (`make check-core`,
and so on) that runs it.

| Document | Claims it supports | Test or command that proves it |
|---|---|---|
| `docs/spec.md` | The normative definition: encoding, `attn_weights`/`attn_cfg` layouts, bit-exact semantics, reserved configurations, trap and re-execution behaviour, spec versioning. | `tests/test_core.py` (the executable header against the float64 model), `tests/test_boundaries.py` (maximum and one-past shapes), `tests/test_vectors.py` (frozen vector set and header hash). |
| `docs/theory.md` | Why the computation is what it is, the float32 accumulation order, where the tolerances come from, and the cost argument. | `tests/test_accumulation_order.py` (the stated ascending-k order), `tests/test_tolerances.py` (one definition of ATOL_F32/ATOL_BF16), `tests/test_core.py`. |
| `docs/build-and-test.md` | Clone to green: packages, sources, the six build steps, every check target, the support matrix and the time budget. | `tests/test_build_info.py` (`out/BUILD-INFO` names the pins and the versions), `tests/test_scripts.py` (`--help`, unknown flags, `set -euo pipefail`). The steps themselves need the toolchain: `make check`. |
| `docs/implementation.md` | Which file in each of the five submodules carries which part of the instruction, and that the patches are the only delta. | `tests/test_core.py::test_simulator_cores_match_include` (the shared headers are byte-identical in spike, qemu and libgcc), `tests/test_pins.py` (the five pins), `scripts/patches.sh check`. |
| `docs/new-instruction.md` | The general method: any instruction through `scripts/xinsn.py`, what it edits, and how to go further by hand. | `tests/test_xinsn.py` (create, apply, list, test, remove; failure paths), `examples/insns/mac.spec`. |
| `docs/recognizer.md` | The GCC middle-end pass: the loop shape it recognises, the runtime guard, and the restrictions that make it reject a loop. | `tests/test_attn_replacement.py` (`make check-demo`), `tests/recog` (`make check-recog`). |
| `docs/walkthrough.md` | The end-to-end narrative: one C excerpt to one `attn` on two simulators and back out again. | `tests/test_three_way.py` (`make check-three-way`), `tests/baremetal` (`make check-sim`). |
| `docs/study.md` | A seven-stage reading path with one checked answer per stage. | `tests/test_study_answers.py` (the answers, the file counts they cite, and the spec sentences they quote). |
| `docs/review.md` | The minimum review for any change to `include/attn_core.h`: spec, vectors, all three executions. | `tests/test_repo_layout.py` (CODEOWNERS, and every target and script the checklist cites exists). |
| `docs/RUNBOOK.md` | The first diagnostic for each failure mode: build step, patch conflict, submodule drift, simulator abort, vector mismatch. | No dedicated test. Its two scripts are exercised by `make check`: `scripts/check-build-info.sh` (stale or missing build record) and `scripts/check-pins.sh` (drifted pin); `tests/test_scripts.py` covers their flags. |
| `docs/artifacts.html` | The static report of the collected results, generated from the JSON, no build step. | `tests/test_artifacts_html.py` (`tools/report_html.py` regenerates it). |
| `docs/troubleshooting.md` | The five most common build failures (missing package, patch conflict, submodule not initialised, stale toolchain, wrong `-march`): the message, the line it came from, and the fix. | `tests/test_diagnose.py` (five fixture logs, exact line numbers and exit codes). |
| `docs/INDEX.md` | This table. | `ls docs` against the first column: every row names a file that exists, and every file has a row. |

## Checking this index

```sh
for f in docs/*; do grep -q "$f" docs/INDEX.md || echo "missing: $f"; done
grep -oE 'tests/[a-z_/]+\.py' docs/INDEX.md | sort -u | xargs ls -1 >/dev/null
```

The first line prints nothing when every file is listed; the second fails if
the index names a test file that no longer exists.