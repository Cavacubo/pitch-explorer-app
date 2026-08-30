"use strict";
/* Pitch Explorer engine: payload decode, data model, statistics, and the
   study-specific aggregation. export_pitch_explorer.py inlines this file into
   the built HTML, and tests/test_engine.js loads it directly, so the browser
   and the Node test run the same code. The t-distribution comes from
   jStat, inlined before this file in the built HTML and provided as a global
   by the Node test. */

/* ============================================================= decode layer */
function b64ToBytes(b64) {
  const bin = atob(b64.trim());
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
async function gunzip(bytes) {
  if (typeof DecompressionStream === "undefined")
    throw new Error(
      "This browser lacks DecompressionStream; use a recent Chrome, Edge, Firefox or Safari.",
    );
  const ds = new DecompressionStream("gzip");
  const buf = await new Response(
    new Blob([bytes]).stream().pipeThrough(ds),
  ).arrayBuffer();
  return buf;
}

/* ============================================================= data model */
const M = {}; // manifest
const D = {}; // decoded typed arrays + derived indices
let SENT = -32768;

function v16(x) {
  return x === SENT ? NaN : x;
}

function buildModel(manifest, dataBuf) {
  Object.assign(M, manifest);
  const ds = M.dataset;
  const lay = M.binary.layout;
  SENT = ds.nanSentinel;
  D.conds = ds.conditions;
  D.nConds = ds.conditions.length;
  D.condIndexById = {};
  ds.conditions.forEach((c, i) => (D.condIndexById[c.id] = i));
  D.ctrlIdx = ds.conditions.findIndex((c) => c.isControl);
  D.nT = ds.epoch.nSamples;
  D.parts = M.participants;
  D.nParts = M.participants.length;
  D.totalTrials = M.totals.nTrials;
  // typed-array views over the one binary blob: per-trial curves only.
  // Participant and grand averages are derived from these on demand.
  D.trials = new Int16Array(dataBuf, lay.trials.offset, lay.trials.bytes / 2);
  D.condCodes = new Int8Array(
    dataBuf,
    lay.condCodes.offset,
    lay.condCodes.bytes,
  );
  // time grid in ms
  const e = ds.epoch;
  D.t = Array.from({ length: D.nT }, (_, i) => -e.tPreMs + i * e.dtMs);
  D.dtMs = e.dtMs;
  D.tMin = D.t[0];
  D.tMax = D.t[D.nT - 1];
  D.smoothWin = ds.smoothWindow;
  D.pkWin = ds.peakWindowMs;
  D.pertMs = ds.perturbation;
  D.presets = ds.analysisWindowPresets || [];
  D.defaultWindows = ds.defaultWindows;
  D.pmeanCache = new Map();
}

// accessor: sample k of global trial gt
function trialVal(gt, k) {
  return v16(D.trials[gt * D.nT + k]);
}

// global trial indices of one participant in one condition, minus any excluded
function participantTrials(pi, ci, excluded) {
  const p = D.parts[pi];
  const out = [];
  for (let j = 0; j < p.nTrials; j++) {
    const gt = p.trialStart + j;
    if (D.condCodes[gt] === ci && !(excluded && excluded.has(gt))) out.push(gt);
  }
  return out;
}

/* Mean curve of one participant in one condition, averaged over that
   participant's trials. Computed on demand so trial exclusions reach the
   grand average. */
function participantMean(pi, ci, excluded) {
  const key = excluded && excluded.size ? null : pi * D.nConds + ci;
  if (key !== null && D.pmeanCache.has(key)) return D.pmeanCache.get(key);
  const sel = participantTrials(pi, ci, excluded);
  if (!sel.length) return null;
  const nT = D.nT;
  const sum = new Float64Array(nT);
  const cnt = new Int32Array(nT);
  for (const gt of sel) {
    const base = gt * nT;
    for (let k = 0; k < nT; k++) {
      const v = v16(D.trials[base + k]);
      if (isFinite(v)) {
        sum[k] += v;
        cnt[k]++;
      }
    }
  }
  const out = new Float64Array(nT);
  for (let k = 0; k < nT; k++) out[k] = cnt[k] > 0 ? sum[k] / cnt[k] : NaN;
  if (key !== null) D.pmeanCache.set(key, out);
  return out;
}

/* ============================================================= math */
function gaussSmooth(x, win) {
  // Port of MATLAB smoothdata(x,'gaussian',win,'omitnan'), matching the Python
  // reference in export_pitch_explorer.py.
  const n = x.length;
  const sigma = win / 5;
  const half = (win - 1) / 2;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const lo = Math.max(Math.ceil(i - half), 0);
    const hi = Math.min(Math.floor(i + half), n - 1);
    let s = 0;
    let acc = 0;
    for (let j = lo; j <= hi; j++) {
      const xj = x[j];
      if (!isFinite(xj)) continue;
      const w = Math.exp(-0.5 * ((j - i) / sigma) ** 2);
      s += w;
      acc += w * xj;
    }
    out[i] = s > 0 ? acc / s : NaN;
  }
  return out;
}
function meanSemAcross(cols, nT) {
  // cols: array of Float arrays (length nT). Per-sample omitnan mean + SEM.
  const mean = new Float64Array(nT);
  const sem = new Float64Array(nT);
  for (let k = 0; k < nT; k++) {
    let s = 0;
    let ss = 0;
    let c = 0;
    for (const col of cols) {
      const v = col[k];
      if (isFinite(v)) {
        s += v;
        ss += v * v;
        c++;
      }
    }
    if (c > 0) {
      const m = s / c;
      mean[k] = m;
      sem[k] =
        c > 1 ? Math.sqrt(Math.max(ss - (s * s) / c, 0) / (c - 1) / c) : NaN;
    } else {
      mean[k] = NaN;
      sem[k] = NaN;
    }
  }
  return { mean, sem };
}
// t-distribution from jStat: two-sided p and two-sided critical value
function tTwoSidedP(t, df) {
  if (!isFinite(t) || df <= 0) return NaN;
  return 2 * jStat.studentt.cdf(-Math.abs(t), df);
}
function tCrit(df, p2 = 0.05) {
  if (df <= 0) return NaN;
  return jStat.studentt.inv(1 - p2 / 2, df);
}
function oneSampleT(vals) {
  const v = vals.filter(isFinite);
  const n = v.length;
  if (n < 2)
    return {
      n,
      mean: n ? v[0] : NaN,
      t: NaN,
      df: n - 1,
      p: NaN,
      d: NaN,
      ciLo: NaN,
      ciHi: NaN,
    };
  const m = v.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) * (b - m), 0) / (n - 1));
  const se = sd / Math.sqrt(n);
  const t = m / se;
  const df = n - 1;
  const tc = tCrit(df, 0.05);
  return {
    n,
    mean: m,
    sd,
    t,
    df,
    p: tTwoSidedP(t, df),
    d: m / sd,
    ciLo: m - tc * se,
    ciHi: m + tc * se,
  };
}

