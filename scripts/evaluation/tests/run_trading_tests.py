# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Run the whole trading suite across BOTH virtualenvs.

    python scripts/evaluation/tests/run_trading_tests.py

The trading tests are split across two interpreters because the code is:
`dydx-v4-client` pins `httpx<0.28` and the framework's `solana` needs
`httpx>=0.28`, so the venue signing SDKs and the framework cannot share an
environment. Each venv therefore skips the half it cannot import.

That split is fine until it is invisible. Run under one interpreter the suite
reports `OK (skipped=4)`, and those four skips are ~51 real tests that did not
run — a green result covering an unrun half. This runs both and adds them up, so
"OK" means the whole suite passed rather than whichever half was reachable.

Exits non-zero if either half fails, or if an interpreter is missing: an
environment that cannot run half the tests is a failure to report, not a detail
to omit.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# (label, interpreter, what it covers)
ENVS = [
    ("main", ["venv"], "framework + portfolio + carry engine"),
    ("executor", ["executor", ".venv"], "venue SDKs + executor server"),
]

def _python(parts):
    base = ROOT.joinpath(*parts)
    for candidate in (base / "Scripts" / "python.exe", base / "bin" / "python"):
        if candidate.exists():
            return candidate
    return None


def _run(label, exe, covers):
    print(f"\n=== {label} venv - {covers} ===")
    print(f"    {exe}")
    proc = subprocess.run(
        [str(exe), "-m", "unittest", "discover",
         "-s", "scripts/evaluation/tests", "-p", "test_trading_*.py", "-t", "."],
        cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stderr or "") + (proc.stdout or "")
    ran = skipped = 0
    for line in tail.splitlines():
        m = re.match(r"^Ran (\d+) tests?", line)
        if m:
            ran = int(m.group(1))
        # `skipped=N` appears on the OK line and inside the FAILED one
        # ("FAILED (failures=1, skipped=4)"), so match it wherever it sits
        # rather than only in the passing shape.
        m = re.search(r"\bskipped=(\d+)", line)
        if m:
            skipped = int(m.group(1))
    ok = proc.returncode == 0
    if not ok:
        # Only on failure: the passing case is a count, not a wall of log lines.
        print(tail.strip())
    executed = ran - skipped
    print(f"    {'PASS' if ok else 'FAIL'} - {executed} run,"
          f" {skipped} skipped (belong to the other venv)")
    return ok, executed


def main():
    results, total, failed = [], 0, False
    for label, parts, covers in ENVS:
        exe = _python(parts)
        if exe is None:
            print(f"\n=== {label} venv ===\n    MISSING: no interpreter under"
                  f" {ROOT.joinpath(*parts)}")
            failed = True
            results.append((label, None, False))
            continue
        ok, executed = _run(label, exe, covers)
        failed = failed or not ok
        total += executed
        results.append((label, executed, ok))

    print("\n" + "=" * 60)
    for label, executed, ok in results:
        if executed is None:
            print(f"  {label:<10} not run (interpreter missing)")
        else:
            print(f"  {label:<10} {executed} tests"
                  f"{'' if ok else '   <-- FAILED'}")
    print(f"  {'total':<10} {total} tests actually executed")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
