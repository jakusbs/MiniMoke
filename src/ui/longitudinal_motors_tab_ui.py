"""
Description:
    Longitudinal motor control tab — odometer style.
    Each axis shows ▲ digit ▼ for every decimal place (10, 1, 0.1, 0.01, 0.001).
    The digit between the buttons is the actual live digit from the current position.

    Moves are dispatched in a QThread so the GUI never freezes while the motor runs.

    Thread safety:
        All hardware access (moves AND the poll timer) is serialised through
        active_stage.hw_lock — the same lock that procedure worker threads
        acquire when they call stage.move_*_to() etc.  This prevents the
        "unexpected command" ThorlabsError caused by two threads hitting the
        USB serial port simultaneously.
"""

import math
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from pymeasure.display.widgets import TabWidget

from src.classes import longitudinal_stage as stage
from src.classes import active_stage       # for the shared hw_lock

STEPS         = [10.0,  1.0,  0.1,   0.01,  0.001]
STEP_DECIMALS = [-1,    0,    1,     2,     3]

# UI sizing constants — tweak here to resize all motor controls at once
_BTN_W, _BTN_H     = 24, 16   # step ▲/▼ button size (px)
_DIGIT_W, _DIGIT_H = 24, 22   # digit label size (px)


# ---------------------------------------------------------------------------
# Background worker — runs a single callable in a QThread
# ---------------------------------------------------------------------------

class _MoveWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, fn, *args):
        super().__init__()
        self._fn   = fn
        self._args = args

    def run(self):
        # hw_lock is a threading.Lock; procedure threads also acquire it,
        # so this guarantees mutual exclusion with the pymeasure worker.
        with active_stage.hw_lock:
            try:
                self._fn(*self._args)
            except Exception as e:
                print(f"LongitudinalStage move error: {e}")
        self.finished.emit()


# ---------------------------------------------------------------------------
# Digit helpers
# ---------------------------------------------------------------------------

