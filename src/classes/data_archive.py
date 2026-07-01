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


# Fixed lab-notebook columns.  Kept deliberately small — the full parameter set
# is captured in the "Parameters" cell — and mirrors the style of the shared
# lab notebook (date/time/scan type/sample/operator/geometry/file/...).
LAB_NOTEBOOK_COLUMNS = [
    "Date",
    "Time",
    "Scan type",
    "Sample ID",
    "Operator",
    "Geometry",
    "Stage type",
    "Total points",
    "Duration (s)",
    "File path",
    "Parameters",
]

LAB_NOTEBOOK_FILENAME = "lab_notebook_MINImoke.csv"


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
