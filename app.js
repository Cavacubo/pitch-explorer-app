"use strict";
/* ============================================================= selection helpers */
/* The participant checkboxes are the single source of truth for who is in the
   aggregate. The All / Female / Male buttons are shortcuts that set those
   checkboxes; they hold no filter state of their own, so the buttons and the
   list always agree. */
function selectionKind(included) {
  const eq = (pred) => {
    const ids = M.participants.filter(pred).map((p) => p.id);
    return (
      ids.length > 0 &&
      ids.length === included.size &&
      ids.every((id) => included.has(id))
    );
  };
  if (eq(() => true)) return "all";
  if (eq((p) => p.gender === "female")) return "female";
  if (eq((p) => p.gender === "male")) return "male";
  return null;
}
function selectionName(included) {
  return selectionKind(included) || "custom";
}
// "16 female, 12 male" for the aggregated participant indices
function genderText(pidx) {
  let f = 0;
  let m = 0;
  for (const pi of pidx) D.parts[pi].gender === "female" ? f++ : m++;
  if (!f && !m) return "none selected";
  const bits = [];
  if (f) bits.push(f + " female");
  if (m) bits.push(m + " male");
  return bits.join(", ");
}

/* ============================================================= chart renderer */
function niceRange(lo, hi) {
  if (!isFinite(lo) || !isFinite(hi)) {
    lo = -10;
    hi = 10;
  }
  if (lo === hi) {
    lo -= 5;
    hi += 5;
  }
  const span = hi - lo;
  const step = niceStep(span / 6);
  return {
    lo: Math.floor(lo / step) * step,
    hi: Math.ceil(hi / step) * step,
    step,
  };
}
function niceStep(x) {
  const p = Math.pow(10, Math.floor(Math.log10(x)));
  const f = x / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
}

function drawChart(canvas, spec) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || spec.width || 640;
  const cssH = spec.height || 300;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const mL = 54;
  const mR = 16;
  const mT = 14;
  const mB = 40;
  const W = cssW - mL - mR;
  const H = cssH - mT - mB;

  // ranges
  const xr = spec.xRange;
  let ylo = Infinity;
  let yhi = -Infinity;
  for (const s of spec.series) {
    for (let k = 0; k < s.t.length; k++) {
      const m = s.mean[k];
      const b = s.ci ? s.ci[k] : s.sem ? 1.96 * s.sem[k] : 0;
      if (isFinite(m)) {
        ylo = Math.min(ylo, m - (isFinite(b) ? b : 0));
        yhi = Math.max(yhi, m + (isFinite(b) ? b : 0));
      }
    }
  }
  const pad = (yhi - ylo) * 0.12 || 5;
  const yr = niceRange(ylo - pad, yhi + pad);
  const X = (v) => mL + ((v - xr[0]) / (xr[1] - xr[0])) * W;
  const Y = (v) => mT + ((yr.hi - v) / (yr.hi - yr.lo)) * H;

  // shaded regions: perturbation, plus whichever analysis windows are set
  for (const b of spec.bands || []) {
    const x0 = X(Math.max(b.from, xr[0]));
    const x1 = X(Math.min(b.to, xr[1]));
    if (x1 <= x0) continue;
    ctx.fillStyle = b.fill;
    ctx.fillRect(x0, mT, x1 - x0, H);
    if (b.edge) {
      ctx.strokeStyle = b.edge;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, mT);
      ctx.lineTo(x0, mT + H);
      ctx.moveTo(x1, mT);
      ctx.lineTo(x1, mT + H);
      ctx.stroke();
    }
  }

  // gridlines + y ticks
  ctx.strokeStyle = "#eef0f5";
  ctx.fillStyle = "#8b90a3";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let v = yr.lo; v <= yr.hi + 1e-9; v += yr.step) {
    ctx.beginPath();
    ctx.moveTo(mL, Y(v));
    ctx.lineTo(mL + W, Y(v));
    ctx.stroke();
    ctx.fillText((v > 0 ? "+" : "") + Math.round(v * 100) / 100, mL - 7, Y(v));
  }
  // x ticks every 500 ms
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let v = Math.ceil(xr[0] / 500) * 500; v <= xr[1]; v += 500) {
    ctx.strokeStyle = "#eef0f5";
    ctx.beginPath();
    ctx.moveTo(X(v), mT);
    ctx.lineTo(X(v), mT + H);
    ctx.stroke();
    ctx.fillStyle = "#8b90a3";
    ctx.fillText(v, X(v), mT + H + 6);
  }
  // y = 0 guide
  ctx.strokeStyle = "#b9bed0";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(mL, Y(0));
  ctx.lineTo(mL + W, Y(0));
  ctx.stroke();
  ctx.setLineDash([]);
  // perturbation onset: a solid, labelled line, since every window is read against it
  ctx.strokeStyle = "#5a5f73";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(X(0), mT);
  ctx.lineTo(X(0), mT + H);
  ctx.stroke();
  ctx.fillStyle = "#5a5f73";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText("onset", X(0) + 4, mT + 2);

  const runs = (t, y) => {
    const r = [];
    let cur = null;
    for (let k = 0; k < t.length; k++) {
      if (isFinite(y[k])) {
        if (!cur) {
          cur = [k];
        }
        cur.push(k);
      } else if (cur) {
        r.push(cur);
        cur = null;
      }
    }
    if (cur) r.push(cur);
    return r;
  };

  // bands then lines
  for (const s of spec.series) {
    const band = (mult, alpha) => {
      ctx.fillStyle = hexA(s.color, alpha);
      for (const run of runs(s.t, s.mean)) {
        ctx.beginPath();
        for (const k of run) {
          const b = (isFinite(s.sem[k]) ? s.sem[k] : 0) * mult;
          const x = X(s.t[k]);
          const yv = Y(s.mean[k] + b);
          k === run[0] ? ctx.moveTo(x, yv) : ctx.lineTo(x, yv);
        }
        for (let i = run.length - 1; i >= 0; i--) {
          const k = run[i];
          const b = (isFinite(s.sem[k]) ? s.sem[k] : 0) * mult;
          ctx.lineTo(X(s.t[k]), Y(s.mean[k] - b));
        }
        ctx.closePath();
        ctx.fill();
      }
    };
    if (s.sem) {
      band(1.96, 0.12);
      band(1.0, 0.25);
    }
  }
  for (const s of spec.series) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.width || 2;
    ctx.setLineDash(s.dash || []);
    for (const run of runs(s.t, s.mean)) {
      ctx.beginPath();
      run.forEach((k, i) => {
        const x = X(s.t[k]);
        const yv = Y(s.mean[k]);
        i ? ctx.lineTo(x, yv) : ctx.moveTo(x, yv);
      });
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }
  // annotations
  for (const a of spec.annotations || []) {
    ctx.fillStyle = a.color;
    ctx.beginPath();
    ctx.arc(X(a.x), Y(a.y), 3.5, 0, 7);
    ctx.fill();
    ctx.font = "600 13px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(a.text, X(a.x) + 6, Y(a.y) - 4);
  }
  // axis titles
  ctx.fillStyle = "#5a5f73";
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillText(spec.xlabel, mL + W / 2, cssH - 6);
  ctx.save();
  ctx.translate(14, mT + H / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText(spec.ylabel, 0, 0);
  ctx.restore();
}
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* ============================================================= app shell */
const state = {
  view: "explore",
  explore: { mode: "single", panels: [] },
  group: null,
};

