"""
Regression tests for the MiniMOKE bug-fix pass.

These tests are intentionally *hardware-free*: every test either constructs a
fresh object with fake collaborators, or swaps the procedure modules' global
``dac`` / ``stage`` / ``hall_sensor`` / ``meas`` references for light fakes.
No real instrument command is ever issued, so the suite is safe to run on the
lab machine as well as on a developer box without any hardware attached.

Run it with either::

    python tests/test_fixes.py          # built-in runner, exit code 0 = pass
    pytest tests/test_fixes.py          # if pytest is installed

It needs the same Python packages the application uses (numpy, scipy, PyQt5,
pymeasure, pyqtgraph, ...).
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_REPO)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import time
import numpy as np

# A Qt application instance is required before importing the UI widgets.
from pymeasure.display.Qt import QtWidgets
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

import src.classes as C
from src.classes.ametek7270_class import OfflineLockin
from src.classes.longitudinal_stage_class import LongitudinalStage

# Never write to the repo's .ini files during tests.
C.proc_config.save_parameters_dict = lambda *a, **k: None
C.proc_config.save_str_dict = lambda *a, **k: None
# Speed: no real sleeping anywhere in the procedures.
time.sleep = lambda *a, **k: None


# ---------------------------------------------------------------------------
# Lightweight fakes used to isolate procedures from hardware
# ---------------------------------------------------------------------------

class FakeStage:
    enabled = False
    def move_x_to(self, *a): pass
    def move_y_to(self, *a): pass
    def move_z_to(self, *a): pass
    def move_x(self, *a): pass
    def move_y(self, *a): pass
    def move_z(self, *a): pass
    def wait_stable(self): pass
    def get_x_pos(self): return 0.0
    def get_y_pos(self): return 0.0
    def get_z_pos(self): return 0.0


class FakeDac:
    def __init__(self):
        self.reserved = False
        self.status_setup = False
        self.enabled = False
        self.coils_output = 0.0
        self.dc_output = [0.0, 0.0]
        self.reference_signal_1f = [np.zeros(4), np.zeros(4)]
        self.reference_signal_2f = [np.zeros(4), np.zeros(4)]
    def setup_aquisition(self, *a, **k): self.status_setup = True
    def start_tasks(self): pass
    def read_data(self): return np.zeros(8), np.zeros(8)
    def set_outputs_and_reset(self, *a, **k): pass
    def demodulation(self, *a, **k): return {"X": 0, "Y": 0, "R": 0, "theta": 0}


class FakeHall:
    def __init__(self, val=10.0):
        self.reserved = False
        self.enabled = True
        self.val = val
    def set_aquisition_time(self, *a): pass
    def read_mT(self): return self.val


def _patch_proc_module(mod, hall_val=10.0):
    """Point a procedure module's hardware globals at fakes; return them."""
    fakes = dict(dac=FakeDac(), stage=FakeStage(),
                 hall_sensor=FakeHall(hall_val), meas=OfflineLockin(),
                 dsp=OfflineLockin())
    for name, obj in fakes.items():
        setattr(mod, name, obj)
    return fakes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_longitudinal_wait_stable_calls_wait_move():
    """wait_stable() must actually CALL motor.wait_move() (was a no-op before)."""
    s = LongitudinalStage.__new__(LongitudinalStage)   # bypass hardware __init__
    s.enabled = True
    calls = {"x": 0, "y": 0, "z": 0}

    class FakeMotor:
        def __init__(self, key): self.key = key
        def wait_move(self): calls[self.key] += 1

    s.motor_x, s.motor_y, s.motor_z = FakeMotor("x"), FakeMotor("y"), FakeMotor("z")
    s.wait_stable()
    assert calls == {"x": 1, "y": 1, "z": 1}, f"wait_move not called for every axis: {calls}"


def test_longitudinal_backlash_applied():
    """Backlash compensation must be programmed on every axis at the configured
    distance, in device steps (scale=False)."""
    s = LongitudinalStage.__new__(LongitudinalStage)   # bypass hardware __init__
    s.enabled = True
    s.mm2steps = 1000.0
    s.backlash_mm = 0.02
    calls = {}

    class FakeMotor:
        def __init__(self, key): self.key = key
        def setup_gen_move(self, backlash_distance=None, scale=True):
            calls[self.key] = (backlash_distance, scale)

    s.motor_x, s.motor_y, s.motor_z = FakeMotor("x"), FakeMotor("y"), FakeMotor("z")
    s._apply_backlash()

    expected = int(round(0.02 * 1000.0))   # 20 steps
    assert calls == {"x": (expected, False), "y": (expected, False), "z": (expected, False)}, calls


def test_active_stage_enabled_is_bool_and_tracks_switch():
    """active_stage.enabled must be a real bool (broken @property before)."""
    val = C.active_stage.enabled
    assert isinstance(val, bool), f"active_stage.enabled is {type(val)!r}, not bool"

    C.set_active_stage("polar")
    assert C.active_stage.enabled == C.polar_stage.enabled
    C.set_active_stage("longitudinal")
    assert C.active_stage.enabled == C.longitudinal_stage.enabled

    # Unknown attributes still raise AttributeError (forwarding is scoped).
    try:
        C.active_stage.does_not_exist
        raise AssertionError("expected AttributeError for unknown attribute")
    except AttributeError:
        pass


