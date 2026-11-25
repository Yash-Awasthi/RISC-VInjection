# Security policy

`attn` is a single instruction with one fixed numeric definition, `include/attn_core.h`,
executed by the Spike and QEMU builds this repository patches. Spike and QEMU are the
reference executions, so an instruction that computes something other than what
`include/attn_core.h` says is a correctness defect with the impact of a security bug.

Three consequences matter:

- A mis-executed `attn` gives silently wrong results in a cryptographic or ML kernel.
  Nothing traps, nothing logs, and the caller uses the wrong bytes.
- A trap that must not happen breaks a program that should run.
- A store that writes where it must not, either an out-of-range element or a descriptor
  pointer that was not honoured, corrupts memory.

## Reporting

GitHub private vulnerability reporting on this repository is the only channel. Use the
Security tab, "Report a vulnerability" (GitHub Security Advisories), at
https://github.com/Yash-Awasthi/RISC-VInjection There is no email address for reports.

If that button is unavailable, open a normal issue that asks for a private channel and
contains NO exploit detail, no reproducer, and no descriptor bytes. Wait for a private
channel before sending anything further.

## What to send

- The simulator (Spike or QEMU) and which build you ran.
- The commit that ran and the pin it came from: `git -C spike rev-parse HEAD` and
  `git ls-tree HEAD spike`, or the `pinned` and `built` pair in `out/BUILD-INFO`, or
  `build/CI-TRACE.txt` when the run came from CI.
- The `-march`, `--isa` or `-cpu` string the simulator was given.
- The `struct attn_cfg` values: n, e, h, h_kv, flags, in_dtype, out_dtype, scale_bits,
  reserved, mask. Also the `struct attn_weights` pointer values.
- Expected and observed `Y` bytes, or the trap cause and mtval.
- A minimal reproducer: a `.S` or `.c` of a few instructions.

## Response window

- Acknowledge within 5 business days.
- Triage decision within 10 business days.
- Fix or documented mitigation within 30 days for a correctness or trap bug in the code
  this tree patches.
- 90 days by default as the coordinated-disclosure deadline, extendable once by
  agreement.

If a deadline is missed, the reporter may disclose after it.

## Scope and upstream

A bug in the upstream project itself also belongs to that project's process: Spike, QEMU,
GCC, binutils, newlib. A bug in the code this repository patches into them is ours first.

No bug bounty, and no payment for any report.

## Supported versions

Supported are only the pinned commits in `versions.env`, named by
`scripts/check-pins.sh`, and the tree this repository builds. Older pins are not
maintained.
