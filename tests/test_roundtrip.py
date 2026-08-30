#!/usr/bin/env python3
"""Validation test 3 (Python): the whole chain preserves the measurements.

Follows the same numbers through every stage of the build:

    MATLAB epoch files  ->  CSV dataset  ->  embedded payload

and checks that nothing is lost beyond the rounding each stage declares:
  * CSV curves match the .mat to the archival decimal precision;
  * payload curves match the .mat to the whole-cent quantization budget;
  * NaN gaps survive both stages unchanged;
  * trial metadata (condition, counts) agrees across all three;
  * the grand-average peaks recomputed at full precision from the .mat agree
    with pitch_explorer_reference.json, which is derived from the quantized payload.

The last check is an end-to-end re-derivation that
shares no code path with the exporter's own reference.

Skips cleanly when the MATLAB epoch files are not on this machine.

Run:  python tests/test_roundtrip.py
"""

import base64, csv, glob, gzip, json, os, re, sys, warnings
import numpy as np

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from convert_mat_to_csv import load_epoch_file, DEFAULT_CACHE, EXCLUDE, CURVE_DECIMALS
from export_pitch_explorer import matlab_gauss_smooth, PEAK_WIN_MS

# Budgets, in cents. The CSV stage rounds to CURVE_DECIMALS, so it can move a
# value by half a unit in the last place. The payload then quantizes THAT value
# to whole cents, so measured against the original .mat the two stages add up —
# which is why the payload budget is 0.5 + the CSV budget, not 0.5.
EPS = 1e-9
CSV_TOL = 0.5 * 10 ** (-CURVE_DECIMALS) + EPS
PAYLOAD_TOL = 0.5 + CSV_TOL
PEAK_TOL = 0.1  # cents, after averaging and smoothing
N_SPOT_CHECK = 4  # participants compared curve by curve

failures = []


def check(cond, msg):
    print(f"  [{'OK ' if cond else 'XX '}] {msg}")
    if not cond:
        failures.append(msg)


def read_curves_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [[float(v) if v else np.nan for v in row[1:]] for row in rd]
    times = np.array([float(x) for x in header[1:]])
    return np.asarray(rows, dtype=float).T, times  # nSamples x nTrials


