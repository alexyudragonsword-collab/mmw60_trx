"""Numerical fingerprint of the engine: prove a change did not move a number (iron rule 7).

Halo_Serdes / d2d_link method.  Records every bundled config
(``configs/*.yaml``) through one packet at a fixed seed and SNR, with and
without noise, plus the primitives no config reaches on its own: the BCC
encoder, both Viterbi kernels, the interleaver, the scrambler, the Rapp
curves and the OBO solver, the pole-zero PSD and its synthesis, the STF /
LTF / extended CFO estimators at K = 4 / 8 / 16, the per-tone SNR offset.
Scalars are stored by ``repr`` and arrays by SHA-256, so the comparison is
exact.  Bit-exact means the same machine and library versions: record both
sides in one environment.

    python tools/fingerprint.py record before.json     # on the base commit
    python tools/fingerprint.py record after.json      # on the change
    python tools/fingerprint.py compare before.json after.json

``compare`` prints every differing value and exits 1 if there is one.  Both
commands also list the entries that raised instead of recording values:
two sides failing the same way compare equal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

CONFIGS = REPO / "configs"


def digest(a) -> str:
    a = np.asarray(a)
    if np.iscomplexobj(a):
        a = np.stack([a.real, a.imag])
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64)).hexdigest()[:16]


def _guarded(fn):
    try:
        return fn()
    except Exception as e:      # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc().splitlines()[-1]}


def packet_values(cfg, snr, seed=11) -> dict:
    from mmw60.sim.link import LinkSim
    sim = LinkSim(cfg)
    rng = np.random.default_rng(seed)
    r = sim.packet(snr, rng, keep_symbols=True)
    out = {"bit_errors": r.rx.bit_errors, "evm_db": repr(r.rx.evm_db),
           "cfo_hat_hz": repr(r.rx.cfo_hat_hz), "cfo_stf_hz": repr(r.rx.cfo_stf_hz),
           "cfo_ltf_hz": repr(r.rx.cfo_ltf_hz), "cfo_true_hz": repr(r.cfo_true_hz),
           "eq_symbols": digest(r.rx.eq_symbols), "taps": digest(r.taps)}
    for k, v in sorted(r.pa_info.items()):
        out["pa." + k] = repr(float(v))
    return out


def config_values(path: Path) -> dict:
    from mmw60.config import Mmw60Config
    cfg = Mmw60Config.from_yaml(path)
    return {"noiseless": _guarded(lambda: packet_values(cfg, None)),
            "snr10": _guarded(lambda: packet_values(cfg, 10.0)),
            "cfo_hz": repr(cfg.cfo_hz)}


def primitive_values() -> dict:
    from mmw60.config import liu2025_table2
    from mmw60.impairments.noise import per_sample_snr_offset_db
    from mmw60.impairments.phase_noise import PoleZeroPhase, lo_phase
    from mmw60.pa.rapp import ModifiedRappPA, drive_for_obo
    from mmw60.phy import bcc, interleaver, scrambler
    from mmw60.phy.mcs import vht_mcs
    from mmw60.phy.ppdu import build_data_field, decode_data_field, random_psdu
    from mmw60.rx.cfo import ltf_integer_cfo, stf_coarse_cfo
    from mmw60.sim.link import LinkSim

    rng = np.random.default_rng(5)
    out: dict = {}
    bits = rng.integers(0, 2, 300).astype(np.uint8)
    bits[-6:] = 0
    coded = bcc.encode(bits)
    out["bcc.encode"] = digest(coded)
    out["bcc.puncture34"] = digest(bcc.puncture(coded, (3, 4)))
    llr = (1.0 - 2.0 * coded) * 3.0 + rng.standard_normal(coded.size)
    for k in ("numpy", "numba"):
        out[f"bcc.viterbi.{k}"] = _guarded(lambda k=k: digest(bcc.viterbi_decode(llr, kernel=k)))
    out["interleaver.perm.4"] = digest(interleaver.permutation(4))
    out["scrambler.seq"] = digest(scrambler.scrambling_sequence(200))
    m = vht_mcs(4)
    psdu = random_psdu(100, rng)
    pil = (2.0 * rng.integers(0, 2, size=(m.n_symbols(100), 4)) - 1).astype(complex)
    f = build_data_field(m, psdu, 56, np.array([7, 21, 34, 48]), pil)
    out["ppdu.symbols"] = digest(f.symbols)
    y = f.symbols + 0.2 * (rng.standard_normal(f.symbols.shape) + 1j * rng.standard_normal(f.symbols.shape))
    out["ppdu.decode_errors"] = decode_data_field(y, f, 1.0)[1]
    pa = ModifiedRappPA()
    a = np.logspace(-3, 0.5, 400)
    out["rapp.am_am"] = digest(pa.am_am(a))
    out["rapp.am_pm"] = digest(pa.am_pm_deg(a))
    out["rapp.p1db"] = repr(pa.p1db)
    x = (rng.standard_normal(4000) + 1j * rng.standard_normal(4000)) / np.sqrt(2)
    out["rapp.drive_obo8"] = repr(drive_for_obo(pa, x, 8.0))
    pn = PoleZeroPhase()
    out["pn.psd"] = digest(pn.psd(np.logspace(3, 9, 200)))
    out["pn.phase"] = digest(lo_phase(pn, 4096, 320e6, np.random.default_rng(9)))
    out["pn.integrated"] = repr(pn.integrated_rad2())
    out["snr_offset"] = repr(per_sample_snr_offset_db(64, 2, 56))
    for k in (4, 8, 16):
        sim = LinkSim(liu2025_table2(k=k, mcs=0).ideal().with_(xo_ppm_tx=20, xo_ppm_rx=20))
        field, frame = sim.transmit(np.random.default_rng(k))
        y, _, _ = sim.impair(frame.x, np.random.default_rng(k + 1), 25.0)
        out[f"cfo.stf.k{k}"] = repr(stf_coarse_cfo(y, sim.phy.stf_period_samples, 10, sim.phy.fs_eff))
        out[f"cfo.integer.k{k}"] = ltf_integer_cfo(y, frame, 8)
    return out


def record() -> dict:
    out = {"configs": {}, "primitives": _guarded(primitive_values)}
    for p in sorted(CONFIGS.glob("*.yaml")):
        out["configs"][p.stem] = _guarded(lambda p=p: config_values(p))
    return out


def flatten(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from flatten(v, f"{prefix}/{k}" if prefix else str(k))
    else:
        yield prefix, d


def compare(a: dict, b: dict) -> list[str]:
    fa, fb = dict(flatten(a)), dict(flatten(b))
    diffs = []
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k, "<absent>") != fb.get(k, "<absent>"):
            diffs.append(f"{k}: {fa.get(k, '<absent>')} -> {fb.get(k, '<absent>')}")
    return diffs


def raised(d: dict) -> list[str]:
    return [k for k, v in flatten(d) if k.endswith("/error")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("out", type=Path)
    c = sub.add_parser("compare")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "record":
        d = record()
        a.out.write_text(json.dumps(d, indent=1, sort_keys=True))
        errs = raised(d)
        print(f"recorded {sum(1 for _ in flatten(d))} values to {a.out}"
              + (f"; {len(errs)} entries raised: {', '.join(errs)}" if errs else ""))
        return 0
    before = json.loads(a.before.read_text())
    after = json.loads(a.after.read_text())
    diffs = compare(before, after)
    for d in diffs:
        print(d)
    errs = raised(after)
    if errs:
        print(f"entries that raised: {', '.join(errs)}")
    if diffs:
        print(f"{len(diffs)} value(s) differ")
        return 1
    print("bit-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
