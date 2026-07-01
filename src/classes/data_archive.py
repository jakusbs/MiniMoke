"""
Helpers for archiving each finished measurement:

  * copy the saved data file to the server (a general folder and a per-operator
    folder), and
  * append a one-row summary to a lab-notebook CSV.

All functions are filesystem-only and defensive: the caller wraps them so a
missing server share (e.g. the Z: drive not mounted) logs a warning instead of
crashing the app.
"""

import os
import csv
import shutil


LAB_NOTEBOOK_FILENAME = "lab_notebook_MINImoke.csv"

# Maps a procedure parameter name -> its lab-notebook column.  Any procedure
# that exposes one of these parameters fills the matching column; the rest stay
# blank for that row.  Add a line here when a new parameter should be logged.
PARAM_TO_COLUMN = {
    "b":            "Field (A)",
    "b_min":        "Field start (A)",
    "b_max":        "Field stop (A)",
    "b_step":       "Field step (A)",
    "sweep_freq":   "Sweep frequency (Hz)",
    "num_sweeps":   "Num sweeps",
    "x":            "X (mm)",
    "x_min":        "X start (mm)",
    "x_max":        "X stop (mm)",
    "x_step":       "X step (mm)",
    "y":            "Y (mm)",
    "y_min":        "Y start (mm)",
    "y_max":        "Y stop (mm)",
    "y_step":       "Y step (mm)",
    "repeat_num":   "Repeat number",
    "volt":         "Lockin voltage (V)",
    "sensi":        "Lockin sensitivity (V)",
    "lockin_freq":  "Lockin frequency (Hz)",
    "chopper_freq": "Chopper frequency (Hz)",
    "time_const":   "Lockin time constant (s)",
    "phase":        "Lockin phase (deg)",
    "acq_time":     "Acquisition time (s)",
    "demod":        "Modulation channel",
    "freq":         "Modulation frequency (Hz)",
    "mod_amp":      "Modulation amplitude (V)",
    "lockin_bw":    "Lockin bandwidth (Hz)",
    "rate":         "Sampling rate (Hz)",
    "cst_out1":     "Const output 1 (V)",
    "cst_out2":     "Const output 2 (V)",
    "duration":     "Duration (s)",
    "interval":     "Sampling interval (s)",
}

# Fixed, ordered lab-notebook header: identity/meta columns, then the parameter
# columns (grouped: field / position / lock-in / modulation / time), then tail.
LAB_NOTEBOOK_COLUMNS = [
    "Date", "Time", "Scan type", "Sample ID", "Operator",
    "Setup", "Geometry", "Stage type",
    # field
    "Field (A)", "Field start (A)", "Field stop (A)", "Field step (A)",
    "Sweep frequency (Hz)", "Num sweeps",
    # position
    "X (mm)", "X start (mm)", "X stop (mm)", "X step (mm)",
    "Y (mm)", "Y start (mm)", "Y stop (mm)", "Y step (mm)", "Repeat number",
    # lock-in
    "Lockin voltage (V)", "Lockin sensitivity (V)", "Lockin frequency (Hz)",
    "Chopper frequency (Hz)", "Lockin time constant (s)", "Lockin phase (deg)",
    "Acquisition time (s)",
    # modulation / DAC
    "Modulation channel", "Modulation frequency (Hz)", "Modulation amplitude (V)",
    "Lockin bandwidth (Hz)", "Sampling rate (Hz)", "Const output 1 (V)", "Const output 2 (V)",
    # time-domain
    "Duration (s)", "Sampling interval (s)",
    # tail
    "Total points", "Measurement duration (s)", "File path",
]


def append_lab_notebook(notebook_path: str, row: dict) -> None:
    """Append one row to the lab-notebook CSV, writing the header if it is new.

    ``row`` is keyed by (a subset of) ``LAB_NOTEBOOK_COLUMNS``; unknown keys are
    ignored and missing ones are left blank, so the header stays stable.
    """
    directory = os.path.dirname(notebook_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    is_new = not os.path.exists(notebook_path)
    with open(notebook_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LAB_NOTEBOOK_COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def copy_file(src_file: str, dest_dir: str) -> str:
    """Copy *src_file* into *dest_dir* (created if needed); return the new path."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src_file))
    shutil.copy2(src_file, dest)
    return dest


def safe_folder_name(name: str) -> str:
    """Make *name* safe to use as a single folder name.

    Replaces characters that are invalid in Windows paths (\\ / : * ? " < > |)
    and trims surrounding whitespace/dots, so a sample name can be used as a
    folder without breaking the path.
    """
    name = (name or "").strip()
    for bad in '\\/:*?"<>|':
        name = name.replace(bad, "_")
    name = name.strip(" .")
    return name or "unnamed"
