"""Assert what the instrumented run actually did, and print what the device said.

A green Gradle task is not proof that the on-device tests ran: a test that
never executes, or is skipped, leaves the build successful and the guard
imaginary.  So the count is asserted here, exactly (a floor would still pass
when a test is added while another quietly stops running), and each failure's
message is printed at the end of the log, where a truncated log still reaches.

Usage:  check_ondevice_results.py <results-dir> <expected-count>
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TAG = "mmw60-ondevice"


def main(argv: list[str]) -> int | str:
    if len(argv) != 3:
        return "usage: check_ondevice_results.py <results-dir> <expected-count>"
    root, expected = Path(argv[1]), int(argv[2])
    files = sorted(root.rglob("*.xml"))
    if not files:
        return f"no instrumented test results were written under {root}"
    total = failed = skipped = 0
    names, failures = [], []
    for path in files:
        suite = ET.parse(path).getroot()
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.iter("testcase"):
            name = f"{case.get('classname')}.{case.get('name')}"
            names.append(name)
            for bad in [*case.iter("failure"), *case.iter("error")]:
                failures.append((name, bad.text or bad.get("message") or "(no message)"))
    print(f"on-device tests: {total} run, {failed} failed, {skipped} skipped")
    for name in sorted(names):
        print("  -", name)
    said = sorted({line.split(TAG, 1)[1].lstrip(": ").strip() for path in root.rglob("logcat*")
                   for line in path.read_text(errors="replace").splitlines() if TAG in line})
    print("what the device said:" if said else "what the device said: (no logcat line found)")
    for line in said:
        print("  ", line)
    for name, text in failures:
        print(f"\n--- {name} ---")
        for line in [ln for ln in text.strip().splitlines() if ln.strip()][:20]:
            print("   ", line)
    if total != expected:
        return f"expected exactly {expected} on-device tests, ran {total} (update the number when adding one)"
    if failed or skipped:
        return "on-device tests failed or were skipped"
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
