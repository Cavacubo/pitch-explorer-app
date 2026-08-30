#!/usr/bin/env python3
"""Convert the MATLAB epoch files into a portable CSV + JSON dataset.

It reads the per-participant files written by the MATLAB pipeline
(build_epoch_cache.m) and re-expresses the same numbers as CSV + JSON tables that
any language can read. It also applies a data-quality filter for a few participants
whose recordings hold trials with no usable F0 (DROP_NONFULL and DROP_EMPTY, see
below); all other trials pass through unchanged.

    data/cache/P001_f.mat …          ->   csv_dataset/
                                            dataset.json          experiment config
                                            trials.csv            one row per trial
                                            curves/P001.csv …     one row per trial,
                                                                  one column per time sample

Three participants who were not naive to the purpose of the experiment are
excluded here, so the dataset that leaves this script contains 28.

Usage:
    python convert_mat_to_csv.py [--cache-dir DIR] [--out DIR] [--example]
"""

from __future__ import annotations
import argparse, csv, glob, json, os, re, sys, warnings
import numpy as np
import scipy.io as sio

np.seterr(all="ignore")
# The epoch files carry a MATLAB datetime that scipy cannot name; safe to ignore,
# because every field this script reads is numeric.
warnings.filterwarnings("ignore", message='Duplicate variable name "None"')

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.normpath(
    os.path.join(
        HERE,
        "..",
        "pitch-compensation",
        "Code",
        "real_time_f0",
        "matlab",
        "data",
        "cache",
    )
)
DEFAULT_OUT = os.path.join(HERE, "csv_dataset")
EXAMPLE_OUT = os.path.join(HERE, "csv_dataset_example")

# Participants who were not naive to the purpose of the experiment. Excluded
# from the dataset this script writes; see REPORT.md. Deliberately not carried
# into dataset.json — the published dataset holds no record of who was removed.
EXCLUDE = ("P002", "P004", "P031")

# Data-quality trial filters, applied once here. Both are participant-specific;
# every other participant keeps all trials.
#
# DROP_NONFULL — drop any trial with a missing sample, keeping only trials measured
# across the whole epoch. P014's recording produced 30 fully empty and 80 partially
# tracked trials (far above anyone else), so only its 212 complete trials are kept.
#
# DROP_EMPTY — drop only fully empty trials (no F0 measured anywhere in the epoch),
# keeping partial and complete trials. Applied to the participants with a cluster of
# such dead trials; it changes the trial counts only.
DROP_NONFULL = ("P014",)
DROP_EMPTY = ("P021", "P027", "P029")

FULL_NT = 751  # samples per epoch at a 2 ms hop
CURVE_DECIMALS = 2  # cents, archival precision
EXAMPLE_TRIALS = 5  # trials per participant in the example dataset

# Colors are assigned by shift sign so any set of conditions gets a stable palette.
CONTROL_COLOR = "#7f7f7f"
DOWN_COLOR = "#3366d9"
UP_COLOR = "#d9660d"


# ------------------------------------------------------------------ loading
def load_epoch_file(path):
    """Read one participant's epoch file.

    id and gender come from the filename (Pnnn_[fm].mat); the MATLAB string
    fields inside the .mat do not round-trip through scipy, so we never rely on
    them. Everything else is numeric and read directly.
    """
    m = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
    base = os.path.basename(path)
    pid = re.match(r"(P\d+)", base).group(1)
    gender = "female" if re.search(r"_f", base) else "male"

    curves = np.atleast_2d(np.asarray(m["inEpoch"], dtype=np.float64))
    if curves.shape[0] != FULL_NT:
        curves = curves.T
    if curves.shape[0] != FULL_NT:
        sys.exit(f"{base}: expected {FULL_NT} samples per trial, got {curves.shape[0]}")

    n = curves.shape[1]

    def col(name, dtype=float, default=np.nan):
        if name not in m:
            return np.full(n, default, dtype=dtype)
        return np.atleast_1d(np.asarray(m[name])).astype(dtype)

    fs = float(np.atleast_1d(m["fs"]).ravel()[0]) if "fs" in m else float("nan")
    return dict(
        pid=pid,
        gender=gender,
        curves=curves,  # nSamples x nTrials, cents
        perturbed=col("perturbed", bool, False),
        shift=col("signedShift"),  # signed shift in cents, NaN on legacy trials
        perturb_dur_s=col("perturbDur"),  # seconds (frame count x frame duration)
        baseline_f0_hz=col("baselineF0"),
        t_grid_s=np.atleast_1d(np.asarray(m["tGrid"], dtype=float)),
        fs=fs,
    )


