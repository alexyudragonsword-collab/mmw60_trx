"""Run the example scripts end to end, small enough for CI (Halo_Serdes / d2d_link method).

``tests/test_examples.py`` checks that each example compiles and that its
first printed line is the engine banner; this runs them.  ``--smoke`` (what
CI runs) passes ``--quick`` to every example and sets ``MMW60_SMOKE=1``: a
handful of packets per point, the numbers are meaningless, the code paths
are exercised.  Without it the examples run at their own sizes (an hour or
more for example 00 on four cores; the numbers the docs quote).

    python tools/run_examples.py --smoke                  # all of them
    python tools/run_examples.py --smoke 00               # by number prefix
    python tools/run_examples.py --jobs 2 --save new/     # full size, stdout kept

``--save DIR`` keeps each example's stdout as ``DIR/<name>.txt`` for
``tools/example_drift.py compare`` against ``examples/expected/``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"


def _one(p: Path, smoke: bool, timeout: float, env: dict, save: Path | None):
    t0 = time.time()
    cmd = [sys.executable, str(p)] + (["--quick"] if smoke else [])
    try:
        r = subprocess.run(cmd, cwd=EXAMPLES, env=env, capture_output=True, text=True,
                           timeout=timeout)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as exc:
        code, out, err = -1, exc.stdout or "", f"timed out after {timeout:.0f} s\n{exc.stderr or ''}"
    if save is not None:
        (save / f"{p.stem}.txt").write_text(out if isinstance(out, str) else out.decode())
    return code, err, time.time() - t0


def run(paths: list[Path], smoke: bool, timeout: float, jobs: int = 1,
        save: Path | None = None) -> int:
    env = dict(os.environ, MPLBACKEND="Agg",
               PYTHONPATH=os.pathsep.join(filter(None, [str(REPO / "src"),
                                                        os.environ.get("PYTHONPATH")])))
    env["MMW60_SMOKE"] = "1" if smoke else "0"
    if save is not None:
        save.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        results = pool.map(lambda p: _one(p, smoke, timeout, env, save), paths)
        for p, (code, err, dt) in zip(paths, results):
            if code == 0:
                print(f"ok    {p.name:<36} {dt:7.1f} s", flush=True)
            else:
                failed.append(p.name)
                print(f"FAIL  {p.name:<36} {dt:7.1f} s", flush=True)
                print("\n".join("      " + ln for ln in err.strip().splitlines()[-25:]), flush=True)
    print(f"\n{len(paths) - len(failed)} of {len(paths)} examples ran"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prefixes", nargs="*", help="example number prefixes (default: all)")
    ap.add_argument("--smoke", action="store_true", help="pass --quick to every example")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=7200.0, help="seconds per example")
    ap.add_argument("--save", type=Path, default=None, help="keep stdout as DIR/<name>.txt")
    a = ap.parse_args(argv)
    paths = sorted(p for p in EXAMPLES.glob("[0-9][0-9]_*.py"))
    if a.prefixes:
        paths = [p for p in paths if any(p.name.startswith(x) for x in a.prefixes)]
    if not paths:
        print("no examples matched", file=sys.stderr)
        return 2
    return run(paths, a.smoke, a.timeout, a.jobs, a.save)


if __name__ == "__main__":
    raise SystemExit(main())
