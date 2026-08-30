# Pitch Explorer

Pitch Explorer is a browser-based tool for exploring pitch-compensation data. All data is embedded in a single HTML file, `pitch_explorer.html`, which opens in a web browser and requires no server or installation. The included corpus is the bachelor-thesis recording set: 28 participants, 6,035 trials, sustained /a/ vowels with a ±100-cent, 200 ms feedback perturbation.

Input is a folder of CSV tables and one JSON configuration file, so a dataset from another study can be prepared without MATLAB. The format is specified in [`DATA_FORMAT.md`](DATA_FORMAT.md), with a complete example in [`csv_dataset_example/`](csv_dataset_example/).

## How to open

Open `pitch_explorer.html` in a web browser, or double-click the file. It decodes its embedded data with the Compression Streams API, which is available in current versions of Chrome, Edge, Firefox (113 and later), and Safari (16.4 and later). If a browser does not decode the file directly, serve the folder over HTTP and open it from there:

```bash
python -m http.server 8765
```

Then open `http://localhost:8765/pitch_explorer.html`.

A hosted copy is available at https://cavacubo.github.io/pitch-explorer-app/.

## Project description

The tool provides two views, Explore and Group Average. Both read from the same pair of time windows, entered as numeric values below the chart: a baseline window (default −200 to 0 ms) and an analysis window (default 100 to 250 ms, the Miller window). Each window is shaded on the chart and updates as its values change. A value typed outside the recorded time range (−500 to 1000 ms) is limited to the nearest edge of that range. Presets fill the analysis window with intervals used in the literature. Perturbation onset is marked with a labeled vertical line, and every window is measured relative to it.

The statistics panel reports a paired t-test between the two windows. Each unit contributes one difference, its mean over the analysis window minus its mean over the baseline window. The panel reports the mean difference in cents, the *t* value, its degrees of freedom, the *p* value, Cohen's *d_z* (a standardized effect size), a 95% confidence interval, and the peak value within the analysis window.

The default unit is the participant: each participant's trials are averaged first, and the test runs across the 28 participants. A trial-level unit is also available.

Explore view. The view shows one panel, or two panels side by side for comparison. In each panel the user selects a shift condition and a set of participants. The All, Female, and Male buttons select whole groups, a master checkbox selects or clears every participant, and the individual checkboxes adjust the selection. Any participant can be expanded into per-trial thumbnails, from which individual trials are included or excluded. The average, shown as the mean ± SEM, recomputes from the current selection. The figure exports to PNG and the displayed data to CSV.

Group Average view. The main figure draws the control, downward, and upward conditions together, averaged across participants so that each participant contributes equally. The participant selection controls match the Explore view. The upper panel shows each condition relative to its own baseline, and the lower panel shows the perturbed conditions minus the control. Two further controls are provided:

- Direction. This chooses which trials feed the paired test in the statistics panel. It also updates the top plot: both directions (the default) shows the by-sign conditions together, signed-combined draws the pooled compensation curve with its peak marked, and a single direction emphasizes that shift with the others faint. Signed-combined pools both directions into one compensation measure by inverting the up-shift responses, so the value is positive whichever way the feedback moved. A single shift direction can also be selected, to test that direction on its own.
- Correct for control. This subtracts each participant's own control curve, isolating the compensation response from baseline drift. It feeds only the statistics panel.

## Architecture

| Component | File | Description |
|---|---|---|
| Format converter | `convert_mat_to_csv.py` | Converts MATLAB epoch files to the CSV and JSON dataset. Run once. Requires `scipy`. |
| Build pipeline | `export_pitch_explorer.py` | Converts the CSV dataset to the quantized binary payload and injects it into the template. No MATLAB required. |
| Application template | `app_template.html` | The page markup and the placeholders the build fills. |
| Interface logic | `app.js` | The user interface: canvas chart renderer, both views, export, and boot code. Inlined at build time. |
| Stylesheet | `app.css` | The interface styles, inlined into the built file's `<style>` tag at build time. |
| Computation engine | `engine.js` | Payload decode, data model, statistics, and aggregation. Inlined into the built file and loaded directly by the Node test. |
| Statistics library | `vendor/jstat.min.js` | jStat 1.9.6 (MIT license), embedded at build time for the *t*-distribution. |
| Built tool | `pitch_explorer.html` | The template with the engine, the statistics library, and the embedded data, about 2.2 MB. |
| Data format | `DATA_FORMAT.md` | The input format (CSV + JSON) and the binary payload embedded in the built file. |
| Reference values | `pitch_explorer_reference.json` | Grand-average peaks and window statistics used by the tests. |
| Tests | `tests/` | The test suites described under Validation. |