def test_offline_lockin_interface():
    """The offline fallback must expose the API the procedures/UI use."""
    ol = OfflineLockin()
    assert ol.enabled is False
    for attr in ("x", "y", "x1", "y1", "mag", "mag1", "theta", "theta1"):
        assert getattr(ol, attr) == 0.0
    assert ol.ask("X.") == ""
    # None of these should raise.
    ol.set_reference_mode(0)
    ol.setup_lockin_condition(lockin_voltage=1.0)
    ol.shutdown()


def test_lockin_globals_constructed():
    """meas/dsp must always exist (real instrument OR offline stub)."""
    assert C.meas is not None and C.dsp is not None
    for inst in (C.meas, C.dsp):
        # Whether real or offline, these attributes/methods must be usable.
        assert hasattr(inst, "shutdown")
        assert hasattr(inst, "enabled")


def test_dac_dc_output_applied_after_setup():
    """start_tasks() must reflect dc_output set AFTER the buffer was built."""
    from src.classes.dac_class import DAC

    class FakeTask:
        def stop(self): pass
        def start(self): pass
        def write(self, *a, **k): pass
        def close(self): pass

    class FakeTrigger:
        def write(self, *a, **k): pass
        def stop(self): pass
        def close(self): pass

    d = DAC.__new__(DAC)               # bypass setup_dac (no NI hardware)
    d.enabled = True
    d.reserved = False
    d.status_setup = False
    d.dc_output = [0.0, 0.0]
    d.coils_output = 0.0
    d.mod_chan = None                  # both AC channels constant
    d.modulation_amp = 0.0
    d.f = 1777.0
    d.sampling_rate = 50000
    d.acquisition_time = 0.001
    d.output = FakeTask()
    d.input = FakeTask()
    d._trigger_task = FakeTrigger()
    d._output_values = None

    d.create_signals()
    d._build_output_buffer()           # built with dc_output = [0, 0]

    # Procedure sets constant outputs and coil current AFTER setup.
    d.dc_output = [1.5, 2.5]
    d.coils_output = 3.0
    d.start_tasks()

    assert np.allclose(d._output_values[0, :], 1.5), "AC_Output1 constant not applied"
    assert np.allclose(d._output_values[1, :], 2.5), "AC_Output2 constant not applied"
    assert np.allclose(d._output_values[2, :], 3.0), "coils current not applied"


def test_dac_modulated_channel_waveform_preserved():
    """When a channel is modulated, its sine waveform must survive start_tasks()."""
    from src.classes.dac_class import DAC

    class FakeTask:
        def stop(self): pass
        def start(self): pass
        def write(self, *a, **k): pass
        def close(self): pass

    class FakeTrigger:
        def write(self, *a, **k): pass
        def stop(self): pass
        def close(self): pass

    d = DAC.__new__(DAC)
    d.enabled = True
    d.dc_output = [0.0, 0.0]
    d.coils_output = 0.0
    d.mod_chan = "AC_Output1"          # channel 0 carries the modulation
    d.modulation_amp = 1.0
    d.f = 1777.0
    d.sampling_rate = 50000
    d.acquisition_time = 0.001
    d.output = FakeTask()
    d.input = FakeTask()
    d._trigger_task = FakeTrigger()
    d._output_values = None
    d.create_signals()
    d._build_output_buffer()

    d.dc_output = [9.9, 2.5]            # 9.9 would clobber the waveform if mis-patched
    d.coils_output = 3.0
    d.start_tasks()

    # Row 0 is the modulation waveform — must NOT be flattened to a constant.
    assert not np.allclose(d._output_values[0, :], 9.9), "modulation waveform was overwritten"
    assert np.allclose(d._output_values[1, :], 2.5), "AC_Output2 constant not applied"
    assert np.allclose(d._output_values[2, :], 3.0), "coils current not applied"


def test_b_sweep_fast_mode_field_not_divided_by_n():
    """Fast-mode averaged field must equal the single hall read (not read / n)."""
    import src.procedures.b_sweep_proc as bsp
    _patch_proc_module(bsp, hall_val=10.0)     # hall returns 10 mT

    p = bsp.B_Sweep()
    p.set_sample_name("t")
    p.b_min, p.b_max, p.b_step = -0.02, 0.02, 0.01
    p.sweep_freq = 100000.0                     # tiny T_point => fast mode
    p.num_sweeps = 4

    records = []
    p.emit = lambda topic, rec=None, **k: records.append(rec) if topic == "results" else None
    p.should_stop = lambda: False

    p.startup()
    assert p._hall_live is False, "test needs fast mode (hall not live)"
    p.execute()

    # Final averaged loop emits have Voltage DC (V)=NaN and a real average.
    final = [r for r in records if np.isnan(r["Voltage DC (V)"])]
    assert final, "no averaged records emitted"
    for r in final:
        assert abs(r["Magnetic Field (T)"] - 0.01) < 1e-9, (
            f"field {r['Magnetic Field (T)']} != 0.01 T "
            f"(would be {0.01 / 4} if divided by num_sweeps)"
        )


