# Data provenance and recording method

Pitch Explorer includes a derived dataset: per-trial fundamental-frequency (F0) contours already expressed in cents relative to each trial's own baseline. This document records how those contours were produced (the experiment, the recording hardware, the real-time processing, and the offline F0 extraction), so the dataset can be understood and reproduced without the original recording code.

Pitch Explorer takes those contours and lets a researcher explore them in the browser. It averages across participants and trials, and splits the view by shift, gender, participant, and individual trial. The user sets the baseline and analysis windows, reads a paired comparison between them (with an effect size and a confidence interval), and exports the chart as a PNG image or the displayed data as a CSV file. The tool's input format is documented in [`DATA_FORMAT.md`](DATA_FORMAT.md), the analysis it performs in [`REPORT.md`](REPORT.md), and the exact recording parameters and OST/PCF templates in [`recording_config/`](recording_config/).

## The experiment

Participants sustained the vowel /a/ while their auditory feedback was pitch-shifted in real time on a subset of trials. Each trial is one of three conditions:

- control — feedback unshifted
- −100 cents — feedback shifted down one semitone
- +100 cents — feedback shifted up one semitone

The shift lasts 200 ms and begins after a randomized baseline period following vowel onset. About 70% of trials were perturbed and 30% were control, in randomized order, with the perturbed trials split evenly between upward and downward shifts. Masking noise was mixed into the feedback throughout (see "Auditory feedback and masking" below). The measure of interest is the compensatory change in produced F0, that is, the voice moving opposite the imposed shift.

Thirty-one participants were recorded, and the included dataset contains data from 28 of them (three non-naïve participants excluded). Sample composition and exclusions are detailed in [`REPORT.md`](REPORT.md) §2.

## Recording hardware

- Audio interface: RME Fireface (Fireface UC), ASIO, running at 48 kHz.
- Microphone: RØDE NT1 (5th generation) condenser microphone on a boom arm.
- Headphones: closed Sennheiser HD 25 (70 Ω).

## Auditory feedback and masking

Feedback was returned to the headphones in real time with added masking noise (Audapter feedback mode 3: speech + noise). The masking signal is pink noise (normalized to unit RMS), presented at about 75 dB SPL, set by the Audapter gain `fb3Gain = 0.0305` and calibrated to that target with a sound-level meter. Feedback output was ramped 20 ms at onset and offset to avoid clicks.

## Real-time processing (Audapter)

Real-time pitch shifting and feedback used Audapter (Cai et al., 2008). Key parameters (full list in [`recording_config/parameters.md`](recording_config/parameters.md)):

- Hardware sample rate 48 kHz. Software processing rate 16 kHz or 24 kHz depending on the session (downsampling factor 3 or 2), with an ASIO buffer of 96 or 128 samples.
- The trial structure is a small state machine defined by an Audapter OST file ([`recording_config/pitch_onset.ost`](recording_config/pitch_onset.ost)). It detects vowel onset (intensity rise), holds a baseline period, applies the perturbation for 200 ms, and then ends. The baseline period is randomized per trial within a configured range, so the interval from trial start to perturbation onset varies from trial to trial.
- The pitch-shift rule is an Audapter PCF file ([`recording_config/pitch_shift.pcf`](recording_config/pitch_shift.pcf)). The perturbation state applies a one-semitone (100-cent) shift. The sign is set per trial, and control trials disable the shift.

## Offline F0 extraction and epoching

After recording, each trial's produced audio (the clean microphone signal) was analyzed offline:

- F0 estimated with SWIPE′ (Camacho & Harris, 2008), parameters `dt = 2 ms`, `dlog2p = 1/96`, `dERBs = 0.1`, `sTHR = 0.3`.
- F0 search range by speaker: 150 to 350 Hz (female), 75 to 180 Hz (male).
- Each trial's baseline F0 is the mean over the −200 to 0 ms window before perturbation onset. F0 is converted to cents as `1200 · log2(F0 / baseline F0)`.
- Epochs are time-locked to perturbation onset, spanning −500 to +1000 ms at a 2 ms step (751 samples).

These are the contours the tool embeds and averages.

## From recordings to the included dataset

1. `build_epoch_cache` (MATLAB) runs the SWIPE′ extraction above and writes one compact epoch file per participant.
2. `convert_mat_to_csv.py` re-expresses those as the portable CSV dataset (`dataset.json` + `trials.csv` + `curves/*.csv`), applies the exclusions, and records the sampling metadata read from the recordings.
3. `export_pitch_explorer.py` embeds the dataset into the single-file tool.

Steps 2 and 3 are in this repository. Step 1 and the recording driver are part of the MATLAB pipeline and are not included here.

## Software and requirements (recording side)

- MATLAB with the Signal Processing Toolbox and Audio System Toolbox.
- Audapter (real-time perturbation package; Cai et al., 2008) with its MEX binary.
- An ASIO audio interface (here, the Fireface).

## Reproducing or adapting the setup

The recording configuration is parameterized. To run a comparable experiment, set the values in [`recording_config/parameters.md`](recording_config/parameters.md) (sample rates, buffer, shift magnitude, perturbed/control ratio, masking level, baseline range, F0 ranges), use the OST and PCF templates in [`recording_config/`](recording_config/), and drive Audapter as above. To visualize any resulting data in this tool, convert it to the CSV format described in [`DATA_FORMAT.md`](DATA_FORMAT.md) (or run `convert_mat_to_csv.py` on the epoch files) and rebuild.

## References

- Cai, S., Boucek, M., Ghosh, S. S., Guenther, F. H., & Perkell, J. S. (2008). A system for online dynamic perturbation of formant frequencies and results from perturbation of the Mandarin triphthong /iau/. *Proceedings of the 8th International Seminar on Speech Production (ISSP)*, 65–68.
- Camacho, A., & Harris, J. G. (2008). A sawtooth waveform inspired pitch estimator for speech and music. *The Journal of the Acoustical Society of America*, 124, 1638–1652.

## Questions

For questions about the recording setup or the dataset, contact the author, Albina Serdiuk.
