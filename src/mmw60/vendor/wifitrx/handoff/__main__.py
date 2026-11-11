# Vendored from wifi_trx_cal@96078aa9438c590a24d13959472263ec5f9ab623: src/wifitrx/handoff/__main__.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""CLI:  python -m wifitrx.handoff run|regress|inspect|replay ...

run:      单个波形过链路,输出结果波形 + 指标 JSON
regress:  目录级批量回归,输出对账单 handoff_report.md
inspect:  独立检查 cal_state.json(纯标准库,可脱离本库运行)
replay:   照残差表字面重放,对上文件自己的实测 EVM(需 numpy)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..provenance import write_provenance
from .inspector import main as inspect_main
from .regress import run_regression
from .runner import build_calibrated_trx, run_handoff
from .waveform_io import load_waveform, save_waveform


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m wifitrx.handoff")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--bw", type=float, required=True,
                       help="channel bandwidth [Hz]")
        p.add_argument("--fs", type=float, default=None,
                       help="sample rate [Hz], default bw*4")
        p.add_argument("--seed", type=int, default=5,
                       help="process-corner seed of the modeled chip")
        p.add_argument("--cal-state", type=Path, default=None,
                       help="cal_state.json to restore instead of recalibrating")
        p.add_argument("--scenario", choices=("tx_only", "loopback", "rx_only"),
                       default="loopback")
        p.add_argument("--out", type=Path, default=Path("reports/handoff"))

    p_run = sub.add_parser("run", help="single waveform")
    common(p_run)
    p_run.add_argument("--wave", type=Path, required=True)

    p_reg = sub.add_parser("regress", help="directory of waveforms")
    common(p_reg)
    p_reg.add_argument("--dir", type=Path, required=True)

    p_ins = sub.add_parser("inspect", help="check a cal_state.json "
                           "(stdlib-only, works without this library)")
    p_ins.add_argument("state", type=Path)

    p_rep = sub.add_parser("replay", help="apply the residuals literally "
                           "and compare against the file's own EVM")
    p_rep.add_argument("state", type=Path)
    p_rep.add_argument("--temp-c", type=float, default=None,
                       help="close at this temperature from the file's "
                            "temperature rules (schema 1.2) instead of at "
                            "the calibrated one")
    p_rep.add_argument("--recalibrated", action="store_true",
                       help="with --temp-c: the part was recalibrated at "
                            "that temperature, so inject each key's "
                            "after_recal bound instead of interpolating")

    args = ap.parse_args(argv)
    if args.cmd == "inspect":
        sys.exit(inspect_main([str(args.state)]))
    if args.cmd == "replay":
        from .replay import replay
        ok = True
        if args.recalibrated and args.temp_c is None:
            ap.error("--recalibrated needs --temp-c")
        for view in ("tx", "rx"):
            result = replay(args.state, view=view, temp_c=args.temp_c,
                            recalibrated=args.recalibrated)
            print(result.summary())
            print()
            ok = ok and result.verdict == "consistent"
        sys.exit(0 if ok else 1)
    fs = args.fs or args.bw * 4
    tx, rx = build_calibrated_trx(args.bw, fs, seed=args.seed,
                                  cal_state_json=args.cal_state)
    args.out.mkdir(parents=True, exist_ok=True)
    write_provenance(args.out / "provenance.json",
                     {"seed": args.seed, "bw_hz": args.bw, "fs_hz": fs})

    if args.cmd == "run":
        wave = load_waveform(args.wave)
        res = run_handoff(wave, tx, rx, scenario=args.scenario)
        out_npz = args.out / f"{args.wave.stem}_out.npz"
        save_waveform(out_npz, res.output)
        out_json = args.out / f"{args.wave.stem}_metrics.json"
        out_json.write_text(json.dumps(res.metrics, indent=2, default=float))
        print(f"output:  {out_npz}\nmetrics: {out_json}")
        for k, v in res.metrics.items():
            print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
    else:
        report = run_regression(args.dir, tx, rx, args.out,
                                scenario=args.scenario)
        print(f"report: {report}")


if __name__ == "__main__":
    main()
