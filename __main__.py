# ███╗   ███╗██╗███╗   ██╗██╗    ███╗   ███╗ ██████╗ ██╗  ██╗███████╗
# ████╗ ████║██║████╗  ██║██║    ████╗ ████║██╔═══██╗██║ ██╔╝██╔════╝
# ██╔████╔██║██║██╔██╗ ██║██║    ██╔████╔██║██║   ██║█████╔╝ █████╗
# ██║╚██╔╝██║██║██║╚██╗██║██║    ██║╚██╔╝██║██║   ██║██╔═██╗ ██╔══╝
# ██║ ╚═╝ ██║██║██║ ╚████║██║    ██║ ╚═╝ ██║╚██████╔╝██║  ██╗███████╗
# ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝    ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝
#
# Description:
#   Mini-MOKE software for InterMag lab at ETHZ.
#   Based on pymeasure. Custom UI styling applied via minimoke_style.qss.

import os
import sys
import time

try:
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
except ImportError:
    pass

import pyqtgraph as pg
from pymeasure.experiment import Results, unique_filename
from pymeasure.display.Qt import QtWidgets
from PyQt5.QtGui import QIcon, QFontDatabase

from src.ui         import UIWindow, UserManualTab, LiveTab, LongitudinalMotorsTab, PolarMotorsTab
from src.procedures import B_Sweep, B_Sweep_Lockin, X_Sweep, Y_Sweep, XY_Sweep, TimeMeasurement
from src.classes    import log
from src.classes.data_archive import (
    append_lab_notebook, copy_file, safe_folder_name, LAB_NOTEBOOK_FILENAME, PARAM_TO_COLUMN,
)

# ── DLL path setup ────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

dll_dir = os.path.join(base_dir, "libs")

if os.path.exists(dll_dir):
    # os.add_dll_directory only exists on Windows (Python 3.8+).  Guard it so
    # the entry point doesn't raise AttributeError on other platforms.
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(dll_dir)
        print(f"Added DLL directory: {dll_dir}")
    else:
        print(f"DLL directory found (non-Windows, not registered): {dll_dir}")
else:
    print(f"Warning: DLL directory not found at {dll_dir}")


# ── Stylesheet loader ─────────────────────────────────────────────────────────

