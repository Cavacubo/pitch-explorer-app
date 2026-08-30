#!/usr/bin/env python3
"""Render the validation figure used in the technical report.

Reproduces the tool's Group Average view (by-sign grand average, all genders)
straight from the CSV dataset, using the same algorithm as the tool:
per-participant condition means, then the mean across participants, then SEM,
then gaussian smoothing. Saves figures/grand_average_by_sign.png.

Uses the CSV, the same input the built tool reads, so the figure matches the tool.
"""

import os
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from export_pitch_explorer import (
    load_dataset,
    matlab_gauss_smooth,
    PEAK_WIN_MS,
    DEFAULT_DATA,
    SMOOTH_WIN,
    DEFAULT_WINDOWS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)

BASE_C, ANA_C = "#3366d9", "#639922"

meta, parts, curves, codes = load_dataset(DEFAULT_DATA)
conds = meta["conditions"]
n_t = meta["epoch"]["nSamples"]
tms = np.array(
    [-meta["epoch"]["tPreMs"] + i * meta["epoch"]["dtMs"] for i in range(n_t)]
)
n_p = len(parts)
n_trials = sum(p["nTrials"] for p in parts)
pert = meta["perturbation"]

# per-participant, per-condition mean curves
pm = np.full((n_p, len(conds), n_t), np.nan)
for pi, (arr, code) in enumerate(zip(curves, codes)):
    for ci in range(len(conds)):
        mask = code == ci
        if mask.any():
            pm[pi, ci] = np.nanmean(arr[mask], axis=0)


def grand(ci):
    mu = pm[:, ci, :].T  # nT x nP
    M = np.nanmean(mu, axis=1)
    Nt = np.sum(~np.isnan(mu), axis=1)
    SEM = np.nanstd(mu, axis=1, ddof=0) / np.sqrt(np.maximum(Nt, 1))
    return matlab_gauss_smooth(M, SMOOTH_WIN), matlab_gauss_smooth(SEM, SMOOTH_WIN)


grands = {c["id"]: grand(i) for i, c in enumerate(conds)}
cond_idx = {c["id"]: i for i, c in enumerate(conds)}
pk = (tms >= PEAK_WIN_MS[0]) & (tms <= PEAK_WIN_MS[1])


def peak(curve):
    seg = np.where(pk, curve, np.nan)
    i = np.nanargmax(np.abs(seg))
    return tms[i], curve[i]


fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6.6), sharex=True)
bw, aw = DEFAULT_WINDOWS["baseline"], DEFAULT_WINDOWS["analysis"]
for ax in (ax1, ax2):
    ax.axvspan(
        pert["onsetMs"],
        pert["onsetMs"] + pert["durationMs"],
        color="0.85",
        alpha=0.6,
        lw=0,
    )
    ax.axvspan(bw["startMs"], bw["endMs"], color=BASE_C, alpha=0.16, lw=0)
    ax.axvspan(aw["startMs"], aw["endMs"], color=ANA_C, alpha=0.18, lw=0)
    ax.axvline(0, color="0.35", lw=1.3)
    ax.axhline(0, ls=":", color="0.6", lw=1)
    ax.grid(True, color="0.93")

# top: each condition against its own baseline
for c in conds:
    M, S = grands[c["id"]]
    ax1.fill_between(
        tms, M - 1.96 * S, M + 1.96 * S, color=c["color"], alpha=0.12, lw=0
    )
    ax1.fill_between(tms, M - S, M + S, color=c["color"], alpha=0.25, lw=0)
    n = int(np.sum(np.any(~np.isnan(pm[:, cond_idx[c["id"]], :]), axis=1)))
    ax1.plot(tms, M, color=c["color"], lw=2, label=f"{c['label']} (N={n})")
    if not c["isControl"]:
        pt, pv = peak(M)
        ax1.plot(pt, pv, "o", color=c["color"], ms=4)
        ax1.annotate(
            f"{pv:+.2f} c",
            (pt, pv),
            textcoords="offset points",
            xytext=(6, 4),
            color=c["color"],
            fontweight="bold",
        )
ax1.fill_between(
    [], [], color="0.85", alpha=0.6, label=f"perturbation ({pert['durationMs']} ms)"
)
ax1.fill_between(
    [],
    [],
    color=BASE_C,
    alpha=0.16,
    label=f"baseline window ({bw['startMs']} to {bw['endMs']} ms)",
)
ax1.fill_between(
    [],
    [],
    color=ANA_C,
    alpha=0.18,
    label=f"analysis window ({aw['startMs']} to {aw['endMs']} ms)",
)
ax1.set_ylabel("Cents from baseline")
ax1.set_title(
    f"Grand average by sign · all genders · N = {n_p} participants · "
    f"{n_trials} trials · SWIPE′\nMean ± SEM across participants; "
    f"peak labels from the {PEAK_WIN_MS[0]}–{PEAK_WIN_MS[1]} ms window"
)
ax1.legend(loc="upper left", fontsize=8, ncol=2)

# bottom: perturbed minus control
ctrlM, ctrlS = grands[next(c["id"] for c in conds if c["isControl"])]
for c in conds:
    if c["isControl"]:
        continue
    M, S = grands[c["id"]]
    dM = M - ctrlM
    dS = np.sqrt(S**2 + ctrlS**2)
    ax2.fill_between(
        tms, dM - 1.96 * dS, dM + 1.96 * dS, color=c["color"], alpha=0.12, lw=0
    )
    ax2.fill_between(tms, dM - dS, dM + dS, color=c["color"], alpha=0.25, lw=0)
    ax2.plot(tms, dM, color=c["color"], lw=2, label=f"{c['label']} − control")
    pt, pv = peak(dM)
    ax2.plot(pt, pv, "o", color=c["color"], ms=4)
    ax2.annotate(
        f"{pv:+.2f} c",
        (pt, pv),
        textcoords="offset points",
        xytext=(6, 4),
        color=c["color"],
        fontweight="bold",
    )
ax2.set_ylabel("Δ cents (group − control)")
ax2.set_xlabel("Time relative to perturbation onset (ms)")
ax2.set_xlim(tms[0], tms[-1])
ax2.legend(loc="upper left", fontsize=8)

fig.tight_layout()
path = os.path.join(OUT, "grand_average_by_sign.png")
fig.savefig(path, dpi=130)
print("wrote", path)

print(f"Validation peaks (all genders, N = {n_p}):")
for c in conds:
    if c["isControl"]:
        continue
    M, _ = grands[c["id"]]
    pt, pv = peak(M)
    print(f"  {c['id']}: peak {pv:+.2f} c at {pt:.0f} ms")
