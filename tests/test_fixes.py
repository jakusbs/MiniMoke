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


def test_xy_sweep_progress_monotonic_and_bounded():
    """XY progress must rise monotonically and never exceed 100 %."""
    import src.procedures.xy_sweep_proc as xyp
    _patch_proc_module(xyp)

    p = xyp.XY_Sweep()
    p.set_sample_name("t")
    p.x_min, p.x_max, p.x_step = 0.0, 0.02, 0.01     # 3 x points
    p.y_min, p.y_max, p.y_step = 0.0, 0.02, 0.01     # 3 y points
    p.b = 0.1
    p.repeat_num = 2
    p.demod = "None"
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


def test_motor_click_queue_applies_every_click():
    """Rapid jog clicks must all execute in order (none dropped while moving)."""
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

    tab._dispatch(rec, "a")     # first starts immediately
    tab._dispatch(rec, "b")     # a still running -> queued
    tab._dispatch(rec, "c")     # queued
    assert len(FakeWorker.instances) == 1 and executed == []

    FakeWorker.instances[0].complete()   # a done -> b starts
    assert executed == ["a"] and len(FakeWorker.instances) == 2
    FakeWorker.instances[1].complete()   # b done -> c starts
    assert executed == ["a", "b"] and len(FakeWorker.instances) == 3
    FakeWorker.instances[2].complete()   # c done

    assert executed == ["a", "b", "c"], "a rapid click was dropped"
    assert tab._queue == [], "queue not drained"


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