def load_stylesheet() -> str:
    """Load the custom QSS file, with a sensible fallback if not found."""
    qss_path = os.path.join(base_dir, "minimoke_style.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            return f.read()
    # Minimal inline fallback (dark base only)
    return "QWidget { background-color: #0A0E1A; color: #E2E8F0; }"


def configure_pyqtgraph():
    """Apply a matching dark theme to all pyqtgraph plots."""
    pg.setConfigOptions(
        background="#0D1220",   # plot background — matches panel colour
        foreground="#64748B",   # axis lines, tick labels
        antialias=True,
    )


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(UIWindow):
    """
    Main application window for the Mini-MOKE setup.
    Defines experiment tabs (B-Sweep, X-Sweep, Y-Sweep, XY-Sweep),
    plus auxiliary tabs for the user manual, motor control and live readings.
    """

    def __init__(self):
        super().__init__(
            procedure_class=[B_Sweep, B_Sweep_Lockin, X_Sweep, Y_Sweep, XY_Sweep, TimeMeasurement],
            inputs=[
                ['b_min', 'b_max', 'b_step', 'sweep_freq', 'num_sweeps'],
                ['b_min', 'b_max', 'b_step', 'sweep_freq', 'num_sweeps', 'volt', 'sensi', 'lockin_freq', 'time_const', 'phase', 'acq_time'],
                ['volt', 'sensi', 'lockin_freq', 'time_const', 'phase', 'acq_time',
                 'x_min', 'x_max', 'x_step', 'y', 'b', 'repeat_num'],
                ['volt', 'sensi', 'lockin_freq', 'time_const', 'phase', 'acq_time',
                 'y_min', 'y_max', 'y_step', 'x', 'b', 'repeat_num'],
                ['volt', 'sensi', 'lockin_freq', 'time_const', 'phase', 'acq_time',
                 'x_min', 'x_max', 'x_step', 'y_min', 'y_max', 'y_step', 'b', 'repeat_num'],
                ['b', 'volt', 'sensi', 'lockin_freq', 'time_const', 'phase', 'acq_time',
                 'x', 'y', 'duration', 'interval'],
            ],
            displays=['sweep_freq'],
            x_axis='Magnetic Field (T)',
            y_axis='Voltage DC (V)',
            linewidth=2,
            widget_list=(
                UserManualTab("User Manual"),
                LiveTab("Live measurements"),
            ),
            motors_widget=(
                LongitudinalMotorsTab("Longitudinal motor control"),
                PolarMotorsTab("Polar motor control"),
            ),
            directory_input=True,
        )
        self.setWindowTitle('MiniMOKE  · Magnetism and Interface Physics · ETHZ')
        self.setWindowIcon(QIcon('assets/ehv.ico'))

        # Server base: data + lab notebook are copied under here after each run.
        # General folder    -> <base>/Data/<date>/<mode>/
        # Per-operator folder -> <base>/<operator>/Data/<date>/<mode>/
        self.server_line.setText(r"Z:\projects\MOKE_mini")

    # ── Post-measurement archiving ────────────────────────────────────────────

    def running(self, experiment):
        super().running(experiment)
        self._run_start = time.time()

    def finished(self, experiment):
        super().finished(experiment)
        self._archive_experiment(experiment)

    def _archive_experiment(self, experiment):
        """Copy the finished data file to the server and append a lab-notebook row.

        Best-effort: if the server share is not mounted (e.g. no Z: drive) or a
        write fails, it logs a warning and never interrupts the measurement flow.
        """
        from datetime import datetime

        try:
            src_file = experiment.data_filename
        except Exception:
            return
        if not src_file or not os.path.exists(src_file):
            return

        procedure   = experiment.procedure
        operator    = self.operator_line.text().strip() or "unknown"
        now         = datetime.now()
        date_folder = now.strftime("%Y-%m-%d")

        try:
            duration = round(time.time() - getattr(self, "_run_start", time.time()), 1)
        except Exception:
            duration = ""
        total_points = getattr(procedure, "nb_it_md", "")
        if not isinstance(total_points, (int, float)):
            total_points = ""

        sample_name = self.sample_name_line.text()
        row = {
            "Date":                      now.strftime("%Y-%m-%d"),
            "Time":                      now.strftime("%H:%M:%S"),
            "Scan type":                 getattr(procedure, "name", type(procedure).__name__),
            "Sample ID":                 sample_name,
            "Operator":                  operator,
            "Setup":                     self._setup_mode,        # longitudinal / polar
            "Geometry":                  ("PMOKE" if self._setup_mode == "polar"
                                          else getattr(self, "_geometry", "")),  # PMOKE / LMOKE
            "Stage type":                "Thorlabs" if self._setup_mode == "longitudinal" else "Trinamic",
            "Total points":              total_points,
            "Measurement duration (s)":  duration,
            "File path":                 os.path.normpath(src_file),
        }
        # Fill the measurement settings into their named columns.
        try:
            for pname, pobj in procedure.parameter_objects().items():
                column = PARAM_TO_COLUMN.get(pname)
                if column:
                    row[column] = pobj.value
        except Exception:
            pass

        # Local lab notebook: <Desktop>/lab notebook/lab_notebook_MINImoke.csv
        try:
            desktop  = os.path.dirname(os.path.normpath(self.directory)) if self.directory_input else ""
            local_nb = os.path.join(desktop, "lab notebook", LAB_NOTEBOOK_FILENAME)
            append_lab_notebook(local_nb, row)
        except Exception as exc:
            log.warning(f"Could not update local lab notebook: {exc}")

        # Server copies and the server lab notebook.
        server_base = self.server_line.text().strip()
        if not server_base:
            return
        server_base = os.path.normpath(server_base)   # clean, OS-native separators
        #  general    -> <base>/Data/<date>/<setup>/
        #  per-operator -> <base>/<operator>/<sample>/<setup>/<date>/
        general_dir  = os.path.join(server_base, "Data", date_folder, self._setup_mode)
        operator_dir = os.path.join(server_base, safe_folder_name(operator),
                                    safe_folder_name(sample_name), self._setup_mode, date_folder)
        for dest_dir in (general_dir, operator_dir):
            try:
                copy_file(src_file, dest_dir)
            except Exception as exc:
                log.warning(f"Could not copy data to server '{dest_dir}': {exc}")
        try:
            # Directly in the server base (Z:\projects\MOKE_mini\lab_notebook_MINImoke.csv).
            append_lab_notebook(os.path.join(server_base, LAB_NOTEBOOK_FILENAME), row)
        except Exception as exc:
            log.warning(f"Could not update server lab notebook: {exc}")

    def queue(self, procedure=None):
        """Queue the next experiment and persist results to the data folder.

        Final path structure:
            <base_directory>/<YYYY-MM-DD>/<longitudinal|polar>/<prefix><datetime>.csv
        """
        if procedure is None:
            procedure = self.make_procedure()

        # Reject configurations the hardware cannot honour (e.g. a field sweep
        # faster than the Hall probe can follow) before anything is queued.
        validate = getattr(procedure, "queue_validation_error", None)
        if callable(validate):
            message = validate()
            if message:
                QtWidgets.QMessageBox.warning(self, "Cannot queue measurement", message)
                return

        # Build <base>/<date>/<mode>/ and create it if needed
        from datetime import date
        date_folder = date.today().strftime("%Y-%m-%d")
        save_dir = os.path.join(self.directory, date_folder, self._setup_mode)
        os.makedirs(save_dir, exist_ok=True)

        file = unique_filename(
            directory=save_dir,
            prefix=self.sample_name_line.text() + "_" + procedure.name + "_",
            datetimeformat="%Y-%m-%d-%Hh%M",
        )
        results    = Results(procedure, file)
        experiment = self.new_experiment(results)
        self.manager.queue(experiment)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Mini MOKE")

    configure_pyqtgraph()
    app.setStyleSheet(load_stylesheet())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())