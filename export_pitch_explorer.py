#!/usr/bin/env python3
"""Build pitch_explorer.html from the portable CSV dataset.

Input is the CSV + JSON dataset written by convert_mat_to_csv.py; this script reads
only the CSV and JSON. Output is a single self-contained HTML file with the
data embedded, plus pitch_explorer_reference.json for the tests.

    csv_dataset/  ->  pitch_explorer.html + pitch_explorer_reference.json

Only ONE representation of the data is embedded: the per-trial curves, at the
dataset's full time resolution. Per-participant and grand averages are computed
in the browser from those curves. A second, pre-averaged copy could diverge from the
curves, and participant or trial exclusions would not reach it.

The embedded representation is general (a versioned manifest plus a
compact binary blob), so the same tool can display any dataset that follows the
documented input contract. See DATA_FORMAT.md.

Usage:
    python export_pitch_explorer.py [--data-dir DIR] [--out FILE]
"""

from __future__ import annotations
import argparse, base64, csv, gzip, io, json, os, sys
import numpy as np

np.seterr(all="ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(HERE, "csv_dataset")
NAN_I16 = -32768  # sentinel for NaN inside int16 curves
SMOOTH_WIN = 15  # gaussian smoothing window (matches MATLAB)

# Selectable presets for the analysis window. The window itself is typed by the
# user; these only fill the boxes.
ANALYSIS_WINDOW_PRESETS = [
    {
        "id": "miller",
        "label": "Miller 100–250 ms",
        "startMs": 100,
        "endMs": 250,
        "cite": "Miller et al. 2023",
    },
    {
        "id": "peak",
        "label": "peak 50–500 ms",
        "startMs": 50,
        "endMs": 500,
        "cite": "Franken et al. 2018",
    },
]
# Where the window boxes start on load.
DEFAULT_WINDOWS = {
    "baseline": {"startMs": -200, "endMs": 0},
    "analysis": {"startMs": 100, "endMs": 250},
}
# Window for the peak annotation (time-to-peak convention, Franken et al. 2018).
PEAK_WIN_MS = (50, 500)


# ------------------------------------------------------------- dataset input
def load_dataset(data_dir):
    """Read dataset.json, trials.csv and every curves/<pid>.csv.

    Validates the input contract documented in DATA_FORMAT.md and stops with a
    plain message rather than guessing, so a dataset prepared elsewhere fails
    where the problem is instead of somewhere later in the build.
    """
    meta_path = os.path.join(data_dir, "dataset.json")
    if not os.path.exists(meta_path):
        sys.exit(f"No dataset.json in {data_dir} — run convert_mat_to_csv.py first.")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    conds = meta["conditions"]
    n_control = sum(1 for c in conds if c.get("isControl"))
    if n_control != 1:
        sys.exit(
            f"dataset.json: exactly one condition must have isControl true, found {n_control}"
        )
    cond_index = {c["id"]: i for i, c in enumerate(conds)}

    ep = meta["epoch"]
    n_samples = ep["nSamples"]
    expected_t = np.array([-ep["tPreMs"] + i * ep["dtMs"] for i in range(n_samples)])

    # condition per trial, keyed by (participant, trial_index)
    trials_path = os.path.join(data_dir, meta["files"]["trials"])
    if not os.path.exists(trials_path):
        sys.exit(f"Missing {trials_path}, named by dataset.json files.trials")
    trial_cond = {}
    with open(trials_path, newline="", encoding="utf-8") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            cid = row["condition"]
            if cid not in cond_index:
                sys.exit(
                    f"{trials_path} line {line_no}: condition '{cid}' is not declared in "
                    f"dataset.json (declared: {', '.join(cond_index)})"
                )
            trial_cond[(row["participant"], int(row["trial_index"]))] = cond_index[cid]

    parts, curves, codes = [], [], []
    for p in meta["participants"]:
        path = os.path.join(data_dir, p["curvesFile"])
        if not os.path.exists(path):
            sys.exit(
                f"{p['id']}: missing {path}, named by dataset.json participants[].curvesFile"
            )
        with open(path, newline="", encoding="utf-8") as f:
            rd = csv.reader(f)
            header = next(rd)
            if len(header) - 1 != n_samples:
                sys.exit(
                    f"{path}: {len(header)-1} time columns, dataset.json epoch says {n_samples}"
                )
            got_t = np.array([float(x) for x in header[1:]])
            if not np.allclose(got_t, expected_t):
                bad = int(np.argmax(np.abs(got_t - expected_t)))
                sys.exit(
                    f"{path}: time grid does not match dataset.json epoch. Column {bad+2} "
                    f"is {got_t[bad]:g} ms, expected {expected_t[bad]:g} ms"
                )
            rows, idx = [], []
            for row in rd:
                idx.append(int(row[0]))
                rows.append([float(v) if v else np.nan for v in row[1:]])
        arr = np.asarray(rows, dtype=np.float64)  # nTrials x nSamples
        if arr.shape[0] != p["nTrials"]:
            sys.exit(f"{path}: {arr.shape[0]} trials, dataset.json says {p['nTrials']}")
        missing = [i for i in idx if (p["id"], i) not in trial_cond]
        if missing:
            sys.exit(
                f"{path}: {len(missing)} trial(s) have no row in {meta['files']['trials']} "
                f"(first missing trial_index: {missing[0]})"
            )
        curves.append(arr)
        codes.append(np.array([trial_cond[(p["id"], i)] for i in idx], dtype=np.int8))
        parts.append(dict(p))
    if not any(np.isfinite(c).any() for c in curves):
        sys.exit(
            "no usable pitch values: every curve in the dataset is empty (all cells are blank)"
        )
    return meta, parts, curves, codes


# --------------------------------------------------------------- quantization
def quantize_i16(arr):
    """Round to nearest cent, clip, NaN -> sentinel; return little-endian int16."""
    q = np.where(np.isfinite(arr), np.clip(np.round(arr), -32000, 32000), NAN_I16)
    return q.astype("<i2")


# ------------------------------------------------------- reference computation
def matlab_gauss_smooth(x, win=SMOOTH_WIN):
    """Port of MATLAB smoothdata(x,'gaussian',win,'omitnan'): gaussian kernel
    (sigma = win/5), NaN-aware renormalization, window shrinks at the edges.
    Kept identical in the JS engine so the tool matches this reference."""
    x = np.asarray(x, float)
    n = len(x)
    sigma = win / 5.0
    half = (win - 1) / 2.0
    finite = np.isfinite(x)
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(int(np.ceil(i - half)), 0)
        hi = min(int(np.floor(i + half)), n - 1)
        idx = np.arange(lo, hi + 1)
        w = np.exp(-0.5 * ((idx - i) / sigma) ** 2) * finite[idx]
        s = w.sum()
        if s > 0:
            out[i] = np.nansum(w * np.where(finite[idx], x[idx], 0.0)) / s
    return out


def participant_means(curves_q, codes, n_conds, n_samples):
    """Per-participant, per-condition mean curve, from the QUANTIZED trial curves.

    Computed the same way the browser computes it, so the reference reflects what
    the tool will actually show.
    """
    out = np.full((len(curves_q), n_conds, n_samples), np.nan)
    for pi, (arr, code) in enumerate(zip(curves_q, codes)):
        for ci in range(n_conds):
            mask = code == ci
            if mask.any():
                out[pi, ci] = np.nanmean(arr[mask], axis=0)
    return out


def grand_average(pmeans, part_idx, cond_idx, smooth_win):
    """Grand mean ACROSS participants for one condition (N = participants)."""
    cols = [
        pmeans[p, cond_idx] for p in part_idx if np.isfinite(pmeans[p, cond_idx]).any()
    ]
    if not cols:
        return np.full(pmeans.shape[2], np.nan)
    return matlab_gauss_smooth(np.nanmean(np.column_stack(cols), axis=1), smooth_win)


def direction_curves(pmeans, part_idx, conds, dir_mode, correct_control, ctrl_idx):
    """One curve per participant, mirroring directionCurves() in the app."""
    out = []
    for pi in part_idx:
        ctrl = pmeans[pi, ctrl_idx] if correct_control else None
        if correct_control and not np.isfinite(ctrl).any():
            continue
        pieces = []
        for ci, c in enumerate(conds):
            if c["isControl"]:
                continue
            if dir_mode == "down" and c["shiftCents"] > 0:
                continue
            if dir_mode == "up" and c["shiftCents"] < 0:
                continue
            m = pmeans[pi, ci]
            if not np.isfinite(m).any():
                continue
            flip = -np.sign(c["shiftCents"]) if dir_mode == "signed" else 1
            pieces.append(((m - ctrl) if ctrl is not None else m) * flip)
        if not pieces:
            continue
        out.append(
            pieces[0] if len(pieces) == 1 else np.nanmean(np.vstack(pieces), axis=0)
        )
    return out


def paired_window_stats(curves, t_ms, baseline, analysis):
    """Paired comparison of two window means, mirroring pairedWindowStats()."""
    from scipy import stats

    b = (t_ms >= baseline["startMs"]) & (t_ms <= baseline["endMs"])
    a = (t_ms >= analysis["startMs"]) & (t_ms <= analysis["endMs"])
    diffs = []
    for cur in curves:
        bm = np.nanmean(cur[b]) if np.isfinite(cur[b]).any() else np.nan
        am = np.nanmean(cur[a]) if np.isfinite(cur[a]).any() else np.nan
        if np.isfinite(am) and np.isfinite(bm):
            diffs.append(am - bm)
    d = np.asarray(diffs, dtype=float)
    n = d.size
    if n < 2:
        return {"n": int(n)}
    m = float(d.mean())
    sd = float(d.std(ddof=1))
    se = sd / np.sqrt(n)
    t = m / se
    df = n - 1
    tc = float(stats.t.ppf(0.975, df))
    return {
        "n": int(n),
        "meanDiff_c": round(m, 2),
        "t": round(float(t), 2),
        "df": int(df),
        "p": float(2 * stats.t.sf(abs(t), df)),
        "dz": round(m / sd, 2),
        "ci_c": [round(m - tc * se, 2), round(m + tc * se, 2)],
    }


def build_reference(parts, pmeans, conds, t_ms, smooth_win):
    """By-sign grand-average peaks for all/female/male -> reference JSON."""
    cond_idx = {c["id"]: i for i, c in enumerate(conds)}
    ctrl_id = next(c["id"] for c in conds if c["isControl"])
    shifted = [c["id"] for c in conds if not c["isControl"]]
    pk = (t_ms >= PEAK_WIN_MS[0]) & (t_ms <= PEAK_WIN_MS[1])

    def peak(curve):
        seg = curve[pk]
        return (
            float(seg[np.nanargmax(np.abs(seg))])
            if np.isfinite(seg).any()
            else float("nan")
        )

    ref = {}
    for label, keep in (
        ("all", lambda g: True),
        ("female", lambda g: g == "female"),
        ("male", lambda g: g == "male"),
    ):
        pidx = [i for i, p in enumerate(parts) if keep(p["gender"])]
        ctrl = grand_average(pmeans, pidx, cond_idx[ctrl_id], smooth_win)
        entry = {"nParticipants": len(pidx)}
        for cid in shifted:
            curve = grand_average(pmeans, pidx, cond_idx[cid], smooth_win)
            entry[f"{cid}_peak_c"] = round(peak(curve), 2)
            entry[f"{cid}_minus_ctrl_peak_c"] = round(peak(curve - ctrl), 2)
        ref[label] = entry

    # Paired window test at the default windows, for the whole sample. The app
    # and the Node port must reproduce these numbers from the same payload.
    ctrl_idx = cond_idx[ctrl_id]
    all_idx = list(range(len(parts)))
    ref["windowTest"] = {}
    for dir_mode in ("signed", "down", "up"):
        for cc in (True, False):
            curves = direction_curves(pmeans, all_idx, conds, dir_mode, cc, ctrl_idx)
            key = f"{dir_mode}_{'ctrlCorrected' if cc else 'raw'}"
            ref["windowTest"][key] = paired_window_stats(
                curves, t_ms, DEFAULT_WINDOWS["baseline"], DEFAULT_WINDOWS["analysis"]
            )
    ref["windowTest"]["windows"] = DEFAULT_WINDOWS

    # Alternate windows (signed + control-corrected), so tests can prove that a
    # changed baseline changes the result, that a custom analysis window is
    # computed correctly, and that the peak preset (50-500 ms) is right.
    signed_cc = direction_curves(pmeans, all_idx, conds, "signed", True, ctrl_idx)
    alt_windows = {
        # A post-onset baseline (in the response) proves the baseline
        # box is wired: a pre-onset baseline is ~0 cents, so any pre-onset choice
        # barely moves the result, while this one flips it well away.
        "baselineShift": {
            "baseline": {"startMs": 300, "endMs": 500},
            "analysis": {"startMs": 100, "endMs": 250},
        },
        "analysisCustom": {
            "baseline": {"startMs": -200, "endMs": 0},
            "analysis": {"startMs": 300, "endMs": 500},
        },
        "peakPreset": {
            "baseline": {"startMs": -200, "endMs": 0},
            "analysis": {"startMs": 50, "endMs": 500},
        },
    }
    ref["windowTestAlt"] = {}
    for name, w in alt_windows.items():
        st = paired_window_stats(signed_cc, t_ms, w["baseline"], w["analysis"])
        st["baseline"] = w["baseline"]
        st["analysis"] = w["analysis"]
        ref["windowTestAlt"][name] = st
    return ref


# ------------------------------------------------------------------- packing
def gzip_b64(raw_bytes):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw_bytes)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_payload(data_dir):
    meta, parts, curves, codes = load_dataset(data_dir)
    conds = meta["conditions"]
    n_conds = len(conds)
    n_stored = meta["epoch"]["nSamples"]
    dt = meta["epoch"]["dtMs"]
    t_stored = np.array([-meta["epoch"]["tPreMs"] + i * dt for i in range(n_stored)])

    trials_q, cursor = [], 0
    for pi, arr in enumerate(curves):
        q = quantize_i16(arr)  # nTrials x nStored
        trials_q.append(q.reshape(-1))  # trial-major
        parts[pi]["trialStart"] = cursor
        cursor += arr.shape[0]
    total_trials = cursor

    data_blob_parts, layout, off = [], {}, 0
    for name, blob, dtype in (
        ("trials", np.concatenate(trials_q).tobytes(), "int16"),
        ("condCodes", np.concatenate(codes).astype(np.int8).tobytes(), "int8"),
    ):
        layout[name] = {"offset": off, "bytes": len(blob), "dtype": dtype}
        data_blob_parts.append(blob)
        off += len(blob)
    data_blob = b"".join(data_blob_parts)

    # Reference is computed on the STORED (quantized) curves, i.e. on
    # exactly what the browser will read.
    curves_q = [
        np.where(
            q.reshape(-1, n_stored) == NAN_I16,
            np.nan,
            q.reshape(-1, n_stored).astype(float),
        )
        for q in trials_q
    ]
    pmeans = participant_means(curves_q, codes, n_conds, n_stored)
    smooth_win = odd_window(SMOOTH_WIN * meta["epoch"]["dtMs"], dt)
    reference = build_reference(parts, pmeans, conds, t_stored, smooth_win)

    manifest = {
        "schema": "audapter-pitch-explorer/v2",
        "generatedBy": "export_pitch_explorer.py",
        "dataset": {
            "name": meta["name"],
            "description": meta["description"],
            "epoch": {
                "tPreMs": meta["epoch"]["tPreMs"],
                "tPostMs": meta["epoch"]["tPostMs"],
                "dtMs": dt,
                "nSamples": n_stored,
                "baselineMs": meta["epoch"]["baselineMs"],
            },
            "units": meta["units"],
            "perturbation": meta["perturbation"],
            "conditions": conds,
            "genders": meta["genders"],
            "samplingRate": meta.get("samplingRate"),
            "analysisWindowPresets": ANALYSIS_WINDOW_PRESETS,
            "defaultWindows": DEFAULT_WINDOWS,
            "peakWindowMs": list(PEAK_WIN_MS),
            "smoothWindow": smooth_win,
            "nanSentinel": NAN_I16,
        },
        "participants": [
            {
                "id": p["id"],
                "gender": p["gender"],
                "nTrials": p["nTrials"],
                "counts": p["counts"],
                "trialStart": p["trialStart"],
            }
            for p in parts
        ],
        "totals": meta["totals"],
        "binary": {
            "encoding": "gzip+base64",
            "layout": layout,
            "condOrder": [c["id"] for c in conds],
        },
    }
    assert (
        manifest["totals"]["nTrials"] == total_trials
    ), "trial count disagrees with dataset.json"
    return manifest, data_blob, reference


