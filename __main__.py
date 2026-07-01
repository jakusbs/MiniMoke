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
                ['b_min', 'b_max', 'b_step', 'sweep_freq', 'num_sweeps', 'chopper_freq', 'volt', 'sensi', 'time_const', 'phase', 'acq_time'],
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