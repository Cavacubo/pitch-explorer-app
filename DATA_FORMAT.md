# Pitch Explorer data format

Two formats appear in this project, and they serve different readers:

1. The input contract — a folder of CSV tables plus one JSON config file. This is the format to prepare in order to display a new dataset. The files are plain text, open in a spreadsheet program, and require no MATLAB.
2. The embedded payload — a compact binary block written into the built HTML file. It is a build artifact, produced by the exporter, and holds the whole corpus so the file opens offline.

Building the tool is two steps:

```bash
python convert_mat_to_csv.py     # step 1, once: MATLAB epoch files -> the CSV dataset below
```
```bash
python export_pitch_explorer.py  # step 2: the CSV dataset -> pitch_explorer.html
```

Step 1 needs `scipy` because it reads `.mat`. Step 2 needs neither MATLAB nor `.mat`. If the data are already in the CSV format, step 1 is not needed.

A complete, runnable example of the input format is in [`csv_dataset_example/`](csv_dataset_example/), with every participant and five trials each.

---

## Part 1 — The input contract

```
csv_dataset/
  dataset.json          experiment configuration and the participant list
  trials.csv            one row per trial: what condition it was, and its measured properties
  curves/
    P001.csv            one row per trial, one column per time sample
    P003.csv
    …
```

### `curves/<id>.csv`

The measured data. Everything the tool shows is derived from these tables.

| | |
|---|---|
| Row | one trial |
| Column | one time sample |
| Cell | the speaker's pitch at that moment, in cents relative to that trial's own baseline |
| Header row | `trial_index`, then the time of each sample in ms relative to perturbation onset |
| First column | `trial_index`, 1-based, matching `trials.csv` |
| Empty cell | no reliable pitch measurement at that moment (a gap, not a zero) |

```csv
trial_index,-500,-498,-496,-494,-492,-490,-488, … ,1000
1,-45.27,-46.83,-48.39,-49.95,-51.52,-51.52,-53.08, … ,
2,,,,-12.11,-11.87,-11.40,-10.98, … ,3.44
```

Negative times are before the perturbation, `0` is the onset, positive times after. Every participant file must use the same time grid, and it must match `epoch` in `dataset.json`.

An empty cell must stay empty. Writing `0` would claim the voice was at baseline, a different statement from "not measurable here". It would also pull every average toward zero.

### `trials.csv`

One row per trial, across all participants. It records the design of each trial. The curves hold the measurements.

```csv
participant,trial_index,gender,condition,perturbed,signed_shift_cents,perturb_dur_ms,baseline_f0_hz
P001,1,female,neg100,1,-100,202.7,160.40
P001,2,female,neg100,1,-100,202.7,165.45
```

| Column | Meaning |
|---|---|
| `participant` | participant code, matching a `curves/<id>.csv` file |
| `trial_index` | 1-based, matching the row in that participant's curves file |
| `gender` | `female` or `male`. Drives the F0 search range during extraction and the gender filter in the tool |
| `condition` | one of the `id` values in `dataset.json` → `conditions` |
| `perturbed` | `1` if feedback was shifted on this trial, `0` for a control trial |
| `signed_shift_cents` | the shift applied, signed. Empty on control trials or where it was not recorded |
| `perturb_dur_ms` | the perturbation duration measured on this trial (the nominal value is in `dataset.json`) |
| `baseline_f0_hz` | the reference pitch used to convert this trial to cents |

`condition` is the column the tool groups by. `perturbed` and `signed_shift_cents` are recorded so the grouping can be checked and re-derived.

### `dataset.json`

The configuration the tool needs in order to read the tables.