/* ============================================================= aggregation */
// sample indices falling inside a [startMs, endMs] window
function windowIdx(startMs, endMs) {
  const out = [];
  for (let k = 0; k < D.nT; k++)
    if (D.t[k] >= startMs && D.t[k] <= endMs) out.push(k);
  return out;
}
// mean of a curve over those samples, ignoring gaps
function windowMean(curve, idx) {
  let s = 0;
  let c = 0;
  for (const k of idx) {
    const v = curve[k];
    if (isFinite(v)) {
      s += v;
      c++;
    }
  }
  return c > 0 ? s / c : NaN;
}

// Explore: trial-level mean±SEM for a panel's selection
function exploreAggregate(state) {
  const ci = D.condIndexById[state.shiftCondId];
  const sel = []; // global trial indices
  for (let pi = 0; pi < D.nParts; pi++) {
    if (!state.included.has(D.parts[pi].id)) continue;
    for (const gt of participantTrials(pi, ci, state.excluded)) sel.push(gt);
  }
  const nT = D.nT;
  const sum = new Float64Array(nT);
  const ssq = new Float64Array(nT);
  const cnt = new Int32Array(nT);
  for (const gt of sel) {
    const base = gt * nT;
    for (let k = 0; k < nT; k++) {
      const v = v16(D.trials[base + k]);
      if (isFinite(v)) {
        sum[k] += v;
        ssq[k] += v * v;
        cnt[k]++;
      }
    }
  }
  const mean = new Float64Array(nT);
  const sem = new Float64Array(nT);
  for (let k = 0; k < nT; k++) {
    const c = cnt[k];
    if (c > 0) {
      const m = sum[k] / c;
      mean[k] = m;
      sem[k] =
        c > 1
          ? Math.sqrt(Math.max(ssq[k] - (sum[k] * sum[k]) / c, 0) / (c - 1) / c)
          : NaN;
    } else {
      mean[k] = NaN;
      sem[k] = NaN;
    }
  }
  const parts = [];
  for (let pi = 0; pi < D.nParts; pi++) {
    if (!state.included.has(D.parts[pi].id)) continue;
    if (participantTrials(pi, ci, state.excluded).length) parts.push(pi);
  }
  return {
    t: D.t,
    mean: gaussSmooth(mean, D.smoothWin),
    sem: gaussSmooth(sem, D.smoothWin),
    nTrials: sel.length,
    sel,
    parts,
    condIdx: ci,
  };
}

// Group average: grand mean±SEM per condition, averaged ACROSS participants
// (N = participants, so no single speaker dominates)
function groupAggregate(included, excluded) {
  const pidx = [];
  for (let pi = 0; pi < D.nParts; pi++)
    if (included.has(D.parts[pi].id)) pidx.push(pi);
  let nTrials = 0;
  for (const pi of pidx)
    for (let ci = 0; ci < D.nConds; ci++)
      nTrials += participantTrials(pi, ci, excluded).length;
  const perCond = D.conds.map((c, ci) => {
    const cols = [];
    for (const pi of pidx) {
      const m = participantMean(pi, ci, excluded);
      if (m) cols.push(m);
    }
    const ms = meanSemAcross(cols, D.nT);
    return {
      mean: gaussSmooth(ms.mean, D.smoothWin),
      sem: gaussSmooth(ms.sem, D.smoothWin),
      n: cols.length,
    };
  });
  return { t: D.t, perCond, parts: pidx, nParticipants: pidx.length, nTrials };
}