def _extract_digit(value: float, step: float, decimal_pos: int) -> str:
    """Return the single odometer digit at *decimal_pos* of *value* (in mm).

    All digits are derived from the value rounded ONCE to the finest displayed
    place, then sliced with integer (floor) division.  Rounding each digit
    independently (the previous behaviour) let a higher place round up while the
    lower place failed to carry — e.g. 0.006 mm was shown as 0.016 mm — making
    the readout appear to jump by ~10 um every few 1 um steps even though the
    motor moved correctly.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "?"
    finest = max(STEP_DECIMALS)                        # smallest place shown (3 -> 0.001 mm)
    scaled = int(round(abs(value) * (10 ** finest)))   # integer count of finest units
    return str((scaled // (10 ** (finest - decimal_pos))) % 10)


# ---------------------------------------------------------------------------
# Single axis row widget
# ---------------------------------------------------------------------------

class AxisRow(QtWidgets.QWidget):
    def __init__(self, axis, move_fn, home_fn, parent=None):
        super().__init__(parent)
        self.axis = axis
        self.move_fn = move_fn
        self.home_fn = home_fn
        self._digit_labels = []
        self._sign_label = None
        self._build()

    def _build(self):
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)

        # Axis label
        axis_lbl = QtWidgets.QLabel(self.axis.upper())
        axis_lbl.setObjectName("axisLabel")
        axis_lbl.setFixedWidth(16)
        axis_lbl.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        row.addWidget(axis_lbl)
        row.addSpacing(3)

        # Sign
        self._sign_label = QtWidgets.QLabel("+")
        self._sign_label.setObjectName("digitLabel")
        self._sign_label.setFixedWidth(12)
        self._sign_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        row.addWidget(self._sign_label)

        # Digit columns
        for idx, (step, dec) in enumerate(zip(STEPS, STEP_DECIMALS)):
            col = QtWidgets.QWidget()
            col.setObjectName("digitCol")
            vbox = QtWidgets.QVBoxLayout(col)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)

            btn_up = QtWidgets.QPushButton("▲")
            btn_up.setObjectName("stepBtn")
            btn_up.setFixedSize(_BTN_W, _BTN_H)
            btn_up.clicked.connect(lambda _, s=step: self.move_fn(+s))

            digit_lbl = QtWidgets.QLabel("0")
            digit_lbl.setObjectName("digitLabel")
            digit_lbl.setFixedSize(_DIGIT_W, _DIGIT_H)
            digit_lbl.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._digit_labels.append(digit_lbl)

            btn_dn = QtWidgets.QPushButton("▼")
            btn_dn.setObjectName("stepBtn")
            btn_dn.setFixedSize(_BTN_W, _BTN_H)
            btn_dn.clicked.connect(lambda _, s=step: self.move_fn(-s))

            vbox.addWidget(btn_up,    alignment=Qt.AlignCenter)
            vbox.addWidget(digit_lbl, alignment=Qt.AlignCenter)
            vbox.addWidget(btn_dn,    alignment=Qt.AlignCenter)
            row.addWidget(col)

            # Decimal point between 1.0 and 0.1 columns
            if step == 1.0:
                dot = QtWidgets.QLabel(".")
                dot.setObjectName("decimalDot")
                dot.setFixedWidth(7)
                dot.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                row.addWidget(dot)

        # mm label
        unit = QtWidgets.QLabel("mm")
        unit.setObjectName("unitLabel")
        unit.setFixedWidth(20)
        row.addWidget(unit)
        row.addSpacing(4)

        # Set Zero button
        home_btn = QtWidgets.QPushButton("Set Zero")
        home_btn.setObjectName("homeBtn")
        home_btn.setFixedWidth(58)
        home_btn.clicked.connect(self.home_fn)
        row.addWidget(home_btn)
        row.addStretch()

    def set_position(self, value: float):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            self._sign_label.setText("?")
            for lbl in self._digit_labels:
                lbl.setText("?")
            return
        self._sign_label.setText("−" if value < 0 else "+")
        for lbl, (step, dec) in zip(self._digit_labels, zip(STEPS, STEP_DECIMALS)):
            lbl.setText(_extract_digit(value, step, dec))


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class LongitudinalMotorsTab(TabWidget, QtWidgets.QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self._worker = None   # keep reference so it isn't GC'd mid-move
        self._build()

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        # Separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setObjectName("motorSep")
        outer.addWidget(sep)
        outer.addSpacing(4)

        # Axis rows
        self.row_x = AxisRow("x", self.move_x, lambda: self.home_axis("x"))
        self.row_y = AxisRow("y", self.move_y, lambda: self.home_axis("y"))
        self.row_z = AxisRow("z", self.move_z, lambda: self.home_axis("z"))

        for row_widget in (self.row_x, self.row_y, self.row_z):
            outer.addWidget(row_widget)
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.HLine)
            line.setObjectName("motorSep")
            outer.addWidget(line)

        outer.addSpacing(12)

        # Go-to-position
        goto_group = QtWidgets.QGroupBox("Go to position")
        goto_layout = QtWidgets.QHBoxLayout(goto_group)
        goto_layout.setSpacing(8)

        for axis, attr in [("X", "x_input"), ("Y", "y_input"), ("Z", "z_input")]:
            lbl = QtWidgets.QLabel(axis)
            lbl.setObjectName("axisLabel")
            lbl.setFixedWidth(14)
            inp = QtWidgets.QLineEdit("0.000")
            inp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            inp.setFixedWidth(80)
            setattr(self, attr, inp)
            goto_layout.addWidget(lbl)
            goto_layout.addWidget(inp)

        self.go_button = QtWidgets.QPushButton("Go")
        self.go_button.setFixedWidth(36)
        self.go_button.clicked.connect(self.go_to_position)
        goto_layout.addWidget(self.go_button)
        goto_layout.addStretch()
        outer.addWidget(goto_group)
        outer.addSpacing(8)

        # Set all axes zero
        self.homing = QtWidgets.QPushButton("Set All Axes Zero")
        self.homing.clicked.connect(self.home_all)
        outer.addWidget(self.homing)
        outer.addStretch()

        self.update_positions()

        # Live polling — refresh display every 250 ms.
        # acquire(blocking=False): skip this tick if the lock is held by a
        # move thread or procedure worker rather than blocking the GUI thread.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._safe_update_positions)
        self._poll_timer.start()

    # ------------------------------------------------------------------
    # Position readout
    # ------------------------------------------------------------------

    def _get_pos(self, axis):
        try:
            v = {"x": stage.get_x_pos, "y": stage.get_y_pos, "z": stage.get_z_pos}[axis]()
            return v if v is not None else 0.0
        except Exception:
            return 0.0

    def update_positions(self):
        """Read all axes and refresh the display (call only when lock is held or safe)."""
        self.row_x.set_position(self._get_pos("x"))
        self.row_y.set_position(self._get_pos("y"))
        self.row_z.set_position(self._get_pos("z"))

    def _safe_update_positions(self):
        """
        Poll tick: only read hardware if the shared hw_lock is free.
        Uses non-blocking acquire so the GUI thread is never stalled
        waiting for a procedure worker or move thread to finish.
        """
        acquired = active_stage.hw_lock.acquire(blocking=False)
        if acquired:
            try:
                self.update_positions()
            finally:
                active_stage.hw_lock.release()
        # else: hardware is busy — skip this tick, display stays as-is

    # ------------------------------------------------------------------
    # Thread-dispatched moves — keeps the Qt event loop responsive
    # ------------------------------------------------------------------

    def _dispatch(self, fn, *args):
        """Run fn(*args) in a background thread; refresh display when done.

        Drops the request if a move is already running, preventing command
        queuing while a motor is in motion.
        """
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _MoveWorker(fn, *args)
        self._worker.finished.connect(self._safe_update_positions)
        self._worker.start()

    def move_x(self, d): self._dispatch(stage.move_x, d)
    def move_y(self, d): self._dispatch(stage.move_y, d)
    def move_z(self, d): self._dispatch(stage.move_z, d)

    def go_to_position(self):
        def _go():
            stage.move_x_to(float(self.x_input.text()))
            stage.move_y_to(float(self.y_input.text()))
            stage.move_z_to(float(self.z_input.text()))
        self._dispatch(_go)

    def home_all(self): self._dispatch(stage.home_axis)
    def home_axis(self, axis): self._dispatch(stage.home_axis, axis)