def test_b_sweep_rejects_too_fast_for_hall():
    """A field sweep faster than the Hall probe can follow must be rejected
    (with a message) before it is ever queued."""
    import src.procedures.b_sweep_proc as bsp
    p = bsp.B_Sweep()
    p.b_min, p.b_max, p.b_step = -0.5, 0.5, 0.01     # hundreds of points/sweep

    p.sweep_freq = 50.0
    msg = p.queue_validation_error()
    assert msg and "too high" in msg, "fast sweep should be rejected"

    p.sweep_freq = 0.5
    assert p.queue_validation_error() is None, "a slow enough sweep must pass"


def test_b_sweep_lockin_uses_lockin_oscillator_not_chopper_or_dac():
    """B-Sweep LockIn must drive the modulation from the lock-in oscillator
    (volt @ lockin_freq), read the already-demodulated first-harmonic outputs
    (meas.x1/...), use NO DAC modulation, and no external chopper.  It must also
    average the signed X (the physical hysteresis loop)."""
    import src.procedures.b_sweep_ac as bsl
    fakes = _patch_proc_module(bsl, hall_val=10.0)

    # No chopper knob any more; the lock-in output/reference frequency instead.
    assert not hasattr(bsl.B_Sweep_Lockin, "chopper_freq")
    assert hasattr(bsl.B_Sweep_Lockin, "lockin_freq")

    modes, dac_cfg, lockin_cfg = [], {}, {}
    fakes["dsp"].set_reference_mode = lambda mode=0: modes.append(mode)
    fakes["dsp"].setup_lockin_condition = lambda **k: lockin_cfg.update(k)
    fakes["dac"].setup_aquisition = lambda **k: dac_cfg.update(k)
    # Distinct values so single-reference reads (x) are told apart from dual (x1).
    fakes["meas"].x, fakes["meas"].y = 1.0, 2.0
    fakes["meas"].mag, fakes["meas"].theta = 3.0, 4.0
    fakes["meas"].x1 = -99.0     # dual-harmonic read must NOT be used

    p = bsl.B_Sweep_Lockin()
    p.set_sample_name("t")
    p.b_min, p.b_max, p.b_step = -0.02, 0.02, 0.01
    p.num_sweeps = 1
    p.sweep_freq = 0.1
    p.volt, p.lockin_freq = 0.7, 3333.0
    p.time_const, p.acq_time = 0.0001, 0.001

    records = []
    p.emit = lambda topic, rec=None, **k: records.append(rec) if topic == "results" else None
    p.should_stop = lambda: False

    p.startup()
    assert 0 in modes and 1 not in modes, \
        f"must use single reference mode (0), not dual-harmonic (1): {modes}"
    # The lock-in oscillator sets the frequency and drives the current (volt).
    assert lockin_cfg.get("lockin_frequency") == 3333.0
    assert lockin_cfg.get("lockin_voltage") == 0.7
    # The DAC generates NO modulation.
    assert dac_cfg.get("modulation_channel") == "None"
    assert dac_cfg.get("modulation_amp") == 0.0

    p.execute()
    live = [r for r in records if not np.isnan(r["Voltage X 1f (V)"])]
    assert live, "no live lock-in points emitted"
    assert live[0]["Voltage X 1f (V)"] == 1.0      # from meas.x, not meas.x1
    assert live[0]["Voltage R 1f (V)"] == 3.0
    # The averaged loop carries the signed X average (the physical hysteresis loop).
    avg = [r for r in records if not np.isnan(r["Voltage X Average (V)"])]
    assert avg and avg[0]["Voltage X Average (V)"] == 1.0


def test_live_readout_push_updates_and_keeps_last_good_field():
    """The Live tab snapshot updates every point, but a NaN/None field (fast
    field sweeps) must not blank the field card."""
    from src.classes.live_readout import LiveReadout
    r = LiveReadout()
    r.push(1.5, 2.5, 10.0)
    assert (r.balanced_v, r.intensity_v, r.field_mT) == (1.5, 2.5, 10.0)
    r.push(3.0, 4.0, float("nan"))
    assert (r.balanced_v, r.intensity_v, r.field_mT) == (3.0, 4.0, 10.0)
    r.push(5.0, 6.0, None)
    assert (r.balanced_v, r.intensity_v, r.field_mT) == (5.0, 6.0, 10.0)


