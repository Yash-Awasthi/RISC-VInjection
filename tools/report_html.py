#!/usr/bin/env python3
"""Render the frozen attention vectors as one self-contained static HTML page.

Every row is generated from the JSON manifest and vector files; nothing is
hand-typed. The output has no build step, no scripts, and no external assets.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "tests" / "vectors" / "MANIFEST.json"
DEFAULT_OUT = REPO_ROOT / "artifacts" / "report.html"

# dtype id -> (JSON encoding written by freeze_vectors.py, display name)
DTYPE_BY_ID = {0: ("<f4", "f32"), 1: ("<u2", "bf16")}
KNOWN_DTYPES = {enc for enc, _ in DTYPE_BY_ID.values()}

BIAS_SHAPES = {"bq": "e", "bo": "e", "bk": "kv", "bv": "kv"}

FLAG_ORDER = (0, 1, 2, 3)
FLAG_LABELS = {0: "none", 1: "causal", 2: "scale", 3: "causal+scale"}
PAIR_ORDER = (("f32", "f32"), ("f32", "bf16"), ("bf16", "f32"), ("bf16", "bf16"))

GENERATOR_COMMAND = "python tools/freeze_vectors.py --write"


class ValidationError(Exception):
    """A manifest or vector file does not match the frozen format."""


def fail(message: str) -> None:
    raise ValidationError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def is_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def as_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{what} must be an integer, got {type(value).__name__}")
    return value


def as_list(value: object, what: str) -> list:
    if not isinstance(value, list):
        fail(f"{what} must be a list, got {type(value).__name__}")
    return value


def load_json(path: Path, what: str):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail(f"cannot read {what} {path}: {exc}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{what} {path} is not valid UTF-8 JSON: {exc}")


def check_array(arrays: dict, key: str, shape: list[int], allowed: set[str],
                 where: str, required: bool) -> None:
    if key not in arrays:
        require(not required, f"{where}: arrays[{key!r}] is missing")
        return
    arr = arrays[key]
    if not isinstance(arr, dict):
        fail(f"{where}: arrays[{key!r}] must be an object")
    require(
        arr.get("shape") == shape,
        f"{where}: arrays[{key!r}].shape must be {shape}, got {arr.get('shape')!r}",
    )
    dtype = arr.get("dtype")
    if not isinstance(dtype, str) or dtype not in KNOWN_DTYPES:
        fail(f"{where}: arrays[{key!r}].dtype is unexpected: {dtype!r}")
    require(
        dtype in allowed,
        f"{where}: arrays[{key!r}].dtype must be {sorted(allowed)}, got {dtype!r}",
    )


def parse_vector(path: Path, filename: str) -> dict:
    where = filename
    vec = load_json(path, "vector")
    if not isinstance(vec, dict):
        fail(f"{where}: top level must be an object")
    require(vec.get("format") == 2, f"{where}: format must be 2, got {vec.get('format')!r}")

    stem = Path(filename).stem
    require(vec.get("name") == stem, f"{where}: name must equal {stem!r}, got {vec.get('name')!r}")

    cfg = vec.get("cfg")
    if not isinstance(cfg, dict):
        fail(f"{where}: cfg must be an object")

    n = as_int(cfg.get("n"), f"{where}: cfg.n")
    e = as_int(cfg.get("e"), f"{where}: cfg.e")
    h = as_int(cfg.get("h"), f"{where}: cfg.h")
    h_kv = as_int(cfg.get("h_kv"), f"{where}: cfg.h_kv")
    flags = as_int(cfg.get("flags"), f"{where}: cfg.flags")
    in_id = as_int(cfg.get("in_dtype"), f"{where}: cfg.in_dtype")
    out_id = as_int(cfg.get("out_dtype"), f"{where}: cfg.out_dtype")

    require(n > 0, f"{where}: cfg.n must be > 0, got {n}")
    require(e > 0, f"{where}: cfg.e must be > 0, got {e}")
    require(h > 0, f"{where}: cfg.h must be > 0, got {h}")
    require(h_kv >= 0, f"{where}: cfg.h_kv must be >= 0, got {h_kv}")
    require(0 <= flags <= 3, f"{where}: cfg.flags must be in 0..3, got {flags}")
    require(in_id in DTYPE_BY_ID, f"{where}: cfg.in_dtype has unknown id {in_id}")
    require(out_id in DTYPE_BY_ID, f"{where}: cfg.out_dtype has unknown id {out_id}")
    require(e % h == 0, f"{where}: cfg.e={e} is not divisible by cfg.h={h}")
    require(
        h_kv == 0 or h % h_kv == 0,
        f"{where}: cfg.h={h} is not divisible by cfg.h_kv={h_kv}",
    )

    in_enc, in_name = DTYPE_BY_ID[in_id]
    out_enc, out_name = DTYPE_BY_ID[out_id]
    d = e // h
    kv = (h_kv or h) * d

    expected = vec.get("expected")
    if not isinstance(expected, dict):
        fail(f"{where}: expected must be an object")
    sha = expected.get("sha256")
    require(is_hex64(sha), f"{where}: expected.sha256 must be 64 hex chars")
    require(
        expected.get("shape") == [n, e],
        f"{where}: expected.shape must be [{n}, {e}], got {expected.get('shape')!r}",
    )
    require(
        expected.get("dtype") == out_enc,
        f"{where}: expected.dtype must be {out_enc!r}, got {expected.get('dtype')!r}",
    )

    arrays = vec.get("arrays")
    if not isinstance(arrays, dict):
        fail(f"{where}: arrays must be an object")

    # Any array, known name or not, must carry a known dtype string.
    for key, arr in arrays.items():
        if not isinstance(arr, dict):
            fail(f"{where}: arrays[{key!r}] must be an object")
        dtype = arr.get("dtype")
        if not isinstance(dtype, str) or dtype not in KNOWN_DTYPES:
            fail(f"{where}: arrays[{key!r}].dtype is unexpected: {dtype!r}")

    in_enc_set = {in_enc}
    weight_set = in_enc_set
    bias_set = {"<f4"}
    check_array(arrays, "x", [n, e], in_enc_set, where, required=True)
    check_array(arrays, "wq", [e, h * d], weight_set, where, required=True)
    check_array(arrays, "wo", [e, h * d], weight_set, where, required=True)
    check_array(arrays, "wk", [e, kv], weight_set, where, required=True)
    check_array(arrays, "wv", [e, kv], weight_set, where, required=True)
    for key, dim in BIAS_SHAPES.items():
        check_array(arrays, key, [e if dim == "e" else kv], bias_set, where, required=False)
    check_array(arrays, "mask", [n, n], bias_set, where, required=False)

    features = vec.get("features") or []
    require(isinstance(features, list), f"{where}: features must be a list")
    for feature in features:
        require(isinstance(feature, str), f"{where}: features entries must be strings")

    return {
        "name": stem,
        "n": n,
        "e": e,
        "h": h,
        "h_kv": h_kv,
        "d": d,
        "kv": kv,
        "in_name": in_name,
        "out_name": out_name,
        "flags": flags,
        "flag_label": FLAG_LABELS[flags],
        "y_shape": f"{n}x{e}",
        "y_dtype": out_name,
        "sha": sha,
        "features": features,
    }


def validate_manifest(manifest_path: Path) -> tuple[dict, list[dict]]:
    manifest = load_json(manifest_path, "manifest")
    if not isinstance(manifest, dict):
        fail("manifest: top level must be an object")
    require(
        manifest.get("format") == 2,
        f"manifest: format must be 2, got {manifest.get('format')!r}",
    )
    header = manifest.get("header_sha256")
    require(is_hex64(header), "manifest: header_sha256 must be a 64-character hex string")

    names = as_list(manifest.get("vectors"), "manifest.vectors")
    for filename in names:
        require(
            isinstance(filename, str) and filename != "",
            f"manifest.vectors: entries must be non-empty strings, got {filename!r}",
        )
        require(
            "/" not in filename and "\\" not in filename and ".." not in filename,
            f"manifest.vectors: {filename!r} must be a bare filename",
        )

    declared = [key for key in ("vector_count", "count") if key in manifest]
    for key in declared:
        value = as_int(manifest[key], f"manifest.{key}")
        require(
            value == len(names),
            f"manifest.{key} is {value} but manifest.vectors lists {len(names)}",
        )

    manifest_dir = manifest_path.parent
    present = sorted(
        p.name for p in manifest_dir.glob("*.json") if p.name != "MANIFEST.json"
    )
    require(
        len(present) == len(names),
        f"manifest dir {manifest_dir} holds {len(present)} vector json files "
        f"but manifest.vectors lists {len(names)}",
    )

    records = []
    for filename in names:
        path = manifest_dir / filename
        require(path.is_file(), f"vector file {filename!r} is missing from {manifest_dir}")
        records.append(parse_vector(path, filename))

    refreeze = manifest.get("refreeze", [])
    require(isinstance(refreeze, list), "manifest.refreeze must be a list")
    return manifest, records


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render(manifest: dict, records: list[dict]) -> str:
    header = manifest["header_sha256"]
    header_prefix = header[:16]
    header12 = header[:12]
    refreeze = manifest.get("refreeze", [])

    provenance = f"freeze_vectors.py <- attn_model.py; header {header12}; format 2"

    pair_counts = Counter((r["in_name"], r["out_name"]) for r in records)
    flag_counts = Counter(r["flags"] for r in records)

    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>RISC-VInjection attention vectors</title>",
        "<style>",
        "body{margin:2rem;background:#fff;color:#1d1f21;"
        "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.45}",
        "h1{font-size:1.4rem;margin:0 0 .25rem}",
        "h2{font-size:1.05rem;margin:2rem 0 .5rem;border-bottom:1px solid #c8ccd0;"
        "padding-bottom:.2rem}",
        "p{margin:.35rem 0}",
        ".tagline{color:#555}",
        "table{border-collapse:collapse;margin:.75rem 0;font-size:.85rem}",
        "th,td{border:1px solid #c8ccd0;padding:.25rem .5rem;text-align:left;"
        "vertical-align:top}",
        "th{background:#eef1f4;font-weight:600}",
        "code{background:#eef1f4;padding:0 .2rem}",
        "span[title]{cursor:help;border-bottom:1px dotted #999}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>RISC-VInjection attention vectors</h1>",
        '<p class="tagline">static, no build step</p>',
        "<p>Every table below is generated from the frozen JSON manifest and vector "
        f"files. {len(records)} vectors.</p>",
        "<h2>Manifest</h2>",
        "<table>",
        "<tr><th>field</th><th>value</th></tr>",
        f"<tr><td>format</td><td>{esc(manifest['format'])}</td></tr>",
        f'<tr><td>header_sha256</td><td><span title="{esc(header)}">'
        f"{esc(header_prefix)}</span></td></tr>",
        f"<tr><td>vector count</td><td>{esc(len(records))}</td></tr>",
        f"<tr><td>refreeze entries</td><td>{esc(len(refreeze))}</td></tr>",
        f"<tr><td>generator</td><td><code>{esc(GENERATOR_COMMAND)}</code></td></tr>",
        "</table>",
        "<h2>Vectors</h2>",
        "<table>",
        "<tr><th>name</th><th>n</th><th>e</th><th>h</th><th>h_kv</th><th>d</th>"
        "<th>kv</th><th>in dtype</th><th>out dtype</th><th>flags</th><th>Y shape</th>"
        "<th>Y dtype</th><th>expected sha256</th><th>features</th>"
        "<th>provenance</th></tr>",
    ]

    for rec in records:
        h_kv_text = "=h" if rec["h_kv"] == 0 else str(rec["h_kv"])
        features_text = ", ".join(rec["features"]) if rec["features"] else "none"
        lines.append(
            "<tr>"
            f"<td>{esc(rec['name'])}</td>"
            f"<td>{esc(rec['n'])}</td>"
            f"<td>{esc(rec['e'])}</td>"
            f"<td>{esc(rec['h'])}</td>"
            f"<td>{esc(h_kv_text)}</td>"
            f"<td>{esc(rec['d'])}</td>"
            f"<td>{esc(rec['kv'])}</td>"
            f"<td>{esc(rec['in_name'])}</td>"
            f"<td>{esc(rec['out_name'])}</td>"
            f"<td>{esc(rec['flag_label'])}</td>"
            f"<td>{esc(rec['y_shape'])}</td>"
            f"<td>{esc(rec['y_dtype'])}</td>"
            f'<td><span title="{esc(rec["sha"])}">{esc(rec["sha"][:12])}</span></td>'
            f"<td>{esc(features_text)}</td>"
            f"<td>{esc(provenance)}</td>"
            "</tr>"
        )

    lines.extend(
        [
            "</table>",
            "<h2>Summary: in/out dtype pairs</h2>",
            "<table>",
            "<tr><th>in dtype</th><th>out dtype</th><th>vectors</th></tr>",
        ]
    )
    for in_name, out_name in PAIR_ORDER:
        lines.append(
            "<tr>"
            f"<td>{esc(in_name)}</td><td>{esc(out_name)}</td>"
            f"<td>{esc(pair_counts[(in_name, out_name)])}</td>"
            "</tr>"
        )

    lines.extend(
        [
            "</table>",
            "<h2>Summary: flags</h2>",
            "<table>",
            "<tr><th>flags</th><th>value</th><th>vectors</th></tr>",
        ]
    )
    for flag in FLAG_ORDER:
        lines.append(
            "<tr>"
            f"<td>{esc(FLAG_LABELS[flag])}</td><td>{esc(flag)}</td>"
            f"<td>{esc(flag_counts[flag])}</td>"
            "</tr>"
        )

    lines.extend(
        [
            "</table>",
            "<h2>Expected sha256</h2>",
            "<table>",
            "<tr><th>name</th><th>sha256</th></tr>",
        ]
    )
    for rec in records:
        lines.append(
            f"<tr><td>{esc(rec['name'])}</td><td>{esc(rec['sha'])}</td></tr>"
        )

    lines.extend(["</table>", "</body>", "</html>", ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the frozen attention vectors as static HTML.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="path to MANIFEST.json")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="path of the HTML file to write")
    return parser


def check_output_path(out_path: Path) -> None:
    out_resolved = out_path.resolve()
    parts = out_resolved.parts
    protected = [(REPO_ROOT / "tests" / "vectors").resolve()]
    for index in range(len(parts) - 1):
        if parts[index].lower() == "tests" and parts[index + 1].lower() == "vectors":
            protected.append(Path(*parts[: index + 2]))
    for base in protected:
        if out_resolved == base or out_resolved.is_relative_to(base):
            fail(f"refusing to write {out_path} inside the vectors directory {base}")
    require(not out_resolved.is_dir(), f"output path {out_path} is a directory")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out)

    try:
        check_output_path(out_path)
        manifest, records = validate_manifest(manifest_path)
        document = render(manifest, records)
        try:
            payload = document.encode("ascii")
        except UnicodeEncodeError as exc:
            fail(f"render produced non-ASCII output: {exc}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {out_path} ({len(payload)} bytes, {len(records)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