function defaultWindows() {
  const d = D.defaultWindows || {
    baseline: { startMs: -200, endMs: 0 },
    analysis: { startMs: 100, endMs: 250 },
  };
  return {
    baseline: Object.assign({}, d.baseline),
    analysis: Object.assign({}, d.analysis),
  };
}
function newPanel(shift) {
  return {
    shiftCondId: shift,
    unit: "participant",
    win: defaultWindows(),
    included: new Set(D_ids()),
    excluded: new Set(),
    expanded: new Set(),
  };
}
function newGroupState() {
  return {
    dir: "both",
    correctControl: true,
    win: defaultWindows(),
    included: new Set(D_ids()),
    excluded: new Set(),
  };
}
function D_ids() {
  return (M.participants || []).map((p) => p.id);
}
function shiftedConds() {
  return D.conds.filter((c) => !c.isControl);
}

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function plural(n, word) {
  return n + " " + word + (n === 1 ? "" : "s");
}

document.getElementById("nav-explore").onclick = () => {
  state.view = "explore";
  syncNav();
  render();
};
document.getElementById("nav-group").onclick = () => {
  state.view = "group";
  syncNav();
  render();
};
function syncNav() {
  document
    .getElementById("nav-explore")
    .classList.toggle("active", state.view === "explore");
  document
    .getElementById("nav-group")
    .classList.toggle("active", state.view === "group");
}

function render() {
  const app = document.getElementById("app");
  app.innerHTML = "";
  if (state.view === "explore") renderExplore(app);
  else renderGroup(app);
}

/* ------------------------------------------- analysis windows (shared) */
const BASE_FILL = "rgba(51,102,217,.18)";
const BASE_EDGE = "rgba(51,102,217,.55)";
const ANA_FILL = "rgba(99,153,34,.20)";
const ANA_EDGE = "rgba(99,153,34,.60)";
const POOLED = "#a21caf"; // the signed-combined compensation line on the Group Average plot

function chartBands(win) {
  return [
    {
      from: D.pertMs.onsetMs,
      to: D.pertMs.onsetMs + D.pertMs.durationMs,
      fill: "rgba(140,140,140,.16)",
    },
    {
      from: win.baseline.startMs,
      to: win.baseline.endMs,
      fill: BASE_FILL,
      edge: BASE_EDGE,
    },
    {
      from: win.analysis.startMs,
      to: win.analysis.endMs,
      fill: ANA_FILL,
      edge: ANA_EDGE,
    },
  ];
}

/* Four number boxes defining the two windows, plus optional extra controls.
   Values are clamped to the epoch and ordered, so a typo cannot put the chart
   into a state the data does not cover. */
function windowControls(win, onChange, extras) {
  const bar = el("div", "winbar");
  let syncPresets = () => {};
  function numPair(key, label, swatch) {
    const g = el("div", "grp");
    const cap = el("span", "cap");
    cap.innerHTML = `<span class="sw" style="background:${swatch}"></span>${label}`;
    g.appendChild(cap);
    const pair = el("div", "pair");
    const mk = (side) => {
      const i = el("input");
      i.type = "number";
      i.step = "10";
      i.value = win[key][side];
      i.setAttribute("aria-label", `${label} ${side}`);
      i.onchange = () => {
        const v = parseFloat(i.value);
        if (!isFinite(v)) {
          i.classList.add("bad");
          return;
        }
        i.classList.remove("bad");
        win[key][side] = Math.max(D.tMin, Math.min(D.tMax, v));
        // the box just typed keeps its value; the other one gives way, so
        // raising the start above the end widens the window and keeps them ordered
        if (win[key].startMs > win[key].endMs) {
          if (side === "startMs") win[key].endMs = win[key].startMs;
          else win[key].startMs = win[key].endMs;
        }
        pair.querySelectorAll("input").forEach((inp, n) => {
          inp.value = n === 0 ? win[key].startMs : win[key].endMs;
        });
        syncPresets();
        onChange();
      };
      return i;
    };
    pair.appendChild(mk("startMs"));
    pair.appendChild(el("span", "to", "to"));
    pair.appendChild(mk("endMs"));
    g.appendChild(pair);
    return g;
  }
  bar.appendChild(numPair("baseline", "Baseline window (ms)", BASE_EDGE));
  const winset = el("div", "winset");
  winset.appendChild(numPair("analysis", "Analysis window (ms)", ANA_EDGE));
  bar.appendChild(winset);

  if (D.presets.length) {
    const g = el("div", "grp");
    g.appendChild(el("span", "cap", "Presets"));
    const box = el("div", "pill");
    const btns = [];
    D.presets.forEach((p) => {
      const b = el("button", null, p.label);
      if (p.cite) b.title = p.cite;
      b.onclick = () => {
        win.analysis.startMs = p.startMs;
        win.analysis.endMs = p.endMs;
        bar
          .querySelectorAll(".grp")[1]
          .querySelectorAll("input")
          .forEach((inp, n) => {
            inp.value = n === 0 ? p.startMs : p.endMs;
          });
        syncPresets();
        onChange();
      };
      btns.push([b, p]);
      box.appendChild(b);
    });
    syncPresets = () => {
      btns.forEach(([b, p]) => {
        const on =
          win.analysis.startMs === p.startMs && win.analysis.endMs === p.endMs;
        b.classList.toggle("active", on);
        b.style.background = on ? "var(--indigo)" : "";
      });
    };
    syncPresets();
    g.appendChild(box);
    winset.appendChild(g);
  }
  (extras || []).forEach((e) => bar.appendChild(e));
  return bar;
}

