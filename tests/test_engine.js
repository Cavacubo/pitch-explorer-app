// Validation test 2 (Node): the engine itself reproduces the reference.
//
// Loads the same engine.js that export_pitch_explorer.py inlines into the
// built file, decodes the embedded payload from pitch_explorer.html, and
// recomputes with the engine's own functions:
//   * the by-sign grand-average peaks, through groupAggregate;
//   * the paired baseline-vs-analysis window test in every direction, with and
//     without control correction, through directionCurves and
//     pairedWindowStats.
// The reference values come from the Python build, so the engine and the
// Python implementation are compared on the same payload. Also unit-tests
// gaussSmooth, oneSampleT and tCrit, and writes the engine's per-participant
// difference vectors to tests/engine_vectors.json for the scipy check
// (tests/test_scipy_check.py).
// Run:  node tests/test_engine.js
"use strict";
var fs = require("fs");
var zlib = require("zlib");
var path = require("path");
var ROOT = path.join(__dirname, "..");
global.jStat = require(path.join(ROOT, "vendor", "jstat.min.js"));
var E = require(path.join(ROOT, "engine.js"));
var TOL = 0.1; // cents
var T_TOL = 0.05; // t units
var failures = 0;
function ok(cond, msg) {
  if (!cond) {
    failures++;
    console.log("  [XX ] " + msg);
  } else console.log("  [OK ] " + msg);
}
function round2(x) {
  return Math.round(x * 100) / 100;
}

// ---- decode embedded payload ----
function block(html, id) {
  var m = html.match(new RegExp('id="' + id + '"[^>]*>([^<]+)</script>'));
  if (!m) throw new Error("missing block " + id);
  return zlib.gunzipSync(Buffer.from(m[1].trim(), "base64"));
}
var html = fs.readFileSync(path.join(ROOT, "pitch_explorer.html"), "utf-8");
var manifest = JSON.parse(block(html, "manifest-b64").toString("utf-8"));
var dataBytes = block(html, "data-b64");
var ref = JSON.parse(
  fs.readFileSync(path.join(ROOT, "pitch_explorer_reference.json"), "utf-8"),
);

// the engine expects an ArrayBuffer whose offsets match the manifest layout
var dataBuf = dataBytes.buffer.slice(
  dataBytes.byteOffset,
  dataBytes.byteOffset + dataBytes.byteLength,
);
E.buildModel(manifest, dataBuf);
var D = E.D;
var parts = D.parts;
var conds = D.conds;
var lay = manifest.binary.layout;

// ---- checks ----
console.log("sample:");
ok(D.nParts === 28, D.nParts + " participants (expect 28)");
["P002", "P004", "P031"].forEach(function (code) {
  ok(html.indexOf(code) === -1, code + " appears nowhere in the built file");
});
ok(
  Object.keys(lay).sort().join(",") === "condCodes,trials",
  "binary sections are " + Object.keys(lay).sort().join(", "),
);

console.log("grand-average peaks vs reference:");
[
  [
    "all",
    function () {
      return true;
    },
  ],
  [
    "female",
    function (g) {
      return g === "female";
    },
  ],
  [
    "male",
    function (g) {
      return g === "male";
    },
  ],
].forEach(function (pair) {
  var gl = pair[0];
  var keep = pair[1];
  var ids = [];
  parts.forEach(function (p) {
    if (keep(p.gender)) ids.push(p.id);
  });
  var agg = E.groupAggregate(new Set(ids));
  ok(
    agg.nParticipants === ref[gl].nParticipants,
    gl + ": N = " + agg.nParticipants,
  );
  var ctrl = agg.perCond[D.ctrlIdx].mean;
  conds.forEach(function (c, ci) {
    if (c.isControl) return;
    var curve = agg.perCond[ci].mean;
    var got = round2(E.peakInWindow(D.t, curve, D.pkWin[0], D.pkWin[1]).v);
    var exp = ref[gl][c.id + "_peak_c"];
    ok(
      Math.abs(got - exp) <= TOL,
      gl + " " + c.id + " peak got=" + got + " ref=" + exp,
    );
    var d = new Float64Array(D.nT);
    for (var k = 0; k < D.nT; k++) d[k] = curve[k] - ctrl[k];
    var gotD = round2(E.peakInWindow(D.t, d, D.pkWin[0], D.pkWin[1]).v);
    var expD = ref[gl][c.id + "_minus_ctrl_peak_c"];
    ok(
      Math.abs(gotD - expD) <= TOL,
      gl + " " + c.id + " minus control got=" + gotD + " ref=" + expD,
    );
  });
});