def _filter_trials(record, keep):
    """Restrict every per-trial field to the columns where keep is True.

    Curves, conditions and counts stay in step because the same mask is applied to
    all of them; the surviving trials are renumbered 1..k when written. Returns the
    (possibly new) record and the number of trials dropped.
    """
    dropped = int((~keep).sum())
    if not dropped:
        return record, 0
    record = dict(record)
    record["curves"] = record["curves"][:, keep]
    for k in ("perturbed", "shift", "perturb_dur_s", "baseline_f0_hz"):
        record[k] = record[k][keep]
    return record, dropped


def drop_nonfull_trials(record):
    """Keep only trials measured across the whole epoch (no missing samples)."""
    return _filter_trials(record, np.all(np.isfinite(record["curves"]), axis=0))


def drop_empty_trials(record):
    """Keep trials with at least one measured sample (drop only all-NaN trials)."""
    return _filter_trials(record, np.any(np.isfinite(record["curves"]), axis=0))


# --------------------------------------------------------------- conditions
def read_down_factor(cache_dir):
    """Audapter's downFact, read from any raw recording beside the cache.

    The epoch files store only params.sRate, which is Audapter's internal
    processing rate; the audio interface ran at sRate x downFact. Read the factor
    from a raw recording where present, and omit it otherwise.
    """
    data_root = os.path.dirname(os.path.abspath(cache_dir))
    for path in sorted(glob.glob(os.path.join(data_root, "P*_*", "*.mat")))[:1]:
        try:
            s = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
            res = s.get("results")
            trial = res[0] if isinstance(res, np.ndarray) and res.size else res
            return int(getattr(trial.params, "downFact"))
        except Exception:
            return None
    return None


def build_conditions(records):
    """Discover the conditions present: control plus each signed shift."""
    shifts = set()
    for r in records:
        vals = r["shift"][r["perturbed"]]
        shifts.update(int(round(v)) for v in vals if np.isfinite(v))
    conds = [
        {
            "id": "control",
            "label": "control",
            "shiftCents": 0,
            "isControl": True,
            "color": CONTROL_COLOR,
        }
    ]
    for s in sorted(shifts):
        conds.append(
            {
                "id": ("neg" if s < 0 else "pos") + str(abs(s)),
                "label": f"{'−' if s < 0 else '+'}{abs(s)} c",
                "shiftCents": s,
                "isControl": False,
                "color": DOWN_COLOR if s < 0 else UP_COLOR,
            }
        )
    return conds


def condition_ids(record, conds):
    """Map every trial of one participant to a condition id."""
    by_shift = {c["shiftCents"]: c["id"] for c in conds if not c["isControl"]}
    control_id = next(c["id"] for c in conds if c["isControl"])
    out = []
    for t in range(record["curves"].shape[1]):
        s = record["shift"][t]
        if record["perturbed"][t] and np.isfinite(s) and int(round(s)) in by_shift:
            out.append(by_shift[int(round(s))])
        else:
            out.append(control_id)
    return out