function selectCtl(label, options, value, onPick) {
  const g = el("div", "grp");
  g.appendChild(el("span", "cap", label));
  const s = el("select");
  options.forEach(([v, txt]) => {
    const o = el("option", null, txt);
    o.value = v;
    s.appendChild(o);
  });
  s.value = value;
  s.onchange = () => onPick(s.value);
  g.appendChild(s);
  return g;
}
function checkCtl(label, checked, onPick) {
  const g = el("div", "grp");
  g.appendChild(el("span", "cap", " "));
  const l = el("label", "chk");
  const c = el("input");
  c.type = "checkbox";
  c.checked = checked;
  c.onchange = () => onPick(c.checked);
  l.appendChild(c);
  l.appendChild(el("span", null, label));
  g.appendChild(l);
  return g;
}

const fmtP = (p) =>
  isFinite(p)
    ? p < 0.001
      ? "< .001"
      : "= " + p.toFixed(3).replace(/^0/, "")
    : "—";

/* Statistics readout for the paired window comparison. Every figure names what
   it measures and its unit. */
function renderWindowStats(box, st, win, unitLabel, peak) {
  box.innerHTML = "";
  const add = (big, small) => {
    const s = el("div", "s");
    s.appendChild(el("b", null, big));
    s.appendChild(el("span", null, small));
    box.appendChild(s);
  };
  add(
    isFinite(st.meanDiff)
      ? (st.meanDiff > 0 ? "+" : "") + st.meanDiff.toFixed(2) + " c"
      : "—",
    `mean difference · analysis − baseline`,
  );
  add(
    isFinite(st.t) ? `t(${st.df}) = ${st.t.toFixed(2)}` : "—",
    `paired t · ${plural(st.n, unitLabel)}`,
  );
  add(fmtP(st.p).replace(/^= /, ""), "p (two-sided)");
  add(
    isFinite(st.dz) ? `d₂ = ${st.dz.toFixed(2)}`.replace("₂", "z") : "—",
    isFinite(st.ciLo)
      ? `95% CI [${st.ciLo.toFixed(2)}, ${st.ciHi.toFixed(2)}] cents`
      : "effect size",
  );
  if (peak)
    add(
      (peak.v > 0 ? "+" : "") + peak.v.toFixed(2) + " c",
      `peak in analysis window · at ${Math.round(peak.t)} ms`,
    );
}

function windowNote(win, unitLabel, n, extra) {
  return (
    `Baseline ${win.baseline.startMs} to ${win.baseline.endMs} ms, analysis ` +
    `${win.analysis.startMs} to ${win.analysis.endMs} ms, both relative to perturbation onset. ` +
    `Each ${unitLabel} contributes one difference (mean over the analysis window minus mean over ` +
    `the baseline window). ` +
    (extra || "")
  );
}

/* --------------------------------------------------- Explore view */
function renderExplore(app) {
  const intro = el("p", "intro");
  intro.innerHTML =
    "<b>Single aggregate</b> shows one average. <b>Compare two</b> shows two independently " +
    "configured charts side by side.<br>On each chart, choose the shift and select participants.<br>The " +
    "All / Female / Male buttons tick whole groups in the list, and the checkboxes fine-tune from there.<br>" +
    "Include or exclude individual trials by clicking on thumbnails.<br>The average updates from the current selection.";
  app.appendChild(intro);

  const tb = el("div", "toolbar");
  tb.appendChild(el("span", "label", "mode:"));
  const seg = el("div", "seg");
  const b1 = el(
    "button",
    state.explore.mode === "single" ? "active" : "",
    "Single aggregate",
  );
  const b2 = el(
    "button",
    state.explore.mode === "compare" ? "active" : "",
    "Compare two",
  );
  b1.onclick = () => {
    state.explore.mode = "single";
    render();
  };
  b2.onclick = () => {
    state.explore.mode = "compare";
    render();
  };
  seg.appendChild(b1);
  seg.appendChild(b2);
  tb.appendChild(seg);
  app.appendChild(tb);

  const wrap = el(
    "div",
    "panels" + (state.explore.mode === "compare" ? " compare" : ""),
  );
  const n = state.explore.mode === "compare" ? 2 : 1;
  for (let i = 0; i < n; i++)
    wrap.appendChild(buildExplorePanel(state.explore.panels[i], i));
  app.appendChild(wrap);
  for (let i = 0; i < n; i++) state.explore.panels[i]._refresh(); // draw now that cards are in the DOM
}

function condColor(id) {
  return D.conds[D.condIndexById[id]].color;
}
function condLabel(id) {
  return D.conds[D.condIndexById[id]].label;
}

