#!/usr/bin/env python3
"""Validation test 1 (Python): the built payload reproduces the reference.

Reads the built pitch_explorer.html, extracts and gunzips the embedded manifest
and data, rebuilds the per-participant means from the trial curves the way the
browser does, and recomputes both headline results straight from that decoded
payload:

  * the by-sign grand-average peaks, and
  * the paired baseline-vs-analysis window test in every direction, with and
    without control correction,

then asserts they equal pitch_explorer_reference.json. This checks the exporter
end to end (quantization, packing, layout), re-deriving the values independently of the
exporter's own output path.

It also checks two non-statistical guarantees: the sample is 28
participants, and the three participants who were not naive to the experiment
appear nowhere in the built file.

Run:  python tests/test_export.py
"""

import base64, gzip, json, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from export_pitch_explorer import (
    matlab_gauss_smooth,
    direction_curves,
    paired_window_stats,
    PEAK_WIN_MS,
)

# cents. The reference comes from the same quantized payload, so the two agree
# to floating point; the budget covers accumulated rounding only.
TOL = 0.1
EXPECTED_N = 28
EXPECTED_GENDER = {"female": 16, "male": 12}
EXCLUDED_CODES = ("P002", "P004", "P031")

failures = []


def check(cond, msg):
    print(f"  [{'OK ' if cond else 'XX '}] {msg}")
    if not cond:
        failures.append(msg)


def extract_block(html, block_id):
    m = re.search(rf'id="{block_id}"[^>]*>([^<]+)</script>', html)
    assert m, f"block {block_id} not found"
    return gzip.decompress(base64.b64decode(m.group(1).strip()))


def load_payload():
    html_path = os.path.join(ROOT, "pitch_explorer.html")
    if not os.path.exists(html_path):
        sys.exit(
            "pitch_explorer.html not built yet — run export_pitch_explorer.py first."
        )
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    manifest = json.loads(extract_block(html, "manifest-b64").decode("utf-8"))
    data = extract_block(html, "data-b64")
    return html, manifest, data


def decode_trials(manifest, data):
    """Trial curves as a float array, NaN sentinel resolved."""
    ds, lay = manifest["dataset"], manifest["binary"]["layout"]
    n_t = ds["epoch"]["nSamples"]
    n_trials = manifest["totals"]["nTrials"]
    s = lay["trials"]
    arr = np.frombuffer(
        data, dtype="<i2", count=s["bytes"] // 2, offset=s["offset"]
    ).astype(float)
    arr = arr.reshape(n_trials, n_t)
    arr = np.where(arr == ds["nanSentinel"], np.nan, arr)
    c = lay["condCodes"]
    codes = np.frombuffer(data, dtype="i1", count=c["bytes"], offset=c["offset"])
    return arr, codes


def participant_means(manifest, trials, codes):
    """Average each participant's trials per condition — what the browser does."""
    ds = manifest["dataset"]
    n_t, conds = ds["epoch"]["nSamples"], ds["conditions"]
    parts = manifest["participants"]
    out = np.full((len(parts), len(conds), n_t), np.nan)
    for pi, p in enumerate(parts):
        lo, hi = p["trialStart"], p["trialStart"] + p["nTrials"]
        block, code = trials[lo:hi], codes[lo:hi]
        for ci in range(len(conds)):
            mask = code == ci
            if mask.any():
                out[pi, ci] = np.nanmean(block[mask], axis=0)
    return out


