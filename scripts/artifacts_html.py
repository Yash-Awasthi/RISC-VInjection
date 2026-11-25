#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the frozen-vector artefacts report as one static HTML page.

Reads tests/vectors/MANIFEST.json, every vector it lists, and the table in
artifacts/README.md, then writes a self-contained HTML5 page (inline style,
no script, no external references) to --out or stdout.
"""

import argparse
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "tests" / "vectors" / "MANIFEST.json"
VECTORS = REPO / "tests" / "vectors"
ARTIFACTS_README = REPO / "artifacts" / "README.md"

DTYPES = {0: "f32", 1: "bf16"}

STYLE = """\
body { margin: 2rem auto; max-width: 72rem; padding: 0 1rem;
       font-family: system-ui, sans-serif; line-height: 1.4; }
table { border-collapse: collapse; margin: 1rem 0 2rem; }
th, td { border: 1px solid #bbb; padding: 0.25rem 0.5rem;
         text-align: left; vertical-align: top; }
th { background: #eee; }
code { font-family: ui-monospace, monospace; }
td.num { text-align: right; }
caption { text-align: left; font-weight: bold; padding-bottom: 0.25rem; }
"""


def md_cell(text):
    """Escape a Markdown cell, turning `spans` into <code>."""
    parts = text.split("`")
    out = []
    for i, part in enumerate(parts):
        esc = html.escape(part)
        out.append("<code>%s</code>" % esc if i % 2 else esc)
    return "".join(out)


def artifacts_table():
    """Rows of the committed-artefacts table in artifacts/README.md."""
    rows = []
    for line in ARTIFACTS_README.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or not cells[0].startswith("`"):
            continue
        rows.append((cells[0], cells[1]))
    return rows


def load_vectors():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vectors = []
    for fname in sorted(manifest["vectors"]):
        doc = json.loads((VECTORS / fname).read_text(encoding="utf-8"))
        for key in ("name", "format", "cfg", "expected", "features"):
            if key not in doc:
                raise SystemExit("%s: missing %r" % (fname, key))
        vectors.append(doc)
    return vectors


def dtype_label(value):
    return DTYPES.get(value, str(value))


def flag_list(cfg):
    names = []
    if cfg.get("flags", 0) & 1:
        names.append("causal")
    if cfg.get("flags", 0) & 2:
        names.append("scale")
    return ", ".join(names) or "none"


def head_width(cfg):
    return cfg["e"] // cfg["h"]


def table(headers, rows, numeric=(), caption=None):
    out = ["<table>"]
    if caption:
        out.append("<caption>%s</caption>" % html.escape(caption))
    out.append("<thead><tr>")
    for i, head in enumerate(headers):
        cls = ' class="num"' if i in numeric else ""
        out.append("<th%s>%s</th>" % (cls, html.escape(head)))
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            cls = ' class="num"' if i in numeric else ""
            out.append("<td%s>%s</td>" % (cls, cell))
        out.append("</tr>")
    out.append("</tbody>")
    out.append("</table>")
    return out


def vector_table(vectors):
    rows = []
    for doc in vectors:
        cfg, exp = doc["cfg"], doc["expected"]
        rows.append([
            "<code>%s</code>" % html.escape(doc["name"]),
            str(doc["format"]),
            str(cfg["n"]),
            str(cfg["e"]),
            str(cfg["h"]),
            str(cfg["h_kv"]),
            str(head_width(cfg)),
            "%s / %s" % (dtype_label(cfg["in_dtype"]),
                         dtype_label(cfg["out_dtype"])),
            html.escape(flag_list(cfg)),
            html.escape(", ".join(doc["features"]) or "none"),
            "<code>%s</code>" % html.escape(exp["sha256"][:12]),
            html.escape("x".join(str(v) for v in exp["shape"])),
        ])
    return table(
        ["Vector", "Format", "n", "e", "h", "h_kv", "d", "Dtypes",
         "Flags", "Features", "sha256", "Shape"],
        rows,
        numeric=tuple(range(1, 7)),
    )


def count_table(caption, pairs):
    rows = [[html.escape(str(key)), str(n)] for key, n in pairs]
    return table(["Value", "Vectors"], rows, numeric=(1,), caption=caption)


def summary(vectors):
    dtype_pairs = {}
    features = {}
    heads = {}
    for doc in vectors:
        cfg = doc["cfg"]
        pair = "%s / %s" % (dtype_label(cfg["in_dtype"]),
                            dtype_label(cfg["out_dtype"]))
        dtype_pairs[pair] = dtype_pairs.get(pair, 0) + 1
        for tag in doc["features"]:
            features[tag] = features.get(tag, 0) + 1
        heads[cfg["h"]] = heads.get(cfg["h"], 0) + 1

    out = ["<h2>Summary</h2>"]
    out.append("<p>%d frozen vectors.</p>" % len(vectors))
    out += count_table("Input / output dtype pairs",
                       sorted(dtype_pairs.items()))
    out += count_table("Feature tags", sorted(features.items()))
    out += count_table("Head counts", sorted(heads.items()))
    return out


def render(vectors, artifacts):
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Artefacts report</title>",
        "<style>",
        STYLE.rstrip("\n"),
        "</style>",
        "</head>",
        "<body>",
        "<h1>Artefacts report</h1>",
        "<p>Tables are generated from tests/vectors/*.json and "
        "artifacts/README.md. This page is committed, not built.</p>",
        "<h2>Committed artefacts</h2>",
    ]
    rows = [[md_cell(name), md_cell(content)]
            for name, content in artifacts]
    out += table(["File", "Content"], rows)
    out.append("<h2>Frozen vectors</h2>")
    out += vector_table(vectors)
    out += summary(vectors)
    out += ["</body>", "</html>", ""]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render the artefacts report as static HTML.")
    parser.add_argument("--out", metavar="PATH",
                        help="write the page here (default: stdout)")
    args = parser.parse_args(argv)

    page = render(load_vectors(), artifacts_table())
    data = page.encode("ascii")
    if args.out:
        Path(args.out).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