def test_lab_notebook_append_and_server_copy():
    """The lab notebook appends rows with a stable header (extra keys ignored,
    missing ones blank), and copy_file creates the destination folder."""
    import os
    import csv
    import tempfile
    from src.classes.data_archive import append_lab_notebook, copy_file, LAB_NOTEBOOK_COLUMNS

    d = tempfile.mkdtemp()
    nb = os.path.join(d, "lab notebook", "lab_notebook_MINImoke.csv")
    append_lab_notebook(nb, {"Date": "2026-07-01", "Scan type": "B-Sweep",
                             "Operator": "jak", "Unknown": "ignored"})
    append_lab_notebook(nb, {"Date": "2026-07-02", "Scan type": "Time", "Operator": "tobi"})

    with open(nb, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["Scan type"] == "B-Sweep" and rows[1]["Operator"] == "tobi"
    assert set(rows[0].keys()) == set(LAB_NOTEBOOK_COLUMNS)   # header stable
    assert rows[0]["Duration (s)"] == ""                      # missing -> blank

    src = os.path.join(d, "data.csv")
    with open(src, "w") as f:
        f.write("a,b\n1,2\n")
    dest = copy_file(src, os.path.join(d, "server", "Data", "2026-07-01", "longitudinal"))
    assert os.path.exists(dest)
    with open(dest) as f:
        assert f.read() == "a,b\n1,2\n"


def test_lab_notebook_append_aligns_to_existing_header_no_shift():
    """If the column list changes later (e.g. a column is inserted), appended
    rows must still line up with the file's OWN header — never shift.  This
    reproduces the reported 'notebook shifted one column right' after a new
    'Setup' column was added."""
    import os
    import csv
    import tempfile
    from src.classes.data_archive import append_lab_notebook

    d = tempfile.mkdtemp()
    nb = os.path.join(d, "lab_notebook_MINImoke.csv")

    # An older notebook whose header PREDATES the inserted "Setup" column.
    old_header = ["Date", "Operator", "Geometry", "Stage type", "File path"]
    with open(nb, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_header)
        w.writeheader()
        w.writerow({"Date": "2026-07-01", "Operator": "jak", "Geometry": "LMOKE",
                    "Stage type": "Thorlabs", "File path": "a.csv"})

    # A row carrying the current, wider schema (note the extra "Setup" key).
    append_lab_notebook(nb, {"Date": "2026-07-02", "Operator": "tobi", "Setup": "polar",
                             "Geometry": "PMOKE", "Stage type": "Trinamic", "File path": "b.csv"})

    with open(nb, newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == old_header, "header must not change on append"
    # Values stay under their correct columns — no rightward shift.
    assert rows[1]["Geometry"] == "PMOKE"
    assert rows[1]["Stage type"] == "Trinamic"
    assert rows[1]["File path"] == "b.csv"
    # "Setup" isn't a column in this file, so it is dropped, not shifted in.
    assert "Setup" not in rows[1]


def test_archive_experiment_writes_local_notebook_and_server_copies():
    """MainWindow._archive_experiment must copy the data file to the general and
    per-operator server folders and append the local + server lab notebooks."""
    import os
    import glob
    import time
    import types
    import tempfile
    import importlib.util

    spec = importlib.util.spec_from_file_location("moke_main", os.path.join(_REPO, "__main__.py"))
    moke_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(moke_main)      # defines MainWindow; does not launch the app

    d = tempfile.mkdtemp()
    local_data = os.path.join(d, "Desktop", "Data")
    server     = os.path.join(d, "server")
    os.makedirs(local_data, exist_ok=True)
    src_csv = os.path.join(local_data, "sampleA_B-Sweep_x.csv")
    with open(src_csv, "w") as f:
        f.write("Iteration\n0\n")

    class FakeLine:
        def __init__(self, t): self._t = t
        def text(self): return self._t

    class FakeParam:
        def __init__(self, v): self.value = v

    class FakeProc:
        name = "B-Sweep"
        nb_it_md = 42
        def parameter_objects(self): return {"b_min": FakeParam(-0.5), "b_max": FakeParam(0.5)}

    class FakeExp:
        data_filename = src_csv
        procedure = FakeProc()

    fake_self = types.SimpleNamespace(
        operator_line=FakeLine("Jakub"),
        server_line=FakeLine(server),
        sample_name_line=FakeLine("sampleA"),
        directory_input=True,
        directory=local_data,
        _setup_mode="longitudinal",
        _geometry="LMOKE",
        _run_start=time.time(),
    )
    moke_main.MainWindow._archive_experiment(fake_self, FakeExp())

    local_nb = os.path.join(d, "Desktop", "lab notebook", "lab_notebook_MINImoke.csv")
    assert os.path.exists(local_nb)
    # general -> <base>/Data/<date>/<setup>/ ; per-operator -> <base>/<op>/<sample>/<setup>/<date>/
    assert glob.glob(os.path.join(server, "Data", "*", "longitudinal", "*.csv")), "no general server copy"
    assert glob.glob(os.path.join(server, "Jakub", "sampleA", "longitudinal", "*", "*.csv")), "no per-operator copy"
    # Server lab notebook sits directly in the server base now.
    assert os.path.exists(os.path.join(server, "lab_notebook_MINImoke.csv"))

    # Parameters are written into their named columns.
    import csv as _csv
    with open(local_nb, newline="") as f:
        rec = next(_csv.DictReader(f))
    assert rec["Scan type"] == "B-Sweep"
    assert rec["Operator"] == "Jakub"
    assert rec["Field start (A)"] == "-0.5" and rec["Field stop (A)"] == "0.5"
    assert rec["Setup"] == "longitudinal" and rec["Geometry"] == "LMOKE"


def test_default_x_axis_is_valid_and_time_selectable():
    """Every procedure's DEFAULT_X_AXIS must be one of its own columns, and the
    union of all columns (offered by the plot) must include 'Time (s)'."""
    from src.procedures import (B_Sweep, B_Sweep_Lockin, X_Sweep, Y_Sweep,
                                XY_Sweep, TimeMeasurement)
    procs = [B_Sweep, B_Sweep_Lockin, X_Sweep, Y_Sweep, XY_Sweep, TimeMeasurement]

    union = []
    for cls in procs:
        x = getattr(cls, "DEFAULT_X_AXIS", None)
        assert x, f"{cls.name} has no DEFAULT_X_AXIS"
        assert x in cls.DATA_COLUMNS, f"{cls.name}: {x!r} not in its DATA_COLUMNS"
        for c in cls.DATA_COLUMNS:
            if c not in union:
                union.append(c)

    assert "Time (s)" in union, "Time column must be selectable on the plot x-axis"
    assert X_Sweep.DEFAULT_X_AXIS == "X Position (um)"
    assert Y_Sweep.DEFAULT_X_AXIS == "Y Position (um)"
    assert TimeMeasurement.DEFAULT_X_AXIS == "Time (s)"


def test_loop_connect_breaks_between_loops():
    """The plot connect-array must join points within a loop and break between."""
    from src.ui.separated_plot import loop_connect
    assert list(loop_connect([0, 0, 0, 1, 1, 2])) == [1, 1, 0, 1, 0, 0]
    assert list(loop_connect([])) == []
    assert list(loop_connect([5])) == [0]


def test_separated_curve_passes_connect_from_loop_column():
    """SeparatedResultsCurve must feed pyqtgraph a connect array built from the
    Loop column, and fall back to a plain line when there is no Loop column."""
    import pandas as pd
    import pyqtgraph as pg
    from src.ui.separated_plot import SeparatedResultsCurve

    class FakeResults:
        def __init__(self, df):
            self.data = df

    def run(df):
        curve = SeparatedResultsCurve(FakeResults(df), x="X", y="Y", pen=pg.mkPen("r"))
        curve.force_reload = False
        captured = {}
        curve.setData = lambda *a, **k: captured.update(connect=k.get("connect", "MISSING"))
        curve.update_data()
        return captured.get("connect")

    conn = run(pd.DataFrame({"X": [0, 1, 0, 1], "Y": [1, 2, 3, 4], "Loop": [0, 0, 1, 1]}))
    assert conn is not None and not isinstance(conn, str), conn
    assert list(conn) == [1, 0, 1, 0]

    # No Loop column -> plain connected line (setData called without connect=).
    assert run(pd.DataFrame({"X": [0, 1], "Y": [1, 2]})) == "MISSING"


def test_xy_sweep_progress_monotonic_and_bounded():
    """XY progress must rise monotonically and never exceed 100 %."""
    import src.procedures.position_sweep as ps
    import src.procedures.xy_sweep_proc as xyp
    _patch_proc_module(ps)              # shared sweep logic lives in position_sweep

    p = xyp.XY_Sweep()
    p.set_sample_name("t")
    p.x_min, p.x_max, p.x_step = 0.0, 20.0, 10.0     # 3 x points (µm)
    p.y_min, p.y_max, p.y_step = 0.0, 20.0, 10.0     # 3 y points (µm)
    p.b = 0.1
    p.repeat_num = 2
    p.acq_time = 0.001

    progs = []
    def emit(topic, rec=None, **k):
        if topic == "progress":
            progs.append(rec)
    p.emit = emit
    p.should_stop = lambda: False

    p.startup()
    p.execute()
    p.shutdown()

    assert progs, "no progress emitted"
    assert all(0 <= x <= 100 for x in progs), f"progress out of [0,100]: min={min(progs)}, max={max(progs)}"
    assert progs == sorted(progs), "progress is not monotonically increasing"


def test_longitudinal_y_jog_matches_readout_direction():
    """A +mm relative jog must step every axis the same sign (Y was inverted)."""
    s = LongitudinalStage.__new__(LongitudinalStage)   # bypass hardware __init__
    s.enabled = True
    s.mm2steps = 1000.0
    recorded = {}

    class FakeMotor:
        def __init__(self, key): self.key = key
        def is_moving(self): return False
        def move_by(self, steps, scale=True): recorded[self.key] = steps
        def wait_move(self): pass

    s.motor_x, s.motor_y, s.motor_z = FakeMotor("x"), FakeMotor("y"), FakeMotor("z")
    s.move_x(1.0)
    s.move_y(1.0)
    s.move_z(1.0)

    assert recorded["x"] > 0
    assert recorded["z"] > 0
    assert recorded["y"] > 0, "Y jog still inverted relative to X/Z and the readout"
    # And a +mm jog on Y matches X in both sign and magnitude.
    assert recorded["y"] == recorded["x"]


def test_motor_odometer_no_phantom_jumps():
    """The motor-control odometer must step by exactly 1 um per 1 um move.

    Reproduces the reported "jumps by ~10 um after a few 1 um clicks": the old
    per-digit rounding showed 0.006 mm as 0.016 mm.  The reconstructed reading
    must now equal the true value (to the um) and change by exactly 1 um.
    """
    from src.ui import longitudinal_motors_tab_ui as L
    from src.ui import polar_motors_tab_ui as P

    for mod in (L, P):
        def shown_mm(value):
            mag = sum(int(mod._extract_digit(value, step, dec)) * step
                      for step, dec in zip(mod.STEPS, mod.STEP_DECIMALS))
            return -mag if value < 0 else mag

        prev = None
        for i in range(0, 2001):                       # 0 .. 2.000 mm in 1 um steps
            mm = i * 0.001
            shown = shown_mm(mm)
            assert abs(shown - mm) < 5e-4, (
                f"{mod.__name__}: {mm*1000:.0f} um displayed as {shown*1000:.0f} um"
            )
            if prev is not None:
                step_um = round((shown - prev) * 1000)
                assert step_um == 1, (
                    f"{mod.__name__}: display jumped {step_um} um at {mm*1000:.0f} um"
                )
            prev = shown

        # A few negative values round-trip too.
        for mm in (-0.001, -0.006, -1.234):
            assert abs(shown_mm(mm) - mm) < 5e-4, f"{mod.__name__}: negative {mm} mis-displayed"


def test_procedure_shutdown_always_releases_hardware():
    """If a teardown call raises, shutdown must still clear the reserved flags
    so the live tab resumes (the cause of 'live didn't restart after a scan')."""
    import src.procedures.b_sweep_proc as bsp
    fakes = _patch_proc_module(bsp)

    def boom(*a, **k):
        raise RuntimeError("simulated DAQ teardown failure")

    fakes["dac"].set_outputs_and_reset = boom
    fakes["dac"].reserved = True
    fakes["hall_sensor"].reserved = True

    p = bsp.B_Sweep()
    p.set_sample_name("t")
    try:
        p.shutdown()
    except RuntimeError:
        pass   # error may propagate, but the flags must already be cleared

    assert fakes["dac"].reserved is False, "DAC stayed reserved -> live tab frozen"
    assert fakes["hall_sensor"].reserved is False, "Hall stayed reserved -> live tab frozen"


def test_motor_jog_ignores_clicks_while_moving():
    """A jog only starts once the previous move has finished; clicks that arrive
    while the stage is moving are ignored (not queued), so no backlog builds up
    and the stage never keeps jogging after the user stops clicking."""
    from PyQt5.QtCore import QObject, pyqtSignal
    from src.ui import longitudinal_motors_tab_ui as L

    executed = []

    class FakeWorker(QObject):
        finished = pyqtSignal()
        instances = []
        def __init__(self, fn, *args):
            super().__init__()
            self._fn, self._args, self._running = fn, args, False
            FakeWorker.instances.append(self)
        def isRunning(self): return self._running
        def start(self): self._running = True          # do NOT auto-complete
        def complete(self):
            self._fn(*self._args)
            self._running = False
            self.finished.emit()

    tab = L.LongitudinalMotorsTab("test")
    tab._safe_update_positions = lambda: None           # don't touch hardware
    FakeWorker.instances.clear()
    tab._WORKER_CLS = FakeWorker

    def rec(label): executed.append(label)

    tab._dispatch(rec, "a")     # free -> starts immediately
    tab._dispatch(rec, "b")     # busy -> ignored
    tab._dispatch(rec, "c")     # busy -> ignored
    assert len(FakeWorker.instances) == 1, "only the first click should start a move"
    assert executed == []

    FakeWorker.instances[0].complete()   # 'a' finishes
    assert executed == ["a"], "the running move must complete"

    tab._dispatch(rec, "d")     # free again -> starts
    assert len(FakeWorker.instances) == 2, "a click after settling must start a move"
    FakeWorker.instances[1].complete()

    assert executed == ["a", "d"], "clicks during a move are dropped; next is accepted"
    assert not hasattr(tab, "_queue"), "the click queue should be gone"


def test_b_sweep_abort_skips_final_average():
    """Aborting must skip the long post-loop averaging so the abort returns
    promptly (and not divide by zero when no sweep completed)."""
    import src.procedures.b_sweep_proc as bsp
    _patch_proc_module(bsp, hall_val=10.0)

    p = bsp.B_Sweep()
    p.set_sample_name("t")
    p.b_min, p.b_max, p.b_step = -0.02, 0.02, 0.01
    p.sweep_freq = 50.0
    p.num_sweeps = 5
    p.should_stop = lambda: True            # aborted from the very start

    records = []
    p.emit = lambda topic, rec=None, **k: records.append((topic, rec))

    p.startup()
    p.execute()

    # The averaged emit is the only one with Voltage DC (V)=NaN — none must appear.
    averaged = [r for t, r in records
                if t == "results" and isinstance(r.get("Voltage DC (V)"), float)
                and np.isnan(r["Voltage DC (V)"])]
    assert averaged == [], "final averaged loop was emitted despite abort"


def test_x_sweep_shutdown_skips_moveback_on_abort():
    """shutdown() must skip the long move-back to start when aborted, but still
    do it on a normal finish.  The non-abortable move-back is the main reason an
    abort could appear to hang the whole app."""
    import src.procedures.position_sweep as ps
    import src.procedures.x_sweep_proc as xsp
    fakes = _patch_proc_module(ps)     # startup/execute/shutdown live in position_sweep

    moves = []
    fakes["stage"].move_x_to = lambda v: moves.append(("x", v))
    fakes["stage"].move_y_to = lambda v: moves.append(("y", v))

    p = xsp.X_Sweep()
    p.set_sample_name("t")
    p.x_min, p.x_max, p.y = -20.0, 20.0, 0.0   # µm
    p._home = (p.x_min, p.y)                 # normally set by startup()

    p.should_stop = lambda: True            # aborted -> no move-back
    p.shutdown()
    assert moves == [], f"stage moved back to start despite abort: {moves}"

    moves.clear()
    p.should_stop = lambda: False           # normal finish -> move back
    p.shutdown()
    # Home is in µm; the stage is commanded in mm (µm / 1000).
    assert ("x", p.x_min / 1000.0) in moves and ("y", p.y / 1000.0) in moves, \
        f"normal finish should move back to start: {moves}"


def test_single_lockin_instance():
    """meas and dsp must be the same object — one VISA session to one box."""
    assert C.meas is C.dsp, "meas and dsp are separate driver sessions to one instrument"


def test_x_sweep_sets_lockin_reference_mode_in_startup():
    """X/Y/XY read the single-reference demod outputs, so startup must select
    single reference mode (0) — NOT the dual-harmonic mode (1), whose unused 2f
    demodulator overloads and spikes.  The modulation comes from the lock-in
    oscillator (volt @ lockin_freq), not the DAC, so the DAC must be configured
    with NO modulation."""
    import src.procedures.position_sweep as ps
    import src.procedures.x_sweep_proc as xsp
    fakes = _patch_proc_module(ps)     # startup/execute/shutdown live in position_sweep

    calls, dac_cfg, lockin_cfg = [], {}, {}
    fakes["dsp"].set_reference_mode = lambda mode=0: calls.append(mode)
    fakes["dsp"].setup_lockin_condition = lambda **k: lockin_cfg.update(k)
    fakes["dac"].setup_aquisition = lambda **k: dac_cfg.update(k)

    # X/Y/XY no longer expose a DAC-modulation channel.
    assert not hasattr(xsp.X_Sweep, "demod")
    assert not hasattr(xsp.X_Sweep, "mod_amp")

    p = xsp.X_Sweep()
    p.set_sample_name("t")
    p.acq_time = 0.001
    p.b = 0.0
    p.volt, p.lockin_freq = 0.8, 2500.0
    p.startup()

    assert 0 in calls and 1 not in calls, \
        f"must use single reference mode (0), not dual-harmonic (1): {calls}"
    # Oscillator drives the current: amplitude = volt, frequency = lockin_freq.
    assert lockin_cfg.get("lockin_voltage") == 0.8
    assert lockin_cfg.get("lockin_frequency") == 2500.0
    # No DAC modulation.
    assert dac_cfg.get("modulation_channel") == "None"
    assert dac_cfg.get("modulation_amp") == 0.0


def test_time_measurement_records_time_series():
    """The time-domain procedure records a monotonic Time column at a fixed
    field, reusing the shared read_signals acquisition."""
    import src.procedures.position_sweep as ps   # read_signals lives here
    import src.procedures.time_proc as tp
    _patch_proc_module(ps)
    _patch_proc_module(tp)

    p = tp.TimeMeasurement()
    p.set_sample_name("t")
    p.b, p.acq_time = 0.0, 0.001
    p.duration, p.interval = 0.005, 0.001         # ~5 points

    records = []
    p.emit = lambda topic, rec=None, **k: records.append(rec) if topic == "results" else None
    p.should_stop = lambda: False

    p.startup()
    p.execute()
    p.shutdown()

    assert records, "no points recorded"
    assert all("Time (s)" in r and "Voltage DC (V)" in r for r in records)
    times = [r["Time (s)"] for r in records]
    assert times == sorted(times), "time must be non-decreasing"


def test_sweep_visit_order_preserved():
    """The PositionSweep refactor must reproduce each procedure's exact visit
    order: field->position for X, and x->field->y for the XY grid."""
    import src.procedures.position_sweep as ps
    import src.procedures.x_sweep_proc as xsp
    import src.procedures.xy_sweep_proc as xyp

    def capture(p):
        fakes = _patch_proc_module(ps)
        state = {"x": 0.0, "y": 0.0}
        fakes["stage"].move_x_to = lambda v: state.__setitem__("x", float(v))
        fakes["stage"].move_y_to = lambda v: state.__setitem__("y", float(v))
        fakes["stage"].get_x_pos = lambda: state["x"]
        fakes["stage"].get_y_pos = lambda: state["y"]
        visits = []

        def emit(topic, rec=None, **k):
            if topic == "results":
                visits.append((round(rec["X Position (um)"], 6),   # positions are µm now
                               round(rec["Y Position (um)"], 6),
                               round(rec["Magnetic Field (A)"], 6)))
        p.emit = emit
        p.should_stop = lambda: False
        p.startup()
        p.execute()
        return visits

    px = xsp.X_Sweep()
    px.set_sample_name("t")
    px.x_min, px.x_max, px.x_step = 0.0, 10.0, 10.0    # x = [0, 10] µm
    px.y, px.b, px.repeat_num = 0.0, 0.1, 1
    px.acq_time = 0.001
    assert capture(px) == [
        (0.0, 0.0,  0.1), (10.0, 0.0,  0.1),           # field +0.1, x inner
        (0.0, 0.0, -0.1), (10.0, 0.0, -0.1),           # field -0.1, x inner
    ]

    pxy = xyp.XY_Sweep()
    pxy.set_sample_name("t")
    pxy.x_min, pxy.x_max, pxy.x_step = 0.0, 10.0, 10.0  # x = [0, 10] µm
    pxy.y_min, pxy.y_max, pxy.y_step = 0.0, 10.0, 10.0  # y = [0, 10] µm
    pxy.b, pxy.repeat_num = 0.1, 1
    pxy.acq_time = 0.001
    assert capture(pxy) == [
        (0.0,  0.0,  0.1), (0.0,  10.0,  0.1),          # x=0, +0.1, y inner
        (0.0,  0.0, -0.1), (0.0,  10.0, -0.1),          # x=0, -0.1, y inner
        (10.0, 0.0,  0.1), (10.0, 10.0,  0.1),          # x=10, +0.1, y inner
        (10.0, 0.0, -0.1), (10.0, 10.0, -0.1),          # x=10, -0.1, y inner
    ]


def test_xy_sweep_exposes_grid_bounds_for_2d_map():
    """XY-Sweep must expose the grid extent the 2D-map reads
    ('<col>_start/_end/_step', in micrometres), stepped to match the scan; 1D and
    field sweeps must NOT look like a grid (so the map skips them)."""
    from src.procedures import XY_Sweep, X_Sweep, Y_Sweep, B_Sweep, TimeMeasurement

    p = XY_Sweep()
    p.x_min, p.x_max, p.x_step = 0.0, 50.0, 20.0      # 3 points, spacing 25 µm
    p.y_min, p.y_max, p.y_step = 20.0, 0.0, 10.0      # reversed range

    # Bounds are micrometres (same unit as the params), normalised start <= end.
    assert getattr(p, "X Position (um)_start") == 0.0
    assert getattr(p, "X Position (um)_end") == 50.0
    # Step is the ACTUAL linspace spacing (span/(N-1)), not the requested x_step,
    # so every image cell lines up with a scan point.
    assert getattr(p, "X Position (um)_step") == 25.0
    assert getattr(p, "Y Position (um)_start") == 0.0                # min(20, 0)
    assert getattr(p, "Y Position (um)_end") == 20.0

    for cls in (X_Sweep, Y_Sweep, B_Sweep, TimeMeasurement):
        assert not hasattr(cls(), "X Position (um)_start"), cls.__name__


def test_2d_map_builds_image_sized_to_the_grid():
    """The 2D-map ImageWidget must build a pymeasure ResultsImage whose grid has
    exactly one cell per XY scan point (no empty margin row/column)."""
    import pandas as pd
    from pymeasure.display.widgets import ImageWidget
    from pymeasure.display.curves import ResultsImage
    from src.procedures import XY_Sweep

    p = XY_Sweep()
    p.x_min, p.x_max, p.x_step = 0.0, 50.0, 20.0
    p.y_min, p.y_max, p.y_step = 0.0, 40.0, 10.0
    p._configure_scan()
    nx, ny = len(p.x_values), len(p.y_values)

    class FakeResults:
        procedure = p
        data = pd.DataFrame(columns=XY_Sweep.DATA_COLUMNS)

    iw = ImageWidget("2D Map", XY_Sweep.DATA_COLUMNS,
                     "X Position (um)", "Y Position (um)", z_axis="Voltage DC (V)")
    img = iw.new_curve(FakeResults())
    assert isinstance(img, ResultsImage)
    assert (img.xsize, img.ysize) == (nx, ny), (img.xsize, img.ysize, nx, ny)


def test_lockin_set_reference_mode_recovers_from_wedged_link():
    """A timed-out REFMODE write must trigger a VISA clear + one retry, so a
    single wedged-link glitch (e.g. after an overload) doesn't abort the run."""
    from src.classes.ametek7270_class import Ametek7270

    dsp = Ametek7270.__new__(Ametek7270)     # bypass hardware __init__
    events = []

    class FakeConn:
        def clear(self): events.append("clear")

    class FakeAdapter:
        connection = FakeConn()

    dsp.adapter = FakeAdapter()
    calls = {"n": 0}

    def fake_ask(cmd, query_delay=0):
        calls["n"] += 1
        events.append(cmd)
        if calls["n"] == 1:
            raise RuntimeError("VI_ERROR_TMO")   # first write is wedged
        return ""
    dsp.ask = fake_ask

    dsp.set_reference_mode(0)                 # must clear + retry, not raise
    assert events == ["REFMODE 0", "clear", "REFMODE 0"], events


# ---------------------------------------------------------------------------
# Minimal runner (so the suite works without pytest)
# ---------------------------------------------------------------------------

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = []
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:
            import traceback
            print(f"  FAIL  {t.__name__}: {exc}")
            traceback.print_exc()
            failures.append(t.__name__)
    print()
    if failures:
        print(f"RESULT: {len(failures)}/{len(tests)} FAILED: {failures}")
        return 1
    print(f"RESULT: all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