def grand_peaks(manifest, pmeans):
    ds = manifest["dataset"]
    conds, parts = ds["conditions"], manifest["participants"]
    cond_idx = {c["id"]: i for i, c in enumerate(conds)}
    ctrl_id = next(c["id"] for c in conds if c["isControl"])
    t = np.array(
        [
            -ds["epoch"]["tPreMs"] + i * ds["epoch"]["dtMs"]
            for i in range(ds["epoch"]["nSamples"])
        ]
    )
    pk = (t >= PEAK_WIN_MS[0]) & (t <= PEAK_WIN_MS[1])

    def grand(pidx, ci):
        cols = [pmeans[p, ci] for p in pidx if np.isfinite(pmeans[p, ci]).any()]
        if not cols:
            return np.full(len(t), np.nan)
        return matlab_gauss_smooth(
            np.nanmean(np.column_stack(cols), axis=1), ds["smoothWindow"]
        )

    def peak(curve):
        seg = curve[pk]
        return (
            float(seg[np.nanargmax(np.abs(seg))])
            if np.isfinite(seg).any()
            else float("nan")
        )

    out = {}
    for label, keep in (
        ("all", lambda g: True),
        ("female", lambda g: g == "female"),
        ("male", lambda g: g == "male"),
    ):
        pidx = [i for i, p in enumerate(parts) if keep(p["gender"])]
        ctrl = grand(pidx, cond_idx[ctrl_id])
        entry = {"nParticipants": len(pidx)}
        for c in conds:
            if c["isControl"]:
                continue
            curve = grand(pidx, cond_idx[c["id"]])
            entry[f"{c['id']}_peak_c"] = round(peak(curve), 2)
            entry[f"{c['id']}_minus_ctrl_peak_c"] = round(peak(curve - ctrl), 2)
        out[label] = entry
    return out, t


def main():
    html, manifest, data = load_payload()
    with open(
        os.path.join(ROOT, "pitch_explorer_reference.json"), encoding="utf-8"
    ) as f:
        ref = json.load(f)

    ds = manifest["dataset"]
    trials, codes = decode_trials(manifest, data)
    pmeans = participant_means(manifest, trials, codes)

    print("sample:")
    check(
        manifest["totals"]["nParticipants"] == EXPECTED_N,
        f"{manifest['totals']['nParticipants']} participants (expect {EXPECTED_N})",
    )
    check(
        manifest["totals"]["nByGender"] == EXPECTED_GENDER,
        f"gender split {manifest['totals']['nByGender']} (expect {EXPECTED_GENDER})",
    )
    check(
        len(manifest["participants"]) == EXPECTED_N,
        f"participant list holds {len(manifest['participants'])} entries",
    )

    print("participants excluded as not naive to the experiment:")
    ids = {p["id"] for p in manifest["participants"]}
    for code in EXCLUDED_CODES:
        check(code not in ids, f"{code} absent from the participant list")
    check(
        not any(c in html for c in EXCLUDED_CODES),
        "no excluded code appears anywhere in the built file",
    )

    print("payload carries one representation only:")
    check(
        set(manifest["binary"]["layout"]) == {"trials", "condCodes"},
        f"binary sections are {sorted(manifest['binary']['layout'])}",
    )

    print("grand-average peaks vs reference:")
    got, t = grand_peaks(manifest, pmeans)
    for label in ("all", "female", "male"):
        check(
            got[label]["nParticipants"] == ref[label]["nParticipants"],
            f"{label}: N = {got[label]['nParticipants']}",
        )
        for key, val in got[label].items():
            if not key.endswith("_peak_c"):
                continue
            check(
                abs(val - ref[label][key]) <= TOL,
                f"{label:6s} {key:28s} got={val:+.2f} ref={ref[label][key]:+.2f}",
            )

    print("paired window test vs reference:")
    conds = ds["conditions"]
    ctrl_idx = next(i for i, c in enumerate(conds) if c["isControl"])
    all_idx = list(range(len(manifest["participants"])))
    wins = ref["windowTest"]["windows"]
    for dir_mode in ("signed", "down", "up"):
        for cc in (True, False):
            key = f"{dir_mode}_{'ctrlCorrected' if cc else 'raw'}"
            curves = direction_curves(pmeans, all_idx, conds, dir_mode, cc, ctrl_idx)
            st = paired_window_stats(curves, t, wins["baseline"], wins["analysis"])
            exp = ref["windowTest"][key]
            check(
                st["n"] == exp["n"]
                and abs(st["meanDiff_c"] - exp["meanDiff_c"]) <= TOL
                and abs(st["t"] - exp["t"]) <= 0.05
                and st["df"] == exp["df"],
                f"{key:22s} mean={st['meanDiff_c']:+.2f}c t({st['df']})={st['t']:.2f} "
                f"dz={st['dz']:.2f}",
            )

    print("alternate windows reproduced from the payload (signed + control-corrected):")
    signed_cc = direction_curves(pmeans, all_idx, conds, "signed", True, ctrl_idx)
    for name, exp in ref["windowTestAlt"].items():
        st = paired_window_stats(signed_cc, t, exp["baseline"], exp["analysis"])
        check(
            st["n"] == exp["n"]
            and abs(st["meanDiff_c"] - exp["meanDiff_c"]) <= TOL
            and abs(st["t"] - exp["t"]) <= 0.05
            and st["df"] == exp["df"],
            f"{name:16s} baseline {exp['baseline']['startMs']}..{exp['baseline']['endMs']} "
            f"analysis {exp['analysis']['startMs']}..{exp['analysis']['endMs']} "
            f"mean={st['meanDiff_c']:+.2f}c t({st['df']})={st['t']:.2f}",
        )

    print("sanity — compensation opposes the shift:")
    down = ref["windowTest"]["down_ctrlCorrected"]["meanDiff_c"]
    up = ref["windowTest"]["up_ctrlCorrected"]["meanDiff_c"]
    check(down > 0, f"downward shift drives the voice up ({down:+.2f} c)")
    check(up < 0, f"upward shift drives the voice down ({up:+.2f} c)")
    check(
        ref["windowTest"]["signed_ctrlCorrected"]["meanDiff_c"] > 0,
        "signed-combined compensation is positive",
    )

    print("smoothing vs the MATLAB fixture:")
    fix_path = os.path.join(HERE, "fixtures", "gauss_fixture.csv")
    if os.path.exists(fix_path):
        with open(fix_path, encoding="utf-8") as f:
            rows = [line.split(",") for line in f.read().strip().splitlines()[1:]]
        xin = np.array([float(a) if a else np.nan for a, _ in rows])
        exp = np.array([float(b) if b else np.nan for _, b in rows])
        got = matlab_gauss_smooth(xin, 15)
        same_gaps = np.array_equal(np.isfinite(got), np.isfinite(exp))
        worst = float(np.nanmax(np.abs(got - exp))) if same_gaps else float("inf")
        check(
            same_gaps and worst < 1e-9,
            f"matlab_gauss_smooth matches smoothdata (max |err| {worst:.1e})",
        )
    else:
        print(
            "  gauss_fixture.csv not present; run tests/fixtures/make_gauss_fixture.m "
            "in MATLAB to create it"
        )

    check_reference_is_not_clobbered()

    print(
        "\n"
        + (
            "PASS — the embedded payload reproduces every reference value."
            if not failures
            else f"{len(failures)} FAILURE(S)"
        )
    )
    sys.exit(1 if failures else 0)