```jsonc
{
  "schema": "audapter-pitch-explorer-dataset/v1",
  "name": "…", "description": "…",

  "epoch": {                      // must match the curves' header row exactly
    "tPreMs": 500,                // the epoch starts 500 ms before onset
    "tPostMs": 1000,              // and ends 1000 ms after
    "dtMs": 2,                    // one sample every 2 ms
    "nSamples": 751,              // = (tPre + tPost) / dt + 1
    "baselineMs": [-200, 0]       // the window used during extraction to convert Hz to cents
  },
  "units": {
    "curves": "cents from baseline",
    "time": "ms relative to perturbation onset"
  },
  "perturbation": { "onsetMs": 0, "durationMs": 200 },   // nominal design values

  "conditions": [                 // any number, exactly one must be the control
    { "id": "control", "label": "control", "shiftCents": 0,    "isControl": true,  "color": "#7f7f7f" },
    { "id": "neg100",  "label": "−100 c",  "shiftCents": -100, "isControl": false, "color": "#3366d9" },
    { "id": "pos100",  "label": "+100 c",  "shiftCents": 100,  "isControl": false, "color": "#d9660d" }
  ],
  "genders": ["female", "male"],
  "f0EstimatorRangeHz": { "female": [150, 350], "male": [75, 180] },
  "samplingRate": {
    "processingHz": 24000,        // Audapter's internal rate (params.sRate)
    "downFactor": 2,
    "hardwareHz": 48000           // = processingHz x downFactor
  },

  "participants": [
    { "id": "P001", "gender": "female", "nTrials": 216,
      "counts": { "control": 65, "neg100": 75, "pos100": 76 },
      "curvesFile": "curves/P001.csv" }
  ],
  "totals": { "nParticipants": 28, "nTrials": 6035, "nByCondition": {…}, "nByGender": {…} },
  "files": { "trials": "trials.csv", "curvesDir": "curves" }
}
```

What generalizes. `conditions` is a list of any length, so a study with three shift magnitudes, or one shift direction, or a non-pitch manipulation, describes itself the same way. The tool reads the conditions from the file, including the shift magnitudes. `epoch` carries the time grid, so a study with a 700 ms baseline needs no code change. `shiftCents` gives each condition a sign, which is what the sign-normalized pooling uses.

What must hold. The exporter checks these and stops on any violation:

- every `curves/*.csv` has exactly `epoch.nSamples` time columns, on the same grid
- each participant's row count equals its `nTrials`
- every `(participant, trial_index)` in the curves has a row in `trials.csv`
- every `condition` value names a declared condition
- exactly one condition has `isControl: true`

---

## Part 2 — The embedded payload (build artifact)

`pitch_explorer.html` carries the whole corpus inside itself, so it opens from `file://` with no server and no network. The CSV form is too large to embed directly: about 4.5 million numbers as text is roughly 28 MB, and browsers would have to parse all of it on every load.

At build time the curves are re-encoded:

| Step | Effect |
|---|---|
| Round each value to the nearest whole cent, store as `int16` | 2 bytes instead of ~7 |
| Gaps become the sentinel `-32768` | NaN survives without a separate mask |
| Concatenate trial by trial (trial-major) | adjacent samples of one smooth curve compress well |
| `gzip`, then `base64` | fits inside a `<script>` tag as text |

The result is about 2.1 MB. At load the page decodes it with the browser's native `DecompressionStream("gzip")` and lays typed arrays over the bytes, so no per-value parsing happens.

Two blocks are embedded:

- `#manifest-b64` — a JSON manifest: the `dataset.json` fields the tool needs, the participant list with each participant's `trialStart` offset, and a `binary.layout` map of byte offsets.
- `#data-b64` — the binary blob itself, holding exactly two sections:

| Section | Type | Length | Layout |
|---|---|---|---|
| `trials` | int16 | `nTrials × nSamples` | Trial `j` of participant `p` starts at `(p.trialStart + j) × nSamples`, where `j` runs 0 to nTrials−1 within the participant (not the 1-based `trial_index`) |
| `condCodes` | int8 | `nTrials` | condition index for each trial, same order |

Only per-trial curves are stored. Per-participant means and grand averages are computed in the browser from these curves, so there is a single source of truth.

What whole-cent rounding costs. Each stored sample is within 0.50 cents of the CSV value. Averaged over a participant's trials and then across participants, the error falls far below that: `tests/test_roundtrip.py` re-derives the grand-average peaks from the original MATLAB files and finds the stored values agree to within 0.01 cents. Charts display two decimals, so the rounding does not affect the displayed values.

Measured against the original `.mat`, a single stored sample can differ by up to 0.505 cents, because the CSV stage rounds to two decimals first and the payload then rounds that again, so the two rounding errors add. `tests/test_roundtrip.py` checks both budgets separately.

---

## Regenerating

```bash
python convert_mat_to_csv.py --example
```
```bash
python export_pitch_explorer.py
```

`--example` also refreshes `csv_dataset_example/`. The full `csv_dataset/` is about 28 MB. It can be reproduced from the MATLAB epoch files at any time.
