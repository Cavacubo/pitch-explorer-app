# Recording configuration: parameter reference

De-identified reference for the parameters used to record the dataset included with Pitch Explorer. These mirror the recording code's configuration (the Audapter setup and the per-session config struct), with no participant names, codes, or session labels. This folder holds the two template files used at recording time: [`pitch_onset.ost`](pitch_onset.ost) (trial state machine) and [`pitch_shift.pcf`](pitch_shift.pcf) (pitch-shift rule).

Narrative context for these values is in [`../PROVENANCE.md`](../PROVENANCE.md).

## Fixed across the study

| Parameter | Value |
|---|---|
| Audio-interface (hardware) sample rate | 48 kHz |
| Perturbation magnitude | ±100 cents (±1 semitone) |
| Perturbation duration | 200 ms (OST state 3) |
| Pre-perturbation baseline hold | randomized per trial (see *Configured per session*) |
| Vowel-onset detection | intensity-rise-hold, threshold 0.03 (normalized RMS), hold 30 ms, RMS slope window 30 ms |
| Perturbed : control ratio | 0.70 : 0.30, randomized order |
| Up : down split among perturbed trials | 0.50 : 0.50 |
| Auditory feedback mode | 3 (speech + masking noise) |
| Masking noise | pink noise, normalized to unit RMS |
| Masking level | about 75 dB SPL, sound-level-meter calibrated (Audapter `fb3Gain = 0.0305`) |
| Feedback ramp (onset / offset) | 20 ms |
| F0 estimator (offline) | SWIPE′: `dt = 2 ms`, `dlog2p = 1/96`, `dERBs = 0.1`, `sTHR = 0.3` |
| Baseline window (offline, for cents) | −200 to 0 ms before perturbation onset |
| Epoch | −500 to +1000 ms, 2 ms step (751 samples) |

## Configured per session

The recording code defines two processing-rate configurations (both at 48 kHz hardware):

| Parameter | Configuration A | Configuration B |
|---|---|---|
| Software processing rate | 16 kHz | 24 kHz |
| Downsampling factor | 3 | 2 |
| ASIO buffer size | 96 samples | 128 samples |
| Randomized baseline range (OST state 2) | 0.20 to 0.50 s | 0.75 to 1.20 s |

F0 detection range is set by speaker: **150 to 350 Hz** (female), **75 to 180 Hz** (male).

## Audapter parameter calls (recording driver)

Set once per session, or per trial where noted:

| Call | Value |
|---|---|
| `downFact` | downsampling factor (2 or 3) |
| `srate` | software processing rate (hardware ÷ `downFact`) |
| `frameLen` | ASIO buffer ÷ `downFact` |
| `fb` | 3 (feedback mode: speech + masking noise) |
| `fb3Gain` | 0.0305 (masking level about 75 dB SPL) |
| `rampLen` | 0.02 (20 ms) |
| `bPitchShift` | 1 on perturbed trials, 0 on control (**per trial**) |
| `ost` | a per-trial randomized copy of `pitch_onset.ost` (randomized baseline duration) |
| `pcf` | `pitch_shift.pcf` |

## Template files in this folder

- **`pitch_onset.ost`** — the OST state machine, which detects vowel onset, holds a baseline period, applies the perturbation for 200 ms, and then ends. At run time the baseline-hold duration is randomized within the configured range, so the interval from trial start to perturbation onset varies from trial to trial.
- **`pitch_shift.pcf`** — the PCF pitch-shift rule: the perturbation state applies a one-semitone (100-cent) shift, with the sign set per trial (`bPitchShift`) and control trials disabling it.