console.log("paired window test vs reference:");
var allIdx = [];
for (var q = 0; q < D.nParts; q++) allIdx.push(q);
var wins = ref.windowTest.windows;
var vectors = {}; // handed to the scipy check
["signed", "down", "up"].forEach(function (dir) {
  [true, false].forEach(function (cc) {
    var key = dir + "_" + (cc ? "ctrlCorrected" : "raw");
    var st = E.pairedWindowStats(
      E.directionCurves(allIdx, dir, cc),
      wins.baseline,
      wins.analysis,
    );
    vectors[key] = {
      diffs: st.diffs,
      n: st.n,
      meanDiff: st.meanDiff,
      t: st.t,
      df: st.df,
      p: st.p,
      dz: st.dz,
      ciLo: st.ciLo,
      ciHi: st.ciHi,
    };
    var exp = ref.windowTest[key];
    var good =
      st.n === exp.n &&
      st.df === exp.df &&
      Math.abs(round2(st.meanDiff) - exp.meanDiff_c) <= TOL &&
      Math.abs(round2(st.t) - exp.t) <= T_TOL &&
      Math.abs(round2(st.dz) - exp.dz) <= 0.02 &&
      Math.abs(round2(st.ciLo) - exp.ci_c[0]) <= TOL &&
      Math.abs(round2(st.ciHi) - exp.ci_c[1]) <= TOL;
    ok(
      good,
      key +
        " mean=" +
        round2(st.meanDiff) +
        "c t(" +
        st.df +
        ")=" +
        round2(st.t) +
        " dz=" +
        round2(st.dz) +
        " CI=[" +
        round2(st.ciLo) +
        ", " +
        round2(st.ciHi) +
        "]",
    );
  });
});
Object.keys(ref.windowTestAlt).forEach(function (name) {
  var w = ref.windowTestAlt[name];
  var st = E.pairedWindowStats(
    E.directionCurves(allIdx, "signed", true),
    w.baseline,
    w.analysis,
  );
  vectors["alt_" + name] = {
    diffs: st.diffs,
    n: st.n,
    meanDiff: st.meanDiff,
    t: st.t,
    df: st.df,
    p: st.p,
    dz: st.dz,
    ciLo: st.ciLo,
    ciHi: st.ciHi,
    baseline: w.baseline,
    analysis: w.analysis,
  };
});

console.log("control correction cancels only where it should:");
var signedCC = E.pairedWindowStats(
  E.directionCurves(allIdx, "signed", true),
  wins.baseline,
  wins.analysis,
);
var signedRaw = E.pairedWindowStats(
  E.directionCurves(allIdx, "signed", false),
  wins.baseline,
  wins.analysis,
);
ok(
  Math.abs(signedCC.meanDiff - signedRaw.meanDiff) < 1e-9,
  "equal and opposite shifts pooled: the control terms cancel exactly",
);
var downCC = E.pairedWindowStats(
  E.directionCurves(allIdx, "down", true),
  wins.baseline,
  wins.analysis,
);
var downRaw = E.pairedWindowStats(
  E.directionCurves(allIdx, "down", false),
  wins.baseline,
  wins.analysis,
);
ok(
  Math.abs(downCC.meanDiff - downRaw.meanDiff) > 0.5,
  "single direction: correction changes the result (" +
    round2(downRaw.meanDiff) +
    " -> " +
    round2(downCC.meanDiff) +
    " c)",
);