function buildExplorePanel(ps, index) {
  const card = el("div", "card");
  const badgeColor = index === 0 ? "var(--indigo)" : "var(--orange)";
  const title = el("div", "panel-title");
  const badge = el("div", "badge", String.fromCharCode(65 + index));
  badge.style.background = badgeColor;
  const titleTxt = el("span");
  titleTxt.textContent = `Group ${String.fromCharCode(65 + index)} · ${condLabel(ps.shiftCondId)} shift`;
  title.appendChild(badge);
  title.appendChild(titleTxt);
  card.appendChild(title);

  // controls
  const row = el("div", "ctl-row");
  const shiftCtl = el("div", "ctl");
  shiftCtl.appendChild(el("span", "cap", "shift"));
  const shiftPill = el("div", "pill");
  D.conds
    .filter((c) => !c.isControl)
    .forEach((c) => {
      const b = el("button", ps.shiftCondId === c.id ? "active" : "", c.label);
      if (ps.shiftCondId === c.id) b.style.background = c.color;
      b.onclick = () => {
        ps.shiftCondId = c.id;
        refresh();
        titleTxt.textContent = `Group ${String.fromCharCode(65 + index)} · ${c.label} shift`;
        shiftPill.querySelectorAll("button").forEach((x) => {
          x.classList.remove("active");
          x.style.background = "";
        });
        b.classList.add("active");
        b.style.background = c.color;
        sec.refreshThumbs();
      }; // open thumbnail boxes must follow the new shift
      shiftPill.appendChild(b);
    });
  shiftCtl.appendChild(shiftPill);
  row.appendChild(shiftCtl);

  const genderCtl = el("div", "ctl");
  genderCtl.appendChild(el("span", "cap", "participants"));
  const gp = genderPill(ps, badgeColor);
  genderCtl.appendChild(gp.node);
  row.appendChild(genderCtl);
  card.appendChild(row);

  // chart
  const cw = el("div", "chart-wrap");
  const canvas = el("canvas", "chart");
  cw.appendChild(canvas);
  card.appendChild(cw);
  const legendHost = el("div");
  card.appendChild(legendHost);
  const cap = el("div", "caption");
  card.appendChild(cap);
  // analysis windows + statistics
  const unitCtl = selectCtl(
    "Test unit",
    [
      ["participant", "Participant"],
      ["trial", "Trial (df inflated)"],
    ],
    ps.unit,
    (v) => {
      ps.unit = v;
      refresh();
    },
  );
  card.appendChild(windowControls(ps.win, () => refresh(), [unitCtl]));
  const stats = el("div", "stats");
  card.appendChild(stats);
  const note = el("div", "winnote");
  card.appendChild(note);

  // export
  const btns = el("div", "btns");
  const pngB = el("button", null, "Export PNG");
  pngB.onclick = () => exportPNG(canvas, `explore_${ps.shiftCondId}`);
  const csvB = el("button", null, "Export CSV");
  csvB.onclick = () => exportExploreCSV(ps);
  btns.appendChild(pngB);
  btns.appendChild(csvB);
  card.appendChild(btns);

  // participant sidebar
  const sec = participantsSection(ps, true);
  card.appendChild(sec.node);
  ps._syncSel = () => {
    gp.sync();
    sec.sync();
  };

  let lastAgg = null;
  function refresh() {
    const agg = exploreAggregate(ps);
    lastAgg = agg;
    ps._agg = agg;
    const color = condColor(ps.shiftCondId);
    legendHost.innerHTML = "";
    legendHost.appendChild(exploreLegend(color));
    const pkAnn = peakInWindow(agg.t, agg.mean, D.pkWin[0], D.pkWin[1]);
    drawChart(canvas, {
      height: 300,
      xRange: [D.tMin, D.tMax],
      bands: chartBands(ps.win),
      xlabel: "Time relative to perturbation onset (ms)",
      ylabel: "Cents from baseline",
      series: [{ t: agg.t, mean: agg.mean, sem: agg.sem, color }],
      annotations: pkAnn
        ? [
            {
              x: pkAnn.t,
              y: pkAnn.v,
              text: (pkAnn.v > 0 ? "+" : "") + pkAnn.v.toFixed(2) + " c",
              color,
            },
          ]
        : [],
    });
    cap.textContent =
      `${plural(agg.parts.length, "participant")} (${genderText(agg.parts)}), ` +
      `${plural(agg.nTrials, "perturbed trial")} at ${condLabel(ps.shiftCondId)}.`;

    // units for the paired test: one curve per participant, or one per trial
    const units =
      ps.unit === "participant"
        ? agg.parts
            .map((pi) => ({
              curve: participantMean(pi, agg.condIdx, ps.excluded),
            }))
            .filter((u) => u.curve)
        : agg.sel.map((gt) => {
            const c = new Float64Array(D.nT);
            for (let k = 0; k < D.nT; k++) c[k] = trialVal(gt, k);
            return { curve: c };
          });
    const st = pairedWindowStats(units, ps.win.baseline, ps.win.analysis);
    const pkWin = peakInWindow(
      agg.t,
      agg.mean,
      ps.win.analysis.startMs,
      ps.win.analysis.endMs,
    );
    renderWindowStats(stats, st, ps.win, ps.unit, pkWin);
    note.textContent = windowNote(
      ps.win,
      ps.unit,
      st.n,
      ps.unit === "trial"
        ? "Trials are nested within participants, so the trial-level degrees of freedom are inflated, so report the participant-level test."
        : "",
    );
  }
  ps._refresh = refresh;
  return card; // caller draws after the card is in the DOM (so clientWidth is valid)
}

function windowLegendHtml() {
  return (
    `<span class="k"><span class="box" style="background:rgba(140,140,140,.25)"></span>perturbation (${D.pertMs.durationMs} ms)</span>` +
    `<span class="k"><span class="box" style="background:${BASE_FILL};border:1px solid ${BASE_EDGE}"></span>baseline window</span>` +
    `<span class="k"><span class="box" style="background:${ANA_FILL};border:1px solid ${ANA_EDGE}"></span>analysis window</span>`
  );
}
function exploreLegend(color) {
  color = color || "#3366d9";
  const l = el("div", "legend");
  l.innerHTML =
    `<span class="k"><span class="swatch" style="border-top-color:${color}"></span>mean</span>` +
    `<span class="k"><span class="box" style="background:${hexA(color, 0.28)}"></span>± 1 SEM (≈68% CI)</span>` +
    `<span class="k"><span class="box" style="background:${hexA(color, 0.14)}"></span>± 1.96 SEM (95% CI)</span>` +
    windowLegendHtml();
  return l;
}

/* Included / total trials of the current shift for one participant. This is
   trial-level (how many thumbnails are checked in), independent of whether the
   participant row itself is checked. One helper drives both the row count and
   the thumbnail-box header, so the two stay in sync. */
function shiftTrialCounts(ps, p) {
  const ci = D.condIndexById[ps.shiftCondId];
  const start = p.trialStart;
  let total = 0;
  let inc = 0;
  for (let j = 0; j < p.nTrials; j++) {
    const gt = start + j;
    if (D.condCodes[gt] !== ci) continue;
    total++;
    if (!ps.excluded.has(gt)) inc++;
  }
  return { total, inc };
}
function trialCountLabel(inc, total) {
  return inc === total ? `${total}` : `${inc} of ${total}`;
}

/* One participant row. withTrials adds the expander for per-trial thumbnails,
   which needs a single condition to show and so belongs to the Explore panels.
   Checkbox changes update the set, then ps._syncSel() repaints every selection
   control (rows, master checkbox, gender buttons) from that one set. */