The payload stores a single representation of the data: the per-trial curves at full time resolution. Per-participant means and grand averages are computed in the browser from these curves.

## How to build

```bash
python convert_mat_to_csv.py
```
```bash
python export_pitch_explorer.py
```

The first step converts the MATLAB epoch files to the `csv_dataset/` (about 28 MB) and is needed only when the source data changes. The second step builds `pitch_explorer.html` from that dataset, inlining `app.css`, `app.js`, `engine.js`, and jStat. Add `--example` to the first command to also write the sample dataset in `csv_dataset_example/`.

### Command-line arguments

Every argument has a default, so both build scripts run with no arguments. Pass `-h` / `--help` to either script to print the same information at the terminal.

`convert_mat_to_csv.py`

| Argument | Default | Description |
|---|---|---|
| `--cache-dir DIR` | `../pitch-compensation/Code/real_time_f0/matlab/data/cache` | Directory holding the MATLAB epoch files (`P*_*.mat`). |
| `--out DIR` | `csv_dataset/` | Output dataset directory. |
| `--example` | off | Also write a 5-trial-per-participant sample to `csv_dataset_example/`. |

`export_pitch_explorer.py`

| Argument | Default | Description |
|---|---|---|
| `--data-dir DIR` | `csv_dataset/` | Dataset directory written by `convert_mat_to_csv.py`. |
| `--template FILE` | `app_template.html` | HTML template to inject the payload into. |
| `--out FILE` | `pitch_explorer.html` | Output HTML file. The reference JSON is written alongside it as `<out>_reference.json`. |

## Validation

Every number in the browser is computed by one engine, `engine.js`, which the build inlines into `pitch_explorer.html` and `tests/test_engine.js` loads directly, so the tested code is the code that runs in the page. The engine is checked against sources that share none of its code:

1. The averaging into per-participant means and grand averages is also implemented in `export_pitch_explorer.py`, which writes `pitch_explorer_reference.json`. `tests/test_engine.js` recomputes every reference value with the engine, and `tests/test_export.py` re-derives the same values in Python from the embedded payload.
2. The *t*-distribution comes from jStat in the engine and from scipy in the Python build. `tests/test_scipy_check.py` additionally hands the engine's own per-participant difference vectors to `scipy.stats.ttest_1samp` and confirms the engine's *t*, *p*, *d_z*, and confidence intervals.
3. The smoothing is a port of MATLAB's `smoothdata`. Both the JavaScript and the Python port are checked against a frozen MATLAB fixture, `tests/fixtures/gauss_fixture.csv`.

`tests/test_roundtrip.py` traces the values from the original MATLAB files through the CSV stage into the payload and re-derives the grand average: the quantized values agree to within 0.01 cents. `tests/test_validation.py` supplies a series of malformed datasets and confirms that the exporter rejects each one with a message identifying the problem.

```bash
python tests/test_export.py
```
```bash
node tests/test_engine.js
```
```bash
python tests/test_scipy_check.py
```
```bash
python tests/test_roundtrip.py
```
```bash
python tests/test_validation.py
```

To test the user interface, `tests/test_ui.html` loads the built tool in a frame, operates its controls, and compares the resulting DOM against `pitch_explorer_reference.json`. Serve the folder and open the page over HTTP, because a `file://` page cannot frame another `file://` file:

```bash
python -m http.server 8000     # then open http://localhost:8000/tests/test_ui.html
```

The suites run 148 command-line checks and 66 user-interface checks. All 214 pass.

The command-line tests need Python 3 with numpy and scipy, and Node.js 18 or later.

## Notes

- An early pilot included 18 participants. The recordings now cover 31 participants, of which the tool includes 28. Three participants who were not naive to the purpose of the experiment are excluded.
- The measurement is the produced voice (`signalIn`), consistent with the thesis analysis pipeline.
- The audio interface operated at 48 kHz, with Audapter processing at 24 kHz. Both rates are read from the recordings and recorded in `dataset.json`.