console.log("unit tests:");
var cst = E.gaussSmooth(new Float64Array([5, 5, 5, 5, 5, 5, 5, 5, 5, 5]), 15);
ok(
  Array.prototype.every.call(cst, function (v) {
    return Math.abs(v - 5) < 1e-9;
  }),
  "gaussSmooth of a constant returns the constant",
);
var wn = E.gaussSmooth(
  new Float64Array([1, NaN, 3, NaN, 5, 6, 7, 8, 9, 10]),
  7,
);
ok(
  wn.length === 10 && Array.prototype.every.call(wn, isFinite),
  "gaussSmooth preserves length and fills across NaNs",
);
var fixPath = path.join(__dirname, "fixtures", "gauss_fixture.csv");
if (fs.existsSync(fixPath)) {
  var rows = fs.readFileSync(fixPath, "utf-8").trim().split(/\r?\n/).slice(1);
  var fxIn = rows.map(function (r) {
    var p = r.split(",");
    return p[0] === "" ? NaN : parseFloat(p[0]);
  });
  var fxExp = rows.map(function (r) {
    var p = r.split(",");
    return p[1] === "" ? NaN : parseFloat(p[1]);
  });
  var fxGot = E.gaussSmooth(fxIn, 15);
  var sameGaps = true;
  var worst = 0;
  for (var fk = 0; fk < fxExp.length; fk++) {
    if (isFinite(fxExp[fk]) !== isFinite(fxGot[fk])) {
      sameGaps = false;
      break;
    }
    if (isFinite(fxExp[fk]))
      worst = Math.max(worst, Math.abs(fxExp[fk] - fxGot[fk]));
  }
  ok(
    sameGaps && worst < 1e-9,
    "gaussSmooth matches the MATLAB smoothdata fixture (max |err| " +
      worst.toExponential(1) +
      ")",
  );
} else {
  console.log(
    "  gauss_fixture.csv not present; run tests/fixtures/make_gauss_fixture.m in MATLAB to create it",
  );
}
var tt = E.oneSampleT([1, 2, 3, 4, 5]);
ok(
  Math.abs(tt.t - 4.2426) < 1e-3 && tt.df === 4,
  "oneSampleT([1..5]) t=" + tt.t.toFixed(4) + " (expect 4.2426), df=" + tt.df,
);
ok(
  Math.abs(tt.p - 0.01324) < 1e-4,
  "oneSampleT p=" + tt.p.toFixed(5) + " (expect ~0.01324)",
);
ok(
  Math.abs(E.tCrit(27, 0.05) - 2.0518) < 1e-3,
  "tCrit(df=27) = " + E.tCrit(27, 0.05).toFixed(4) + " (expect 2.0518)",
);

// a fixture with known differences, so the window machinery is checked
// independently of the corpus. The step starts strictly after onset because
// both window bounds are inclusive, so t = 0 belongs to the baseline window.
var fixture = [2, 4, 6, 8].map(function (d) {
  var c = new Float64Array(D.nT);
  for (var k = 0; k < D.nT; k++) c[k] = D.t[k] > 0 ? d : 0;
  return c;
});
var fx = E.pairedWindowStats(
  fixture,
  { startMs: -100, endMs: 0 },
  { startMs: 100, endMs: 250 },
);
ok(
  fx.n === 4 &&
    Math.abs(fx.meanDiff - 5) < 1e-9 &&
    Math.abs(fx.t - 3.873) < 1e-3 &&
    Math.abs(fx.dz - 1.9365) < 1e-3,
  "fixture diffs [2,4,6,8]: mean=" +
    fx.meanDiff.toFixed(4) +
    " t=" +
    fx.t.toFixed(4) +
    " dz=" +
    fx.dz.toFixed(4),
);

// hand the engine's own difference vectors to the scipy check
var dumpPath = path.join(__dirname, "engine_vectors.json");
fs.writeFileSync(dumpPath, JSON.stringify(vectors));
console.log(
  "\nwrote " + path.basename(dumpPath) + " for tests/test_scipy_check.py",
);

console.log(
  failures
    ? "\n" + failures + " FAILURE(S)"
    : "\nPASS — the JS engine reproduces every reference value.",
);
process.exit(failures ? 1 : 0);