/* One curve per participant for the window statistics.
   dir: "signed" pools every shifted condition with up-shift responses inverted,
   so compensation is positive whichever way the feedback moved (the
   sign-normalization convention, Miller et al. 2023). "up"/"down" take a single
   condition. correctControl subtracts that participant's own control curve
   first, isolating the response from baseline drift. */
function directionCurves(pidx, dir, correctControl, excluded) {
  const out = [];
  for (const pi of pidx) {
    const ctrl = correctControl
      ? participantMean(pi, D.ctrlIdx, excluded)
      : null;
    if (correctControl && !ctrl) continue;
    const pieces = [];
    D.conds.forEach((c, ci) => {
      if (c.isControl) return;
      if (dir === "down" && c.shiftCents > 0) return;
      if (dir === "up" && c.shiftCents < 0) return;
      const m = participantMean(pi, ci, excluded);
      if (!m) return;
      const flip = dir === "signed" ? -Math.sign(c.shiftCents) : 1;
      const cur = new Float64Array(D.nT);
      for (let k = 0; k < D.nT; k++)
        cur[k] = (ctrl ? m[k] - ctrl[k] : m[k]) * flip;
      pieces.push(cur);
    });
    if (!pieces.length) continue;
    if (pieces.length === 1) {
      out.push({ pi, curve: pieces[0] });
      continue;
    }
    const avg = new Float64Array(D.nT);
    for (let k = 0; k < D.nT; k++) {
      let s = 0;
      let c = 0;
      for (const p of pieces) {
        if (isFinite(p[k])) {
          s += p[k];
          c++;
        }
      }
      avg[k] = c > 0 ? s / c : NaN;
    }
    out.push({ pi, curve: avg });
  }
  return out;
}

/* Whether subtracting the control curve can change anything for this direction.
   Each pooled condition contributes (curve - control) x flip, so the control
   term carries a factor equal to the sum of the flips. With an equal and
   opposite pair pooled under sign-normalization that sum is zero and the
   correction cancels exactly, so the correction has no effect for a
   sign-normalized pair; the note explains the unchanged result to the user. */
function controlCorrectionCancels(dir) {
  let sum = 0;
  D.conds.forEach((c) => {
    if (c.isControl) return;
    if (dir === "down" && c.shiftCents > 0) return;
    if (dir === "up" && c.shiftCents < 0) return;
    sum += dir === "signed" ? -Math.sign(c.shiftCents) : 1;
  });
  return sum === 0;
}

/* Paired comparison of two windows on the same units.
   Each unit contributes one difference (analysis-window mean minus
   baseline-window mean); the test asks whether those differences differ from
   zero. A window spans many samples, so each window is summarized by its mean —
   the peak would be biased upward by noise and is reported separately. */
function pairedWindowStats(curves, baseWin, analysisWin) {
  const bIdx = windowIdx(baseWin.startMs, baseWin.endMs);
  const aIdx = windowIdx(analysisWin.startMs, analysisWin.endMs);
  const diffs = [];
  for (const c of curves) {
    const b = windowMean(c.curve ? c.curve : c, bIdx);
    const a = windowMean(c.curve ? c.curve : c, aIdx);
    if (isFinite(a) && isFinite(b)) diffs.push(a - b);
  }
  const s = oneSampleT(diffs);
  return {
    n: s.n,
    meanDiff: s.mean,
    sd: s.sd,
    t: s.t,
    df: s.df,
    p: s.p,
    dz: s.d,
    ciLo: s.ciLo,
    ciHi: s.ciHi,
    diffs,
    nBaseSamples: bIdx.length,
    nAnalysisSamples: aIdx.length,
  };
}

/* peak (extremum by |value|) of a curve within a ms window */
function peakInWindow(t, y, startMs, endMs) {
  let bi = -1;
  let bv = -Infinity;
  for (let k = 0; k < t.length; k++) {
    if (t[k] < startMs || t[k] > endMs) continue;
    const v = y[k];
    if (isFinite(v) && Math.abs(v) > bv) {
      bv = Math.abs(v);
      bi = k;
    }
  }
  return bi < 0 ? null : { t: t[bi], v: y[bi] };
}

/* Loaded two ways: as an inlined browser script, where the top-level
   declarations are shared with the UI script, and as a CommonJS module by the
   Node test. */
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    b64ToBytes,
    gunzip,
    M,
    D,
    v16,
    buildModel,
    trialVal,
    participantTrials,
    participantMean,
    gaussSmooth,
    meanSemAcross,
    tTwoSidedP,
    tCrit,
    oneSampleT,
    windowIdx,
    windowMean,
    exploreAggregate,
    groupAggregate,
    directionCurves,
    controlCorrectionCancels,
    pairedWindowStats,
    peakInWindow,
  };
}