function participantRow(ps, p, pi, withTrials) {
  const row = el("div", "prow" + (ps.included.has(p.id) ? "" : " off"));
  const cb = el("input");
  cb.type = "checkbox";
  // Level-2 checkbox. In the Group view it is a plain participant toggle. In
  // Explore it is the parent of the level-3 trial checkboxes: checkmark when the
  // participant is in and all its current-shift trials are in, a dash ("minus")
  // when in but some trials are trimmed, unchecked when the participant is out.
  // Clicking toggles the whole participant in / out; the trimmed trials are kept
  // dormant, so re-selecting restores the same dash.
  if (withTrials) {
    // Toggle membership by CURRENT state, not by cb.checked: clicking a dash must
    // deselect (not jump to checked, as a native tristate would). syncCb then sets
    // the real checked/indeterminate; onchange (not onclick) avoids the checkbox
    // preventDefault-revert quirk.
    cb.onchange = () => {
      if (ps.included.has(p.id)) ps.included.delete(p.id);
      else ps.included.add(p.id);
      ps._syncSel();
      ps._refresh();
    };
  } else {
    cb.checked = ps.included.has(p.id);
    cb.onchange = () => {
      cb.checked ? ps.included.add(p.id) : ps.included.delete(p.id);
      ps._syncSel();
      ps._refresh();
    };
  }
  const pid = el("span", "pid", p.id);
  // Meta line. The trial count is a pill so it reads as a separate chip, not as
  // part of the sentence: "P001 · female · [72 of 76 +100 c]".
  const meta = el("span", "meta");
  const pill = el("span", "tpill");
  function syncMeta() {
    if (!withTrials) {
      meta.textContent = `· ${p.gender} · ${p.nTrials} trials`;
      return;
    }
    const c = shiftTrialCounts(ps, p);
    meta.textContent = `· ${p.gender} `;
    pill.textContent = `${trialCountLabel(c.inc, c.total)} trials (${condLabel(ps.shiftCondId)} shift)`;
    pill.classList.toggle("part", c.inc < c.total);
    meta.appendChild(pill);
  }
  // Level-2 display: derive checked / indeterminate / unchecked from membership
  // and the trial counts, and grey the row when the participant is out.
  function syncCb() {
    if (!withTrials) {
      const on = ps.included.has(p.id);
      cb.checked = on;
      cb.indeterminate = false;
      row.classList.toggle("off", !on);
      return;
    }
    const inc = ps.included.has(p.id);
    const c = shiftTrialCounts(ps, p);
    cb.checked = inc && c.total > 0 && c.inc === c.total;
    cb.indeterminate = inc && c.inc < c.total; // dash when in but trimmed (incl. all-out)
    row.classList.toggle("off", !inc);
    syncMeta();
  }
  syncMeta();
  row.appendChild(cb);
  let thumbBox = null;
  let exp = null;
  if (withTrials) {
    exp = el("span", "exp", "▸");
    row.appendChild(exp);
    exp.onclick = () => {
      if (thumbBox) {
        thumbBox.remove();
        thumbBox = null;
        exp.textContent = "▸";
        return;
      }
      exp.textContent = "▾";
      thumbBox = buildThumbs(ps, p, syncCb);
      row.after(thumbBox);
      thumbBox
        .querySelectorAll("canvas")
        .forEach((cv) => cv._draw && cv._draw()); // redraw at real width
    };
  } else {
    row.appendChild(el("span", "exp", " "));
  }
  row.appendChild(pid);
  row.appendChild(meta);
  // Refresh the row count + checkbox, and rebuild an OPEN thumbnail box in place —
  // called when the panel's shift changes, so all three levels match the shift.
  function renderThumbs() {
    syncCb();
    if (!thumbBox) return;
    const fresh = buildThumbs(ps, p, syncCb);
    thumbBox.replaceWith(fresh);
    thumbBox = fresh;
    thumbBox.querySelectorAll("canvas").forEach((cv) => cv._draw && cv._draw());
  }
  return { row, cb, p, renderThumbs, syncCb, syncMeta };
}

/* All / Female / Male shortcut buttons. Clicking one ticks exactly that group
   in the participant list; the highlight mirrors the current selection and goes
   out when a hand-picked subset matches none of the three. */
function genderPill(ps, activeBg) {
  const pill = el("div", "pill");
  const btns = {};
  [
    ["all", "All"],
    ["female", "Female"],
    ["male", "Male"],
  ].forEach(([g, lbl]) => {
    const b = el("button", null, lbl);
    b.onclick = () => {
      ps.included = new Set(
        M.participants
          .filter((p) => g === "all" || p.gender === g)
          .map((p) => p.id),
      );
      ps._syncSel();
      ps._refresh();
    };
    btns[g] = b;
    pill.appendChild(b);
  });
  function sync() {
    const kind = selectionKind(ps.included);
    for (const g in btns) {
      const on = kind === g;
      btns[g].classList.toggle("active", on);
      btns[g].style.background = on ? activeBg : "";
    }
  }
  sync();
  return { node: pill, sync };
}

/* Participant list with a master select-all checkbox and a selection counter. */
function participantsSection(ps, withTrials) {
  const node = el("div");
  const head = el("div", "sidehead");
  const master = el("input");
  master.type = "checkbox";
  master.setAttribute("aria-label", "select or deselect all participants");
  master.title = "select / deselect all";
  master.onchange = () => {
    ps.included = master.checked ? new Set(D_ids()) : new Set();
    ps._syncSel();
    ps._refresh();
  };
  head.appendChild(master);
  head.appendChild(el("span", null, "PARTICIPANTS"));
  const cnt = el("span", "cnt");
  head.appendChild(cnt);
  node.appendChild(head);
  const list = el("div", "plist");
  const rows = [];
  M.participants.forEach((p, pi) => {
    const r = participantRow(ps, p, pi, withTrials);
    rows.push(r);
    list.appendChild(r.row);
  });
  node.appendChild(list);
  function sync() {
    let n = 0;
    for (const r of rows) {
      if (ps.included.has(r.p.id)) n++;
      r.syncCb();
    }
    // Level-1 master reflects participant membership (the "n of 28"); a member
    // whose trials are trimmed still counts here and shows a dash at level 2.
    master.checked = n === rows.length && n > 0;
    master.indeterminate = n > 0 && n < rows.length;
    cnt.textContent = `${n} of ${rows.length} selected`;
  }
  function refreshThumbs() {
    for (const r of rows) if (r.renderThumbs) r.renderThumbs();
  }
  sync();
  return { node, sync, refreshThumbs };
}

