# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/*.sh: known set, strict mode, no swallowed failure at the end."""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
KNOWN = {
    "artifacts.sh", "attncc.sh", "build.sh", "check-build-info.sh",
    "check-pins.sh", "patches.sh", "setup.sh", "xattn.sh",
}
STRICT = re.compile(r"^set -euo pipefail$", re.M)
EXIT_STATUS = re.compile(r"\bexit\s+(\$[\w{}]+|[1-9]\d*|0)\b")
SWALLOW = re.compile(r"\|\|\s*(true|:|exit\s+0)\s*$")


def last_code_line(text):
    code = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    return code[-1]


def test_script_set_is_deliberate():
    files = sorted(SCRIPTS.glob("*.sh"))
    assert len(files) == len(set(files)) == 8
    assert {p.name for p in files} == KNOWN


def test_scripts_are_strict():
    for path in sorted(SCRIPTS.glob("*.sh")):
        assert STRICT.search(path.read_text(encoding="utf-8")), path.name


# Under `set -e` a trailing `exit 0` cannot mask a failure: the failing
# command already aborted the script, so only a clean run reaches that line.
def test_last_line_preserves_failure():
    for path in sorted(SCRIPTS.glob("*.sh")):
        line = last_code_line(path.read_text(encoding="utf-8"))
        assert not SWALLOW.search(line), f"{path.name}: {line!r}"
        if "||" in line:
            assert EXIT_STATUS.search(line.split("||", 1)[1]), \
                f"{path.name}: {line!r}"
        elif re.match(r"exit\b", line):
            assert EXIT_STATUS.search(line), f"{path.name}: {line!r}"