def odd_window(ms, dt):
    w = max(3, int(round(ms / dt)))
    return w - 1 if w % 2 == 0 else w


# --------------------------------------------------------------------- emit
def main():
    ap = argparse.ArgumentParser(
        description="Build the Pitch Explorer HTML from the CSV dataset."
    )
    ap.add_argument(
        "--data-dir",
        default=DEFAULT_DATA,
        help="dataset directory written by convert_mat_to_csv.py",
    )
    ap.add_argument("--template", default=os.path.join(HERE, "app_template.html"))
    ap.add_argument("--out", default=os.path.join(HERE, "pitch_explorer.html"))
    args = ap.parse_args()

    manifest, data_blob, reference = build_payload(args.data_dir)
    manifest_b64 = gzip_b64(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    data_b64 = gzip_b64(data_blob)

    # Named after the output it describes, so one build never overwrites
    # another build's reference. A fixed name would let a check build of another
    # dataset overwrite the built tool's values.
    ref_path = os.path.splitext(os.path.abspath(args.out))[0] + "_reference.json"
    with open(ref_path, "w", encoding="utf-8") as f:
        json.dump(reference, f, indent=2, ensure_ascii=False)

    t = manifest["totals"]
    print(
        f"participants={t['nParticipants']} ({t['nByGender']['female']} female, "
        f"{t['nByGender']['male']} male)  trials={t['nTrials']}"
    )
    print(f"byCondition={t['nByCondition']}")
    print(
        f"stored curves: {manifest['dataset']['epoch']['nSamples']} samples at "
        f"{manifest['dataset']['epoch']['dtMs']} ms"
    )
    print(
        f"payload: manifest={len(manifest_b64)/1e6:.2f} MB  data={len(data_b64)/1e6:.2f} MB"
    )
    print("reference grand-average peaks:")
    for label in ("all", "female", "male"):
        r = reference[label]
        peaks = "  ".join(
            f"{k.replace('_peak_c','')}={v:+.2f}c"
            for k, v in r.items()
            if k.endswith("_peak_c") and not k.endswith("_minus_ctrl_peak_c")
        )
        print(f"  {label:6s} N={r['nParticipants']:2d}  {peaks}")
    wt = reference["windowTest"]["signed_ctrlCorrected"]
    print(
        f"reference window test (signed, default windows): "
        f"mean diff {wt['meanDiff_c']:+.2f} c, t({wt['df']}) = {wt['t']:.2f}, dz = {wt['dz']:.2f}"
    )

    if not os.path.exists(args.template):
        sys.exit(f"\ntemplate not found: {args.template}")
    with open(args.template, encoding="utf-8") as f:
        html = f.read()
    # Inline the stylesheet, the statistics library, the engine and the app, which
    # the template holds as placeholder bodies inside their <style>/<script> tags.
    # The Node test loads the same engine.js, so the browser and the test run one
    # implementation. Each entry names the closing tag the source must not contain,
    # so an inlined body can never break out of its surrounding element.
    inlines = {
        "/*__APP_CSS__*/": (os.path.join(HERE, "app.css"), "</style"),
        "/*__JSTAT_JS__*/": (os.path.join(HERE, "vendor", "jstat.min.js"), "</script"),
        "/*__ENGINE_JS__*/": (os.path.join(HERE, "engine.js"), "</script"),
        "/*__APP_JS__*/": (os.path.join(HERE, "app.js"), "</script"),
    }
    for marker, (path, close_tag) in inlines.items():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if close_tag in src or "<!--" in src:
            sys.exit(
                f"{os.path.basename(path)} contains text that would break "
                f"the surrounding {close_tag[1:]} tag"
            )
        if marker not in html:
            sys.exit(f"template is missing the {marker} placeholder")
        html = html.replace(marker, src)
    html = html.replace("__MANIFEST_B64__", manifest_b64).replace(
        "__DATA_B64__", data_b64
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nwrote {args.out} ({os.path.getsize(args.out)/1e6:.2f} MB)")
    print(f"wrote {os.path.basename(ref_path)}")


if __name__ == "__main__":
    main()
