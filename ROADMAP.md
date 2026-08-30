# Roadmap: what a general-purpose tool still needs

Pitch Explorer is a single-file browser tool built on one corpus. Its design allows generalization as an extension of the existing structure. This document records what is in place, what remains, and what is out of scope, so it can be reused in a future paper's system section or future-work discussion.

## Already in place

- A documented, tool-independent input format. Plain CSV tables plus one JSON config file, fully specified in [`DATA_FORMAT.md`](DATA_FORMAT.md), with a runnable example in [`csv_dataset_example/`](csv_dataset_example/). Preparing a dataset needs no MATLAB and no knowledge of the tool's internals.
- Input validation with clear messages. The build refuses a malformed dataset and names the file, the line or column, and what was expected, so a failure points to the offending input.
- Self-describing designs. `conditions` is a list of any length with exactly one control, and `epoch` carries the time grid, so a study with three shift magnitudes, one direction, or a different baseline length describes itself in the same format. The tool reads the design from the data, including the shift magnitudes and the gender labels.
- Descriptors stored with the data. Condition, trial, and control counts, genders, epoch geometry, and sampling rates.
- User-defined analysis windows. Baseline and analysis windows are user inputs, so a reader can test whether a result depends on where the window was placed.
- A demonstration dataset. The study's own corpus serves as a ready example.

## Possible extensions

1. Load a dataset in the browser. Today a dataset is embedded at build time, so showing new data means re-running the build. A sandboxed page cannot read an arbitrary local path without user action, so three options exist:
   - file upload or drag-and-drop of the dataset folder,
   - the File System Access API, which is Chromium-only and prompts the user each session, or
   - a small local server run by the researcher.

One option should be chosen and its trade-off documented. Because the input format already exists, this extension requires only a loader.
2. Validate on a second real dataset. The format is documented, checked, and provided with a worked example, but it has been exercised on one corpus. Running another perturbation study through it unchanged would confirm that the generality holds in practice.
3. Broaden beyond pitch. The format stores a signed magnitude per condition and a labeled epoch, which is most of what a formant or time-warp study needs. What is missing is axis and label generalization, and data to check it against.
4. Generate configuration files. A form over the experiment parameters that emits a settings file plus the OST/PCF pair. It writes files only, with no hardware access.

## Out of scope for a browser tool

These are architecturally incompatible with a single self-contained web page, and each needs a native application. They belong to a discussion of the field's broader tooling needs:

- Audio-interface and ASIO detection. A browser cannot enumerate ASIO devices.
- A native desktop executable. A different stack, with per-OS builds and signing.
- A hosted tool reading an arbitrary local path. Forbidden by the browser sandbox.
- A full experiment runner. Needs MATLAB and the Audapter MEX at runtime.

## Toward a multi-study version

The extensions above together describe a generalized version of the tool: the same self-contained page, able to load any perturbation dataset in the browser, cover formant and time-warp paradigms alongside pitch, and emit the experiment-configuration files (settings + OST/PCF) a new study needs. The manifest-driven engine and tool-independent format make each of these an add-on to the existing design, and the result is a candidate artifact for a future methods or tool paper.

## Deployment

The deliverable is a single static file with no server-side component, so hosting requires only serving one file. It can be opened in a browser, sent as an attachment, or placed on any static host.
