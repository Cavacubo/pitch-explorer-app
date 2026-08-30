#!/usr/bin/env python3
"""Validation test 4 (Python): the exporter refuses malformed input.

The CSV input contract (DATA_FORMAT.md) lets another researcher bring their own data. A mistake in that data must be caught and named at build time. This test covers the malformed-input cases:
for each way a dataset can be wrong, it copies the example dataset, breaks
exactly one thing, runs the exporter, and asserts it exits non-zero with a
message that names the file and the problem.

A positive control (the unmodified example builds) guards against the test
passing because the exporter is broken and rejects everything.

Skips cleanly when csv_dataset_example/ is not present.

Run:  python tests/test_validation.py
"""

import csv, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "csv_dataset_example")
EXPORTER = os.path.join(ROOT, "export_pitch_explorer.py")

failures = []


def check(cond, msg):
    print(f"  [{'OK ' if cond else 'XX '}] {msg}")
    if not cond:
        failures.append(msg)


def build(data_dir, out_dir):
    """Run the exporter on data_dir; return (returncode, combined output)."""
    out = os.path.join(out_dir, "out.html")
    r = subprocess.run(
        [sys.executable, EXPORTER, "--data-dir", data_dir, "--out", out],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def edit_json(path, mutate):
    import json

    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    mutate(d)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f)


def edit_lines(path, mutate):
    with open(path, encoding="utf-8", newline="") as f:
        lines = f.read().splitlines()
    lines = mutate(lines)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")


def first_curves_id(data_dir):
    import json

    with open(os.path.join(data_dir, "dataset.json"), encoding="utf-8") as f:
        return json.load(f)["participants"][0]


# each case: (label, mutation(dataDir), expected substring in the exit message)
def case_two_controls(d):
    edit_json(
        os.path.join(d, "dataset.json"),
        lambda j: j["conditions"].__setitem__(
            1, {**j["conditions"][1], "isControl": True}
        ),
    )


def case_undeclared_condition(d):
    path = os.path.join(d, "trials.csv")

    def m(lines):
        row = lines[1].split(",")
        row[3] = "bogus99"
        lines[1] = ",".join(row)
        return lines

    edit_lines(path, m)


def case_bad_time_grid(d):
    p = first_curves_id(d)
    path = os.path.join(d, p["curvesFile"])

    def m(lines):
        h = lines[0].split(",")
        h[1] = str(float(h[1]) + 1)
        lines[0] = ",".join(h)
        return lines

    edit_lines(path, m)


def case_wrong_column_count(d):
    p = first_curves_id(d)
    path = os.path.join(d, p["curvesFile"])
    edit_lines(path, lambda lines: [",".join(r.split(",")[:-1]) for r in lines])


def case_wrong_ntrials(d):
    edit_json(
        os.path.join(d, "dataset.json"),
        lambda j: j["participants"][0].__setitem__("nTrials", 999),
    )


def case_missing_curves_file(d):
    p = first_curves_id(d)
    os.remove(os.path.join(d, p["curvesFile"]))


def case_missing_trials_row(d):
    path = os.path.join(d, "trials.csv")
    edit_lines(path, lambda lines: [lines[0]] + lines[2:])  # drop the first data row


def case_all_empty_curves(d):
    """Blank every sample value in every curves file: a dataset with no measurements."""
    import json

    with open(os.path.join(d, "dataset.json"), encoding="utf-8") as f:
        meta = json.load(f)

    def blank(lines):
        out = [lines[0]]  # keep the time-grid header
        for row in lines[1:]:
            cells = row.split(",")
            out.append(
                ",".join([cells[0]] + [""] * (len(cells) - 1))
            )  # keep trial_index, blank the rest
        return out

    for p in meta["participants"]:
        edit_lines(os.path.join(d, p["curvesFile"]), blank)


CASES = [
    (
        "two controls",
        case_two_controls,
        "exactly one condition must have isControl true",
    ),
    ("undeclared condition", case_undeclared_condition, "is not declared in"),
    (
        "bad time grid value",
        case_bad_time_grid,
        "time grid does not match dataset.json epoch",
    ),
    (
        "wrong column count",
        case_wrong_column_count,
        "time columns, dataset.json epoch says",
    ),
    ("wrong nTrials", case_wrong_ntrials, "dataset.json says 999"),
    ("missing curves file", case_missing_curves_file, "curvesFile"),
    ("missing trials row", case_missing_trials_row, "have no row in"),
    ("all-empty curves", case_all_empty_curves, "every curve in the dataset is empty"),
]


def main():
    if not os.path.isdir(EXAMPLE):
        print(
            f"No example dataset at {EXAMPLE} — run convert_mat_to_csv.py --example first. Skipping."
        )
        return 0

    tmp_root = tempfile.mkdtemp(prefix="pex_validation_")
    try:
        # positive control: the unmodified example must build
        good = os.path.join(tmp_root, "good")
        shutil.copytree(EXAMPLE, good)
        rc, out = build(good, good)
        check(rc == 0, f"positive control: the unmodified example builds (exit {rc})")

        print("malformed input is refused with a message that names the problem:")
        for label, mutate, expected in CASES:
            d = os.path.join(tmp_root, label.replace(" ", "_"))
            shutil.copytree(EXAMPLE, d)
            mutate(d)
            rc, out = build(d, d)
            got = expected.lower() in out.lower()
            snippet = next(
                (
                    ln.strip()
                    for ln in out.splitlines()
                    if expected.lower() in ln.lower()
                ),
                "",
            )
            check(
                rc != 0 and got,
                f"{label:22s} -> exit {rc}, message: {snippet[:80] or '(expected text not found)'}",
            )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print(
        "\n"
        + (
            "PASS — every malformed dataset is refused with a clear message."
            if not failures
            else f"{len(failures)} FAILURE(S)"
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