# ------------------------------------------------------------------ writing
def write_curves(path, curves, t_grid_ms, max_trials=None):
    """One row per trial, one column per time sample. Empty cell = no measurement."""
    n_trials = (
        curves.shape[1] if max_trials is None else min(max_trials, curves.shape[1])
    )
    fmt = "{:." + str(CURVE_DECIMALS) + "f}"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["trial_index"] + [f"{t:g}" for t in t_grid_ms])
        for j in range(n_trials):
            col = curves[:, j]
            w.writerow([j + 1] + [fmt.format(v) if np.isfinite(v) else "" for v in col])
    return n_trials


def write_trials(path, records, conds, max_trials=None):
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "participant",
                "trial_index",
                "gender",
                "condition",
                "perturbed",
                "signed_shift_cents",
                "perturb_dur_ms",
                "baseline_f0_hz",
            ]
        )
        for r in records:
            ids = condition_ids(r, conds)
            n = (
                r["curves"].shape[1]
                if max_trials is None
                else min(max_trials, r["curves"].shape[1])
            )
            for j in range(n):
                dur = r["perturb_dur_s"][j]
                bf0 = r["baseline_f0_hz"][j]
                shift = r["shift"][j]
                w.writerow(
                    [
                        r["pid"],
                        j + 1,
                        r["gender"],
                        ids[j],
                        int(bool(r["perturbed"][j])),
                        "" if not np.isfinite(shift) else int(round(shift)),
                        "" if not np.isfinite(dur) else f"{dur * 1000:.1f}",
                        "" if not np.isfinite(bf0) else f"{bf0:.2f}",
                    ]
                )
                rows += 1
    return rows


def build_dataset_json(
    records, conds, t_grid_ms, counts_by_pid, n_trials_by_pid, down_fact
):
    fs_vals = [r["fs"] for r in records if np.isfinite(r["fs"])]
    proc_hz = fs_vals[0] if fs_vals else None
    sampling = {
        "processingHz": proc_hz,
        "note": "Audapter's internal processing rate. The audio interface "
        "ran at processingHz x downFactor.",
    }
    if down_fact:
        sampling["downFactor"] = down_fact
        if proc_hz:
            sampling["hardwareHz"] = proc_hz * down_fact
    dt_ms = float(t_grid_ms[1] - t_grid_ms[0])
    return {
        "schema": "audapter-pitch-explorer-dataset/v1",
        "generatedBy": "convert_mat_to_csv.py",
        "name": "Reflexive pitch compensation (sustained /a/, ±100 c)",
        "description": "Sustained vowel /a/ with a brief pitch perturbation in "
        "auditory feedback. Curves are the produced voice (signalIn), "
        "F0 estimated with SWIPE′ and expressed in cents relative to "
        "each trial's own pre-perturbation baseline.",
        "epoch": {
            "tPreMs": float(-t_grid_ms[0]),
            "tPostMs": float(t_grid_ms[-1]),
            "dtMs": dt_ms,
            "nSamples": len(t_grid_ms),
            "baselineMs": [-200, 0],
        },
        "units": {
            "curves": "cents from baseline",
            "time": "ms relative to perturbation onset",
        },
        # Nominal design values. The duration actually measured on each trial is
        # in trials.csv as perturb_dur_ms.
        "perturbation": {"onsetMs": 0, "durationMs": 200},
        "conditions": conds,
        "genders": ["female", "male"],
        "f0EstimatorRangeHz": {"female": [150, 350], "male": [75, 180]},
        "samplingRate": sampling,
        "participants": [
            {
                "id": r["pid"],
                "gender": r["gender"],
                "nTrials": n_trials_by_pid[r["pid"]],
                "counts": counts_by_pid[r["pid"]],
                "curvesFile": f"curves/{r['pid']}.csv",
            }
            for r in records
        ],
        "totals": {
            "nParticipants": len(records),
            "nTrials": sum(n_trials_by_pid.values()),
            "nByCondition": {
                c["id"]: sum(counts_by_pid[r["pid"]][c["id"]] for r in records)
                for c in conds
            },
            "nByGender": {
                g: sum(1 for r in records if r["gender"] == g)
                for g in ("female", "male")
            },
        },
        "files": {"trials": "trials.csv", "curvesDir": "curves"},
    }


