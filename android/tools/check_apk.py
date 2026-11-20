"""Say what actually went into the APK, and fail when the app could not work with it.

The build log does not tell whether the page, the library's data files and the
intended numpy / scipy are inside; this reads the APK itself (Chaquopy keeps the
Python payload in zip archives under assets/chaquopy/).

Usage:  check_apk.py <app.apk> <src/mmw60/webui/www> <android/phone-stack.txt>
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path


def main(argv: list[str]) -> int | str:
    if len(argv) != 4:
        return "usage: check_apk.py <app.apk> <www-dir> <phone-stack.txt>"
    apk = zipfile.ZipFile(argv[1])
    names = apk.namelist()
    print(f"{argv[1]}: {Path(argv[1]).stat().st_size / 1e6:.1f} MB, {len(names)} entries")
    problems = []

    page = sorted(p.name for p in Path(argv[2]).iterdir() if p.is_file())
    missing = [f for f in page if f"assets/www/{f}" not in names]
    print(f"page files: {len(page) - len(missing)} of {len(page)} under assets/www/")
    if missing:
        problems.append(f"page files missing from the APK: {missing}")

    payload: set[str] = set()
    for name in names:
        if name.startswith("assets/chaquopy/"):
            blob = apk.read(name)
            if zipfile.is_zipfile(io.BytesIO(blob)):
                inner = zipfile.ZipFile(io.BytesIO(blob)).namelist()
                payload.update(inner)
                print(f"  {name}: {len(blob) / 1e6:.1f} MB, {len(inner)} files")
    dists = sorted({m.group(1) for n in payload if (m := re.match(r"([^/]+)\.dist-info/", n))})
    print("python distributions:", ", ".join(dists) or "(none found)")
    for line in Path(argv[3]).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            want = line.replace("==", "-")
            if want not in dists:
                problems.append(f"{line} (android/phone-stack.txt) is not what the APK carries: {dists}")
    for prefix in ("mmw60/appbridge.", "mmw60/vendor/wifitrx/", "mmw60/data/gui/baseline/table.json",
                   "mmw60/data/spec/", "mmw60/vendor/spec_sources/data/", "numpy/", "scipy/", "yaml/"):
        if not any(n.startswith(prefix) for n in payload):
            problems.append(f"nothing under {prefix} in the Python payload")
    for unwanted in ("matplotlib/", "numba/"):
        if any(n.startswith(unwanted) for n in payload):
            problems.append(f"{unwanted} is in the payload; the app is meant to ship without it")
    abis = sorted({n.split("/")[1] for n in names if n.startswith("lib/")})
    print("ABIs:", ", ".join(abis))
    if abis != ["arm64-v8a", "x86_64"]:
        problems.append(f"expected the ABIs arm64-v8a and x86_64, found {abis}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