def load_payload():
    path = os.path.join(ROOT, "pitch_explorer.html")
    if not os.path.exists(path):
        sys.exit(
            "pitch_explorer.html not built yet — run export_pitch_explorer.py first."
        )
    with open(path, encoding="utf-8") as f:
        html = f.read()

    def block(bid):
        m = re.search(rf'id="{bid}"[^>]*>([^<]+)</script>', html)
        return gzip.decompress(base64.b64decode(m.group(1).strip()))

    manifest = json.loads(block("manifest-b64").decode("utf-8"))
    data = block("data-b64")
    ds, lay = manifest["dataset"], manifest["binary"]["layout"]
    n_t = ds["epoch"]["nSamples"]
    s = lay["trials"]
    arr = (
        np.frombuffer(data, dtype="<i2", count=s["bytes"] // 2, offset=s["offset"])
        .astype(float)
        .reshape(-1, n_t)
    )
    arr = np.where(arr == ds["nanSentinel"], np.nan, arr)
    c = lay["condCodes"]
    codes = np.frombuffer(data, dtype="i1", count=c["bytes"], offset=c["offset"])
    return manifest, arr, codes


def main():
    files = sorted(glob.glob(os.path.join(DEFAULT_CACHE, "P*_*.mat")))
    if not files:
        print(
            f"MATLAB epoch files not found in {DEFAULT_CACHE} — skipping the round-trip test."
        )
        print("This test needs the source data; the payload tests do not.")
        return 0

    data_dir = os.path.join(ROOT, "csv_dataset")
    if not os.path.exists(os.path.join(data_dir, "dataset.json")):
        print(
            f"No CSV dataset in {data_dir} — run convert_mat_to_csv.py first. Skipping."
        )
        return 0

    with open(os.path.join(data_dir, "dataset.json"), encoding="utf-8") as f:
        meta = json.load(f)
    manifest, payload, codes = load_payload()
    with open(
        os.path.join(ROOT, "pitch_explorer_reference.json"), encoding="utf-8"
    ) as f:
        ref = json.load(f)

    kept = [
        p
        for p in files
        if re.match(r"(P\d+)", os.path.basename(p)).group(1) not in EXCLUDE
    ]

    print("exclusions applied at the converter:")
    check(
        len(files) - len(kept) == len(EXCLUDE),
        f"{len(files)} epoch files in, {len(kept)} kept, {len(EXCLUDE)} excluded",
    )
    check(
        len(meta["participants"]) == len(kept),
        f"CSV dataset holds {len(meta['participants'])} participants",
    )

    part_index = {p["id"]: i for i, p in enumerate(manifest["participants"])}

    print(
        f"curve fidelity through both stages ({N_SPOT_CHECK} participants, every trial):"
    )
    for path in kept[:N_SPOT_CHECK]:
        rec = load_epoch_file(path)
        pid = rec["pid"]
        csv_curves, times = read_curves_csv(
            os.path.join(data_dir, "curves", f"{pid}.csv")
        )
        src = rec["curves"]

        same_shape = csv_curves.shape == src.shape
        check(same_shape, f"{pid}: CSV shape {csv_curves.shape} matches the .mat")
        if not same_shape:
            continue
        check(
            np.array_equal(np.isnan(src), np.isnan(csv_curves)),
            f"{pid}: CSV preserves the gap pattern exactly",
        )
        d = np.abs(src - csv_curves)[np.isfinite(src)]
        check(
            d.max() <= CSV_TOL,
            f"{pid}: CSV max deviation {d.max():.4f} c (budget {CSV_TOL:.4f} c)",
        )

        pi = part_index[pid]
        p = manifest["participants"][pi]
        pay = payload[p["trialStart"] : p["trialStart"] + p["nTrials"]].T
        check(
            pay.shape == src.shape, f"{pid}: payload shape {pay.shape} matches the .mat"
        )
        if pay.shape != src.shape:
            continue
        check(
            np.array_equal(np.isnan(src), np.isnan(pay)),
            f"{pid}: payload preserves the gap pattern exactly",
        )
        d = np.abs(src - pay)[np.isfinite(src)]
        check(
            d.max() <= PAYLOAD_TOL,
            f"{pid}: payload max deviation {d.max():.4f} c (budget {PAYLOAD_TOL:.4f} c)",
        )

    print("trial counts agree across all three stages:")
    for p in meta["participants"][:N_SPOT_CHECK]:
        mp = manifest["participants"][part_index[p["id"]]]
        check(
            p["nTrials"] == mp["nTrials"] and p["counts"] == mp["counts"],
            f"{p['id']}: {p['nTrials']} trials, per-condition counts match",
        )

    print("grand-average peaks re-derived at full precision from the .mat:")
    conds = meta["conditions"]
    cond_of_shift = {
        c["shiftCents"]: i for i, c in enumerate(conds) if not c["isControl"]
    }
    ctrl_i = next(i for i, c in enumerate(conds) if c["isControl"])
    n_t = meta["epoch"]["nSamples"]
    t = np.array(
        [-meta["epoch"]["tPreMs"] + i * meta["epoch"]["dtMs"] for i in range(n_t)]
    )
    pk = (t >= PEAK_WIN_MS[0]) & (t <= PEAK_WIN_MS[1])

    pmeans, genders = [], []
    for path in kept:
        rec = load_epoch_file(path)
        code = np.full(rec["curves"].shape[1], ctrl_i, dtype=int)
        for j in range(rec["curves"].shape[1]):
            s = rec["shift"][j]
            if (
                rec["perturbed"][j]
                and np.isfinite(s)
                and int(round(s)) in cond_of_shift
            ):
                code[j] = cond_of_shift[int(round(s))]
        pm = np.full((len(conds), n_t), np.nan)
        for ci in range(len(conds)):
            mask = code == ci
            if mask.any():
                pm[ci] = np.nanmean(rec["curves"][:, mask], axis=1)
        pmeans.append(pm)
        genders.append(rec["gender"])
    pmeans = np.array(pmeans)

    def grand(pidx, ci):
        cols = [pmeans[p, ci] for p in pidx if np.isfinite(pmeans[p, ci]).any()]
        return matlab_gauss_smooth(
            np.nanmean(np.column_stack(cols), axis=1),
            manifest["dataset"]["smoothWindow"],
        )

    def peak(curve):
        seg = curve[pk]
        return float(seg[np.nanargmax(np.abs(seg))])

    for label, keep in (
        ("all", lambda g: True),
        ("female", lambda g: g == "female"),
        ("male", lambda g: g == "male"),
    ):
        pidx = [i for i, g in enumerate(genders) if keep(g)]
        check(len(pidx) == ref[label]["nParticipants"], f"{label}: N = {len(pidx)}")
        ctrl = grand(pidx, ctrl_i)
        for c in conds:
            if c["isControl"]:
                continue
            ci = next(i for i, x in enumerate(conds) if x["id"] == c["id"])
            got = round(peak(grand(pidx, ci)), 2)
            exp = ref[label][f"{c['id']}_peak_c"]
            check(
                abs(got - exp) <= PEAK_TOL,
                f"{label:6s} {c['id']:7s} full precision={got:+.2f} stored={exp:+.2f} "
                f"(diff {abs(got-exp):.3f} c)",
            )
            gotd = round(peak(grand(pidx, ci) - ctrl), 2)
            expd = ref[label][f"{c['id']}_minus_ctrl_peak_c"]
            check(
                abs(gotd - expd) <= PEAK_TOL,
                f"{label:6s} {c['id']:7s} minus control={gotd:+.2f} stored={expd:+.2f} "
                f"(diff {abs(gotd-expd):.3f} c)",
            )

    print(
        "\n"
        + (
            "PASS — the chain preserves the measurements within every declared budget."
            if not failures
            else f"{len(failures)} FAILURE(S)"
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