function buildThumbs(ps, p, onChange) {
  const box = el("div", "thumbs");
  const ci = D.condIndexById[ps.shiftCondId];
  const start = p.trialStart;
  const gts = [];
  for (let j = 0; j < p.nTrials; j++) {
    const gt = start + j;
    if (D.condCodes[gt] === ci) gts.push(gt);
  }

  // header: a master checkbox that includes / excludes every trial shown (the
  // per-participant analogue of the participant select-all), and a live count of
  // how many of this shift's trials are checked in.
  const head = el("div", "th-h");
  const all = el("input");
  all.type = "checkbox";
  all.className = "th-all";
  all.setAttribute(
    "aria-label",
    `include or exclude all ${condLabel(ps.shiftCondId)} trials for ${p.id}`,
  );
  all.title = "include / exclude all trials shown";
  const htxt = el("span", null, `${p.id} — `);
  const hpill = el("span", "tpill");
  const hhint = el(
    "span",
    null,
    " — click a thumbnail, or the box above, to include / exclude",
  );
  head.appendChild(all);
  head.appendChild(htxt);
  head.appendChild(hpill);
  head.appendChild(hhint);
  box.appendChild(head);

  const grid = el("div", "th-grid");
  const thumbs = [];
  gts.forEach((gt, i) => {
    const th = thumb(ps, gt, i + 1, afterChange);
    grid.appendChild(th.node);
    thumbs.push(th);
  });
  if (gts.length === 0)
    grid.appendChild(
      el("div", "muted", `No ${condLabel(ps.shiftCondId)} trials for ${p.id}.`),
    );
  box.appendChild(grid);

  function included() {
    let inc = 0;
    for (const gt of gts) if (!ps.excluded.has(gt)) inc++;
    return inc;
  }
  function syncAll() {
    const inc = included();
    all.checked = gts.length > 0 && inc === gts.length;
    all.indeterminate = inc > 0 && inc < gts.length;
    hpill.textContent = `${trialCountLabel(inc, gts.length)} trials (${condLabel(ps.shiftCondId)} shift)`;
    hpill.classList.toggle("part", inc < gts.length);
  }
  function afterChange() {
    syncAll();
    if (onChange) onChange();
    ps._refresh();
  }
  all.onchange = () => {
    // the browser has already flipped all.checked
    for (const gt of gts) {
      if (all.checked) ps.excluded.delete(gt);
      else ps.excluded.add(gt);
    }
    for (const th of thumbs) th.refresh();
    afterChange();
  };
  syncAll();
  return box;
}
function thumb(ps, gt, n, onToggle) {
  const t = el("div", "thumb" + (ps.excluded.has(gt) ? " excluded" : ""));
  const tl = el("div", "tl");
  tl.appendChild(el("span", null, "t" + n));
  const mark = el("span", null, ps.excluded.has(gt) ? "☐" : "☑");
  mark.style.fontSize = "15px";
  mark.style.lineHeight = "1";
  tl.appendChild(mark);
  t.appendChild(tl);
  const c = el("canvas");
  c.style.height = "52px";
  t.appendChild(c);
  const draw = () => drawThumb(c, gt, !ps.excluded.has(gt));
  c._draw = draw;
  draw(); // draw now (fallback width); caller redraws after insertion
  function paint() {
    t.classList.toggle("excluded", ps.excluded.has(gt));
    mark.textContent = ps.excluded.has(gt) ? "☐" : "☑";
    draw();
  }
  t.onclick = () => {
    ps.excluded.has(gt) ? ps.excluded.delete(gt) : ps.excluded.add(gt);
    paint();
    if (onToggle) onToggle();
  }; // onToggle drives sync + row count + refresh
  return { node: t, refresh: paint };
}
function drawThumb(canvas, gt, included) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 120;
  const h = 52;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const t = D.t;
  let lo = Infinity;
  let hi = -Infinity;
  for (let k = 0; k < t.length; k++) {
    const v = trialVal(gt, k);
    if (isFinite(v)) {
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  if (!isFinite(lo)) {
    lo = -50;
    hi = 50;
  }
  const pad = (hi - lo) * 0.15 || 10;
  lo -= pad;
  hi += pad;
  const span = D.tMax - D.tMin;
  const X = (v) => ((v - D.tMin) / span) * w;
  const Y = (v) => h - ((v - lo) / (hi - lo)) * h;
  ctx.fillStyle = "rgba(90,110,200,.14)";
  ctx.fillRect(
    X(D.pertMs.onsetMs),
    0,
    X(D.pertMs.onsetMs + D.pertMs.durationMs) - X(D.pertMs.onsetMs),
    h,
  );
  ctx.strokeStyle = "#c9ccd8";
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(0, Y(0));
  ctx.lineTo(w, Y(0));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = included ? "#3366d9" : "#aeb3c2";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  let started = false;
  for (let k = 0; k < t.length; k++) {
    const v = trialVal(gt, k);
    if (!isFinite(v)) {
      started = false;
      continue;
    }
    const x = X(t[k]);
    const y = Y(v);
    started ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    started = true;
  }
  ctx.stroke();
}

/* --------------------------------------------------- Group Average view */
function renderGroup(app) {
  const gs = state.group;
  const intro = el("p", "intro");
  intro.innerHTML =
    "This view averages <b>every participant</b> together (so no single " +
    "speaker dominates) and splits by shift sign.<br>Set the baseline and analysis windows below the " +
    "chart and the paired test compares them.<br>The All / Female / Male buttons tick whole groups in " +
    "the participant list.<br>Check participants in and out of the list to see the average move.";
  app.appendChild(intro);

  const tb = el("div", "toolbar");
  tb.appendChild(el("span", "label", "participants:"));
  const gp = genderPill(gs, "var(--indigo)");
  tb.appendChild(gp.node);
  app.appendChild(tb);

  const card = el("div", "card");
  const title = el("div", "panel-title");
  card.appendChild(title);
  const sub = el(
    "div",
    "muted",
    "Averaged across participants (N counts participants): each participant's trials are averaged first, then those curves are averaged.",
  );
  sub.style.fontSize = "12px";
  sub.style.margin = "-4px 0 8px";
  card.appendChild(sub);
  const leg = el("div", "legend");
  card.appendChild(leg);
  const cw1 = el("div", "chart-wrap");
  const c1 = el("canvas", "chart");
  cw1.appendChild(c1);
  card.appendChild(cw1);
  const cap1 = el("div", "caption");
  card.appendChild(cap1);
  const cw2 = el("div", "chart-wrap");
  const c2 = el("canvas", "chart");
  cw2.appendChild(c2);
  card.appendChild(cw2);
  card.appendChild(
    el(
      "div",
      "caption",
      "Bottom — perturbed minus control, isolating the compensation response from baseline drift.",
    ),
  );

  const dirCtl = selectCtl(
    "Direction",
    [
      ["both", "Both directions"],
      ["signed", "Signed-combined"],
      ...shiftedConds().map((c) => [
        c.shiftCents < 0 ? "down" : "up",
        `${c.label} only`,
      ]),
    ],
    gs.dir,
    (v) => {
      gs.dir = v;
      refresh();
    },
  );
  const ccCtl = checkCtl("Correct for control", gs.correctControl, (v) => {
    gs.correctControl = v;
    refresh();
  });
  card.appendChild(windowControls(gs.win, () => refresh(), [dirCtl, ccCtl]));
  const stats = el("div", "stats");
  card.appendChild(stats);
  const note = el("div", "winnote");
  card.appendChild(note);

  const btns = el("div", "btns");
  const p1 = el("button", null, "Export PNG (vs baseline)");
  p1.onclick = () => exportPNG(c1, "group_vs_baseline");
  const p2 = el("button", null, "Export PNG (difference)");
  p2.onclick = () => exportPNG(c2, "group_difference");
  const cs = el("button", null, "Export CSV");
  cs.onclick = () => exportGroupCSV(lastAgg);
  btns.appendChild(p1);
  btns.appendChild(p2);
  btns.appendChild(cs);
  card.appendChild(btns);

  const sec = participantsSection(gs, false);
  card.appendChild(sec.node);
  gs._syncSel = () => {
    gp.sync();
    sec.sync();
  };

  app.appendChild(card); // in the DOM before drawing so canvas clientWidth is valid

  let lastAgg = null;
  gs._refresh = () => refresh();
  function refresh() {
    const agg = groupAggregate(gs.included, gs.excluded);
    lastAgg = agg;
    title.textContent = `Grand average (by sign) · ${plural(agg.nParticipants, "participant")} (${genderText(agg.parts)}) · ${plural(agg.nTrials, "trial")} · SWIPE′`;

    // per-participant curves for the paired statistics (control correction reflected here).
    // "both" is a view of the by-sign curves; its statistic is the signed-combined pooling.
    const statDir = gs.dir === "both" ? "signed" : gs.dir;
    const curves = directionCurves(
      agg.parts,
      statDir,
      gs.correctControl,
      gs.excluded,
    );
    const st = pairedWindowStats(curves, gs.win.baseline, gs.win.analysis);
    let pk = null;
    if (curves.length) {
      const ms = meanSemAcross(
        curves.map((c) => c.curve),
        D.nT,
      );
      pk = peakInWindow(
        agg.t,
        gaussSmooth(ms.mean, D.smoothWin),
        gs.win.analysis.startMs,
        gs.win.analysis.endMs,
      );
    }

    // pooled compensation curve for the plot, so the reported number has a line to
    // match. Computed uncorrected on purpose, so the Correct-for-control checkbox
    // never moves the plotted line: on a sign-normalized pair its effect is zero,
    // and for a single direction it lives in the difference tile below.
    let pooledMean = null;
    let pooledSem = null;
    let pooledPk = null;
    if (gs.dir === "signed") {
      const pc = directionCurves(agg.parts, "signed", false, gs.excluded);
      if (pc.length) {
        const pms = meanSemAcross(
          pc.map((c) => c.curve),
          D.nT,
        );
        pooledMean = gaussSmooth(pms.mean, D.smoothWin);
        pooledSem = gaussSmooth(pms.sem, D.smoothWin);
        pooledPk = peakInWindow(
          agg.t,
          pooledMean,
          gs.win.analysis.startMs,
          gs.win.analysis.endMs,
        );
      }
    }

    leg.innerHTML = "";
    D.conds.forEach((c, ci) => {
      leg.innerHTML += `<span class="k"><span class="swatch" style="border-top-color:${c.color}"></span>${c.label} (N=${agg.perCond[ci].n})</span>`;
    });
    if (gs.dir === "signed")
      leg.innerHTML += `<span class="k"><span class="swatch" style="border-top-color:${POOLED}"></span>signed-combined compensation</span>`;
    leg.innerHTML +=
      `<span class="k"><span class="box" style="background:rgba(140,140,140,.22)"></span>± SEM / 95% CI</span>` +
      windowLegendHtml();

    // tile 1: conditions vs their own baselines, with the Direction control reflected
    const faint = (c) => ({
      t: agg.t,
      mean: agg.perCond[D.conds.indexOf(c)].mean,
      color: hexA(c.color, 0.4),
      width: 1,
      dash: [3, 3],
    });
    const bysignPeaks = () => {
      const a = [];
      D.conds.forEach((c, ci) => {
        if (c.isControl) return;
        const p = peakInWindow(
          agg.t,
          agg.perCond[ci].mean,
          D.pkWin[0],
          D.pkWin[1],
        );
        if (p)
          a.push({
            x: p.t,
            y: p.v,
            text: (p.v > 0 ? "+" : "") + p.v.toFixed(2) + " c",
            color: c.color,
          });
      });
      return a;
    };
    let series1;
    let anns1;
    if (gs.dir === "both") {
      series1 = D.conds.map((c, ci) => ({
        t: agg.t,
        mean: agg.perCond[ci].mean,
        sem: agg.perCond[ci].sem,
        color: c.color,
      }));
      anns1 = bysignPeaks();
      cap1.textContent =
        "Top — control, downward and upward shifts together, against their own " +
        `baselines. Peak labels use the ${D.pkWin[0]}–${D.pkWin[1]} ms window.`;
    } else if (gs.dir === "signed") {
      series1 = D.conds.map(faint);
      if (pooledMean)
        series1.push({
          t: agg.t,
          mean: pooledMean,
          sem: pooledSem,
          color: POOLED,
          width: 2.6,
        });
      anns1 = pooledPk
        ? [
            {
              x: pooledPk.t,
              y: pooledPk.v,
              text: (pooledPk.v > 0 ? "+" : "") + pooledPk.v.toFixed(2) + " c",
              color: POOLED,
            },
          ]
        : [];
      cap1.textContent =
        "Top — the signed-combined compensation curve (up-shift responses inverted, " +
        "pooled across both directions), with the by-sign conditions dashed for reference. Its peak " +
        "is marked in the analysis window, matching the statistics panel.";
    } else {
      const isSel = (c) =>
        !c.isControl &&
        (gs.dir === "down" ? c.shiftCents < 0 : c.shiftCents > 0);
      series1 = [];
      D.conds.forEach((c) => {
        if (!isSel(c)) series1.push(faint(c));
      });
      D.conds.forEach((c, ci) => {
        if (isSel(c))
          series1.push({
            t: agg.t,
            mean: agg.perCond[ci].mean,
            sem: agg.perCond[ci].sem,
            color: c.color,
            width: 2.6,
          });
      });
      anns1 = [];
      D.conds.forEach((c, ci) => {
        if (!isSel(c)) return;
        const p = peakInWindow(
          agg.t,
          agg.perCond[ci].mean,
          D.pkWin[0],
          D.pkWin[1],
        );
        if (p)
          anns1.push({
            x: p.t,
            y: p.v,
            text: (p.v > 0 ? "+" : "") + p.v.toFixed(2) + " c",
            color: c.color,
          });
      });
      cap1.textContent =
        `Top — ${gs.dir === "down" ? "−100 c" : "+100 c"} emphasized, with control and the ` +
        `other direction dashed. Peak labels use the ${D.pkWin[0]}–${D.pkWin[1]} ms window.`;
    }
    drawChart(c1, {
      height: 300,
      xRange: [D.tMin, D.tMax],
      bands: chartBands(gs.win),
      xlabel: "Time relative to perturbation onset (ms)",
      ylabel: "Cents from baseline",
      series: series1,
      annotations: anns1,
    });

    // tile 2: perturbed minus control
    const ctrl = agg.perCond[D.ctrlIdx];
    const series2 = [];
    const anns2 = [];
    D.conds.forEach((c, ci) => {
      if (c.isControl) return;
      const dm = new Float64Array(D.nT);
      const dsem = new Float64Array(D.nT);
      for (let k = 0; k < D.nT; k++) {
        dm[k] = agg.perCond[ci].mean[k] - ctrl.mean[k];
        dsem[k] = Math.sqrt(
          Math.pow(agg.perCond[ci].sem[k], 2) + Math.pow(ctrl.sem[k], 2),
        );
      }
      series2.push({ t: agg.t, mean: dm, sem: dsem, color: c.color });
      const p = peakInWindow(agg.t, dm, D.pkWin[0], D.pkWin[1]);
      if (p)
        anns2.push({
          x: p.t,
          y: p.v,
          text: (p.v > 0 ? "+" : "") + p.v.toFixed(2) + " c",
          color: c.color,
        });
    });
    drawChart(c2, {
      height: 300,
      xRange: [D.tMin, D.tMax],
      bands: chartBands(gs.win),
      xlabel: "Time relative to perturbation onset (ms)",
      ylabel: "Δ cents (group − control)",
      series: series2,
      annotations: anns2,
    });

    renderWindowStats(stats, st, gs.win, "participant", pk);
    const dirTxt =
      gs.dir === "signed" || gs.dir === "both"
        ? "Up-shift responses are inverted before pooling, so compensation counts as positive whichever way the feedback moved."
        : "A single shift direction. Compensation opposes the shift, so the sign follows the condition.";
    const ccTxt = !gs.correctControl
      ? " Control trials are not subtracted."
      : controlCorrectionCancels(statDir)
        ? " Each participant's control curve is subtracted first. With equal and opposite shifts pooled together, the control terms cancel, so this does not change the combined numbers. Pick a single direction to see its effect."
        : " Each participant's control curve is subtracted first.";
    note.textContent = windowNote(gs.win, "participant", st.n, dirTxt + ccTxt);
  }
  refresh();
}

/* --------------------------------------------------- export */
function download(name, blob) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function exportPNG(canvas, stem) {
  canvas.toBlob((b) => download(stem + ".png", b));
}
function csvBlob(rows) {
  return new Blob([rows.map((r) => r.join(",")).join("\n")], {
    type: "text/csv",
  });
}
function exportExploreCSV(ps) {
  const agg = exploreAggregate(ps);
  const rows = [["time_ms", "mean_cents", "sem_cents"]];
  for (let k = 0; k < agg.t.length; k++)
    rows.push([agg.t[k], fmt(agg.mean[k]), fmt(agg.sem[k])]);
  download(
    `explore_${ps.shiftCondId}_${selectionName(ps.included)}.csv`,
    csvBlob(rows),
  );
}
function exportGroupCSV(agg) {
  const head = ["time_ms"];
  D.conds.forEach((c) => {
    head.push(c.id + "_mean", c.id + "_sem");
  });
  const rows = [head];
  for (let k = 0; k < agg.t.length; k++) {
    const r = [agg.t[k]];
    D.conds.forEach((c, ci) =>
      r.push(fmt(agg.perCond[ci].mean[k]), fmt(agg.perCond[ci].sem[k])),
    );
    rows.push(r);
  }
  download(
    `group_average_${selectionName(state.group.included)}.csv`,
    csvBlob(rows),
  );
}
function fmt(x) {
  return isFinite(x) ? Math.round(x * 1000) / 1000 : "";
}

/* ============================================================= boot */
(async function boot() {
  try {
    const mb = document.getElementById("manifest-b64").textContent;
    const db = document.getElementById("data-b64").textContent;
    if (mb.trim().startsWith("__") || db.trim().startsWith("__")) {
      document.getElementById("app").innerHTML =
        `<div class="err">This is <b>app_template.html</b>, the data-less template. Open the built file <b>pitch_explorer.html</b> instead (run <code>python export_pitch_explorer.py</code> to build it if it is missing).</div>`;
      return;
    }
    const manifestBuf = await gunzip(b64ToBytes(mb));
    const manifest = JSON.parse(new TextDecoder().decode(manifestBuf));
    const dataBuf = await gunzip(b64ToBytes(db));
    buildModel(manifest, dataBuf);
    const shifted = shiftedConds();
    state.explore.panels = [
      newPanel(shifted[0].id),
      newPanel((shifted[1] || shifted[0]).id),
    ];
    state.group = newGroupState();
    syncNav();
    render();
    window.addEventListener("resize", () => {
      // redraw charts on resize
      if (state.view === "explore")
        state.explore.panels.forEach((p) => p._refresh && p._refresh());
      else render();
    });
  } catch (e) {
    document.getElementById("app").innerHTML =
      `<div class="err">Failed to load: ${e.message}</div>`;
    console.error(e);
  }
})();