# --------------------------------------------------------------------- main
def convert(cache_dir, out_dir, max_trials=None):
    files = sorted(glob.glob(os.path.join(cache_dir, "P*_*.mat")))
    if not files:
        sys.exit(f"No epoch files found in {cache_dir}")

    kept, skipped = [], []
    for path in files:
        pid = re.match(r"(P\d+)", os.path.basename(path)).group(1)
        (skipped if pid in EXCLUDE else kept).append(path)
    if skipped:
        print(
            f"excluded {len(skipped)} participant(s) who were not naive to the experiment"
        )

    records = [load_epoch_file(p) for p in kept]
    for i, r in enumerate(records):
        if r["pid"] in DROP_NONFULL:
            records[i], dropped = drop_nonfull_trials(r)
            reason = "with missing samples"
        elif r["pid"] in DROP_EMPTY:
            records[i], dropped = drop_empty_trials(r)
            reason = "with no measured samples"
        else:
            continue
        if dropped:
            print(
                f"{r['pid']}: dropped {dropped} trial(s) {reason}, "
                f"kept {records[i]['curves'].shape[1]}"
            )
    t_grid_ms = records[0]["t_grid_s"] * 1000.0
    for r in records[1:]:
        if not np.allclose(r["t_grid_s"] * 1000.0, t_grid_ms):
            sys.exit(f"{r['pid']}: time grid differs from {records[0]['pid']}")

    conds = build_conditions(records)
    os.makedirs(os.path.join(out_dir, "curves"), exist_ok=True)

    counts_by_pid, n_trials_by_pid = {}, {}
    for r in records:
        n = write_curves(
            os.path.join(out_dir, "curves", f"{r['pid']}.csv"),
            r["curves"],
            t_grid_ms,
            max_trials,
        )
        ids = condition_ids(r, conds)[:n]
        counts_by_pid[r["pid"]] = {c["id"]: ids.count(c["id"]) for c in conds}
        n_trials_by_pid[r["pid"]] = n
        print(f"  {r['pid']} {r['gender']:6s} {n:4d} trials")

    n_rows = write_trials(
        os.path.join(out_dir, "trials.csv"), records, conds, max_trials
    )
    meta = build_dataset_json(
        records,
        conds,
        t_grid_ms,
        counts_by_pid,
        n_trials_by_pid,
        read_down_factor(cache_dir),
    )
    with open(os.path.join(out_dir, "dataset.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    assert (
        n_rows == meta["totals"]["nTrials"]
    ), "trials.csv rows disagree with the participant totals"
    return meta, n_rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE,
        help="directory holding the MATLAB epoch files (P*_*.mat)",
    )
    ap.add_argument("--out", default=DEFAULT_OUT, help="output dataset directory")
    ap.add_argument(
        "--example",
        action="store_true",
        help=f"also write a {EXAMPLE_TRIALS}-trial sample to csv_dataset_example/",
    )
    args = ap.parse_args()

    meta, n_rows = convert(args.cache_dir, args.out)
    t = meta["totals"]
    print(
        f"\nparticipants={t['nParticipants']} ({t['nByGender']['female']} female, "
        f"{t['nByGender']['male']} male)  trials={t['nTrials']}"
    )
    print(f"byCondition={t['nByCondition']}")
    print(f"trials.csv rows={n_rows}")
    size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fn in os.walk(args.out)
        for f in fn
    )
    print(f"wrote {args.out} ({size/1e6:.1f} MB)")

    if args.example:
        convert(args.cache_dir, EXAMPLE_OUT, max_trials=EXAMPLE_TRIALS)
        print(f"wrote {EXAMPLE_OUT} ({EXAMPLE_TRIALS} trials per participant)")


if __name__ == "__main__":
    main()
