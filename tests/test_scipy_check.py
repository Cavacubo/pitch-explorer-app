#!/usr/bin/env python3
"""Validation test 5 (scipy): scipy verifies the engine's own statistics.

Runs node tests/test_engine.js, which exercises the engine and writes the
engine's per-participant difference vectors (analysis-window mean minus
baseline-window mean, one value per participant) to tests/engine_vectors.json.
For every vector this script recomputes the paired test with
scipy.stats.ttest_1samp and scipy.stats.t.ppf and compares t, p, dz and the
95% CI against the values the engine computed with jStat. The vectors for the
default windows and the alternate windows are also compared against
pitch_explorer_reference.json, which the Python build wrote from its own
independent aggregation.

Skips (exit 0) when Node.js is not on PATH.

Run:  python tests/test_scipy_check.py
"""

import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

failures = 0


def check(cond, msg):
    global failures
    if cond:
        print(f"  [OK ] {msg}")
    else:
        failures += 1
        print(f"  [XX ] {msg}")


def close(a, b, tol):
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def rel_close(a, b, rel):
    return (
        math.isfinite(a)
        and math.isfinite(b)
        and abs(a - b) <= rel * max(abs(a), abs(b))
    )


def main():
    node = shutil.which("node")
    if node is None:
        print("Node.js not found on PATH; skipping the scipy check.")
        return 0

    print("running node tests/test_engine.js for the difference vectors:")
    run = subprocess.run(
        [node, os.path.join(HERE, "test_engine.js")], capture_output=True, text=True
    )
    check(run.returncode == 0, "test_engine.js passes and writes the vectors")
    if run.returncode != 0:
        sys.stdout.write(run.stdout + run.stderr)
        print("\n1 FAILURE(S)")
        return 1

    with open(os.path.join(HERE, "engine_vectors.json"), encoding="utf-8") as f:
        vectors = json.load(f)
    with open(
        os.path.join(ROOT, "pitch_explorer_reference.json"), encoding="utf-8"
    ) as f:
        ref = json.load(f)

    default_keys = [
        f"{d}_{c}" for d in ("signed", "down", "up") for c in ("ctrlCorrected", "raw")
    ]
    alt_keys = [f"alt_{name}" for name in ref["windowTestAlt"]]
    check(
        sorted(vectors) == sorted(default_keys + alt_keys),
        f"the dump holds all {len(default_keys) + len(alt_keys)} difference vectors",
    )

    print("scipy on the engine's difference vectors vs the engine's statistics:")
    for key, v in sorted(vectors.items()):
        d = np.asarray(v["diffs"], dtype=float)
        res = stats.ttest_1samp(d, 0.0)
        df = d.size - 1
        se = d.std(ddof=1) / np.sqrt(d.size)
        tc = stats.t.ppf(0.975, df)
        ci_lo, ci_hi = d.mean() - tc * se, d.mean() + tc * se
        good = (
            v["n"] == d.size
            and v["df"] == df
            and close(v["t"], float(res.statistic), 1e-9)
            and rel_close(v["p"], float(res.pvalue), 1e-6)
            and close(v["dz"], float(d.mean() / d.std(ddof=1)), 1e-9)
            and close(v["ciLo"], float(ci_lo), 1e-7)
            and close(v["ciHi"], float(ci_hi), 1e-7)
        )
        check(
            good,
            f"{key}: t = {res.statistic:.6f}, p = {res.pvalue:.3g}, "
            f"CI [{ci_lo:.4f}, {ci_hi:.4f}]",
        )

    print("scipy on the engine's vectors vs the reference (Python aggregation):")
    for key in default_keys:
        d = np.asarray(vectors[key]["diffs"], dtype=float)
        res = stats.ttest_1samp(d, 0.0)
        df = d.size - 1
        se = d.std(ddof=1) / np.sqrt(d.size)
        tc = stats.t.ppf(0.975, df)
        r = ref["windowTest"][key]
        good = (
            r["n"] == d.size
            and r["df"] == df
            and close(float(d.mean()), r["meanDiff_c"], 0.005)
            and close(float(res.statistic), r["t"], 0.005)
            and rel_close(float(res.pvalue), r["p"], 1e-6)
            and close(float(d.mean() / d.std(ddof=1)), r["dz"], 0.005)
            and close(float(d.mean() - tc * se), r["ci_c"][0], 0.005)
            and close(float(d.mean() + tc * se), r["ci_c"][1], 0.005)
        )
        check(
            good,
            f"{key} matches windowTest ({r['meanDiff_c']:+.2f} c, "
            f"t({r['df']}) = {r['t']:.2f})",
        )
    for name, r in ref["windowTestAlt"].items():
        d = np.asarray(vectors[f"alt_{name}"]["diffs"], dtype=float)
        res = stats.ttest_1samp(d, 0.0)
        good = (
            r["n"] == d.size
            and close(float(d.mean()), r["meanDiff_c"], 0.005)
            and close(float(res.statistic), r["t"], 0.005)
            and rel_close(float(res.pvalue), r["p"], 1e-6)
        )
        check(
            good,
            f"alt_{name} matches windowTestAlt ({r['meanDiff_c']:+.2f} c, "
            f"t({r['df']}) = {r['t']:.2f})",
        )

    if failures:
        print(f"\n{failures} FAILURE(S)")
        return 1
    print(
        "\nPASS — scipy reproduces the engine's statistics from the engine's own vectors."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