def check_reference_is_not_clobbered():
    """Building some other dataset must not touch the built tool's reference.

    Guards a real regression: an earlier version wrote the
    reference to a fixed filename, first beside the script and then beside the
    output. Both let a check build, of a test fixture or of the example
    dataset, replace the values the whole test suite is
    measured against, while every test kept passing against the wrong numbers.
    The reference is now named after its own output.
    """
    import hashlib, shutil, subprocess, tempfile

    print("a build of another dataset leaves the main reference alone:")
    example = os.path.join(ROOT, "csv_dataset_example")
    main_ref = os.path.join(ROOT, "pitch_explorer_reference.json")
    if not os.path.isdir(example):
        check(True, "no example dataset present, skipped")
        return

    def digest():
        return hashlib.sha256(open(main_ref, "rb").read()).hexdigest()

    before = digest()
    tmp = tempfile.mkdtemp()
    try:
        out = os.path.join(tmp, "check_build.html")
        r = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "export_pitch_explorer.py"),
                "--data-dir",
                example,
                "--out",
                out,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        check(r.returncode == 0, "the example dataset builds")
        check(digest() == before, "the main reference is byte-identical afterwards")
        check(
            os.path.exists(os.path.splitext(out)[0] + "_reference.json"),
            "that build wrote its own reference, named after its own output",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
