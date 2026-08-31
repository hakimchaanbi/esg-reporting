"""Negative test: a duplicate AMENDMENTS key must stop the run.

    python mapping/test_amendments_unique.py

Python dict literals silently keep the LAST of any repeated key. On 2026-08-30
the three OP-3 water rows were amended twice — once in the 2026-08-22 unit pass,
once for the conversion-instruction fix — and the older block won because it sat
lower in the file. `add_pass2_rows.py` printed "already current" and changed
nothing, which is indistinguishable from success.

`assert_no_duplicate_amendments()` parses the module's own source, where both
keys still exist, and refuses to run. This proves it fires, in the same spirit as
`test_validator_catches_fabrication.py`: a guard nobody has tried to break is not
a guarantee.

Dry run only — this never passes --write, so the mapping CSV is not touched.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
SRC = ROOT / "mapping" / "add_pass2_rows.py"
PROBE = ROOT / "mapping" / "_dupe_probe.py"

# A second block for a key the file already amends, placed so it silently wins.
DUPE = (
    '    ("OP-5", "Natural gas", "302-1"): {\n'
    '        "caveat": "INJECTED DUPLICATE - must be unreachable",\n'
    '    },\n'
)


def run(module: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(PYTHON) if PYTHON.exists() else sys.executable,
                           "-m", module],
                          cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    anchor = "\nAMENDMENTS = {\n"
    text = SRC.read_text(encoding="utf-8")
    if anchor not in text:
        sys.exit("cannot inject: the AMENDMENTS literal was reformatted, so "
                 "this test no longer knows where to put the duplicate.")

    try:
        PROBE.write_text(text.replace(anchor, anchor + DUPE, 1), encoding="utf-8")
        bad = run("mapping._dupe_probe")
        out = (bad.stdout + bad.stderr).strip()

        print(f"[probe] injected a duplicate key -> exit={bad.returncode}")
        if bad.returncode == 0:
            sys.exit("FAIL: a duplicate AMENDMENTS key ran through cleanly. The "
                     "earlier block would be dead code and nothing would say so.")
        if "repeats" not in out or "Natural gas" not in out:
            sys.exit(f"FAIL: it stopped, but not with the duplicate-key "
                     f"message:\n{out[:400]}")
        print("       rejected, and the message names the offending key")

        # The positive control: the real file must still run. A guard that
        # rejects everything is not evidence of anything.
        good = run("mapping.add_pass2_rows")
        if good.returncode != 0:
            sys.exit(f"FAIL: the real, duplicate-free file no longer runs.\n"
                     f"{good.stderr[:400]}")
        print("[real ] duplicate-free file runs clean")
    finally:
        PROBE.unlink(missing_ok=True)
        shutil.rmtree(ROOT / "mapping" / "__pycache__", ignore_errors=True)

    print("\nAMENDMENTS uniqueness enforced: a repeated key cannot silently "
          "discard an earlier amendment.")


if __name__ == "__main__":
    main()
