"""
Description:
    Defines a PolarStage class for controlling the polar motor setup.
    Uses a Trinamic TMCM-3212 3-axis stepper controller connected via USB,
    driven by the pytrinamic library (pip install pytrinamic).

    The TMCM-3212 exposes 3 axes (0=X, 1=Y, 2=Z) on a single USB connection.
    Positions are tracked in microsteps internally; the mm2steps conversion
    factor in polar_stage_config.ini translates to/from millimetres.

    Hardware axes:
        AXIS_X (2) = PP110-30 (30 mm travel, 28mm stepper, 0.7 A, 0.5 mm/rev lead)
        AXIS_Y (1) = GD401   (60 mm lift,   SST42D2121,  1.2 A, 1.0 mm/rev lead)
        AXIS_Z (0) = PP110-20 (20 mm travel, 28mm stepper, 0.7 A, 0.5 mm/rev lead)

    Noise fix:
        StealthChop (AP 167) and associated tuning parameters (APs 140, 162, 165, 
        166, 191) are applied to all axes to eliminate high-pitched chopper noise.
"""

import warnings
import time

try:
    from pytrinamic.connections import ConnectionManager
    _PYTRINAMIC_AVAILABLE = True
except ImportError:
    warnings.warn(
        "pytrinamic is not installed — polar stage (TMCM-3212) will be disabled.\n"
        "Install it with:  pip install pytrinamic",
        UserWarning,
        stacklevel=2,
    )
    _PYTRINAMIC_AVAILABLE = False

from src.classes import polar_stage_config

# ---------------------------------------------------------------------------
# Axis indices on the TMCM-3212
# ---------------------------------------------------------------------------
_AXIS_X = 2   # PP110-30 (30 mm travel linear stage)
_AXIS_Y = 1   # GD401    (60 mm motorised lab jack / lift)
_AXIS_Z = 0   # PP110-20 (20 mm travel linear stage)

# ---------------------------------------------------------------------------
# Per-axis rated currents
# ---------------------------------------------------------------------------
_CURRENT_X = 60    # PP110-30, 0.7 A RMS
_CURRENT_Y = 102   # GD401,    1.2 A RMS
_CURRENT_Z = 60    # PP110-20, 0.7 A RMS

# ---------------------------------------------------------------------------
# WINNING SILENT PARAMETERS (Acoustic Tournament Winners)
# ---------------------------------------------------------------------------
_STANDBY_CURRENT  = 25   # AP 7: Optimized to stop idle hiss
_PWM_AMPLITUDE    = 128  # AP 165: StealthChop voltage amplitude
_PWM_GRADIENT     = 4    # AP 166: Velocity adaptation gradient
_BLANK_TIME       = 3    # AP 162: Filter for high-pitched ringing
_PWM_FREQUENCY    = 1    # AP 191: Efficient standard frequency
_MICROSTEPS       = 8    # AP 140: 256 Microsteps (2^8)

# ---------------------------------------------------------------------------
# Motion parameters
# ---------------------------------------------------------------------------
_MAX_VELOCITY     = 51200   # steps/s  (~1 mm/s)
_MAX_ACCEL        = 25600   # steps/s² (~0.5 mm/s²)

class PolarStage:
    enabled = False

    def __init__(self) -> None:
        self._interface = None
        self._module    = None

        if not _PYTRINAMIC_AVAILABLE:
            print("WARNING: PolarStage disabled — pytrinamic package not found.")
            self._finish_init()
            return

        connection_cfg = polar_stage_config.get_section("Connection")
        port = connection_cfg.get("port", "auto").strip()

        try:
            if port.lower() == "auto":
                self._interface = ConnectionManager("--interface usb_tmcl").connect()
            else:
                self._interface = ConnectionManager(
                    f"--interface usb_tmcl --port {port}"
                ).connect()

            from pytrinamic.modules import TMCLModule
            self._module = TMCLModule(self._interface, module_id=1)
            self.enabled = True
            print("PolarStage (TMCM-3212): connected successfully.")

            self._apply_motor_config()

        except Exception as err:
            print(
                f"WARNING: PolarStage (TMCM-3212) could not connect — "
                f"running without polar stage.\n  Reason: {err}"
            )
            self._interface = None
            self._module    = None
            self.enabled    = False

        self._finish_init()

    def _finish_init(self) -> None:
        constants = polar_stage_config.get_section("Constants")
        # Load independent scaling factors for each axis
        self.mm2steps_x = float(constants.get("mm2steps_x", "1"))
        self.mm2steps_y = float(constants.get("mm2steps_y", "1"))
        self.mm2steps_z = float(constants.get("mm2steps_z", "1"))
        self.load_offsets()

    # ------------------------------------------------------------------
    # TMCL axis-parameter (AP) indices
    # ------------------------------------------------------------------
    _AP_ACTUAL_POSITION      = 1
    _AP_MAX_VELOCITY         = 4
    _AP_MAX_ACCELERATION     = 5
    _AP_MAX_CURRENT          = 6
    _AP_STANDBY_CURRENT      = 7
    _AP_POSITION_REACHED     = 8
    _AP_MICROSTEP_RES        = 140
    _AP_BLANK_TIME           = 162
    _AP_PWM_AMPL             = 165
    _AP_PWM_GRAD             = 166
    _AP_STEALTH_CHOP         = 167 
    _AP_PWM_FREQ             = 191

    # TMCL opcodes
    _CMD_SAP = 5   # Set Axis Parameter
    _CMD_GAP = 6   # Get Axis Parameter
    _CMD_MVP = 4   # Move to Position
    _MVP_ABS = 0
    _MVP_REL = 1

    # ------------------------------------------------------------------
    # Low-level TMCL helpers
    # ------------------------------------------------------------------

    def _set_ap(self, axis: int, ap: int, value: int) -> None:
        self._interface.send(self._CMD_SAP, ap, axis, value, self._module.module_id)

    def _get_ap(self, axis: int, ap: int) -> int:
        return self._interface.send(self._CMD_GAP, ap, axis, 0, self._module.module_id).value

    def _mvp_relative(self, axis: int, steps: int) -> None:
        self._interface.send(self._CMD_MVP, self._MVP_REL, axis, steps, self._module.module_id)

    def _mvp_absolute(self, axis: int, position: int) -> None:
        self._interface.send(self._CMD_MVP, self._MVP_ABS, axis, position, self._module.module_id)

    # ------------------------------------------------------------------
    # Motor configuration — called once at connection time
    # ------------------------------------------------------------------

    def _apply_motor_config(self) -> None:
        """
        Configure per-axis current limits, motion parameters, and chopper mode.
        Applies the silent winning tournament variables.
        """
        per_axis_config = {
            _AXIS_X: _CURRENT_X,
            _AXIS_Y: _CURRENT_Y,
            _AXIS_Z: _CURRENT_Z,
        }

        for axis, run_current in per_axis_config.items():
            # Current limits & Motion profile
            self._set_ap(axis, self._AP_MAX_CURRENT,      run_current)
            self._set_ap(axis, self._AP_STANDBY_CURRENT,  _STANDBY_CURRENT)
            self._set_ap(axis, self._AP_MAX_VELOCITY,     _MAX_VELOCITY)
            self._set_ap(axis, self._AP_MAX_ACCELERATION, _MAX_ACCEL)

            # Silent Mode Parameters (Winners)
            self._set_ap(axis, self._AP_MICROSTEP_RES,    _MICROSTEPS)
            self._set_ap(axis, self._AP_STEALTH_CHOP,     1)
            self._set_ap(axis, self._AP_BLANK_TIME,       _BLANK_TIME)
            self._set_ap(axis, self._AP_PWM_AMPL,         _PWM_AMPLITUDE)
            self._set_ap(axis, self._AP_PWM_GRAD,         _PWM_GRADIENT)
            self._set_ap(axis, self._AP_PWM_FREQ,         _PWM_FREQUENCY)

        print(
            "Motor config applied:\n"
            f"  Silent profile active (Standby: {_STANDBY_CURRENT}, BlankTime: {_BLANK_TIME})\n"
            f"  Currents: X={_CURRENT_X}, Y={_CURRENT_Y}, Z={_CURRENT_Z}\n"
            f"  Resolution: {2**_MICROSTEPS} microsteps"
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _to_signed32(value: int) -> int:
        value = int(value) & 0xFFFFFFFF
        if value >= 0x80000000:
            value -= 0x100000000
        return value

    def _get_raw_pos(self, axis_index: int) -> int:
        return self._to_signed32(self._get_ap(axis_index, self._AP_ACTUAL_POSITION))

    def _is_moving(self, axis_index: int) -> bool:
        """
        Check if the axis is moving.
        Improved to use the hardware PositionReached flag (AP 8).
        1 = Target Reached, 0 = Moving.
        """
        return self._get_ap(axis_index, self._AP_POSITION_REACHED) == 0

    def _wait_move(self, axis_index: int) -> None:
        while self._is_moving(axis_index):
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Offset management
    # ------------------------------------------------------------------

    def load_offsets(self) -> None:
        offsets = polar_stage_config.get_section("Offsets")
        self.offset_x = self._to_signed32(int(float(offsets.get("offset_x", "0"))))
        self.offset_y = self._to_signed32(int(float(offsets.get("offset_y", "0"))))
        self.offset_z = self._to_signed32(int(float(offsets.get("offset_z", "0"))))

    def save_config(self) -> None:
        polar_stage_config.save_str_dict("Offsets", {
            "offset_x": str(self.offset_x),
            "offset_y": str(self.offset_y),
            "offset_z": str(self.offset_z),
        })

    def home_axis(self, axis=None) -> None:
        if not self.enabled:
            return
        if axis is None or axis == "x":
            self.offset_x = self._get_raw_pos(_AXIS_X)
        if axis is None or axis == "y":
            self.offset_y = self._get_raw_pos(_AXIS_Y)
        if axis is None or axis == "z":
            self.offset_z = self._get_raw_pos(_AXIS_Z)
        self.save_config()

    def wait_stable(self) -> None:
        if self.enabled:
            self._wait_move(_AXIS_X)
            self._wait_move(_AXIS_Y)
            self._wait_move(_AXIS_Z)

    # ------------------------------------------------------------------
    # Relative moves
    # ------------------------------------------------------------------

    def move_x(self, mm: float) -> None:
        if self.enabled:
            steps = int(round(mm * self.mm2steps_x))
            self._mvp_relative(_AXIS_X, steps)
            self._wait_move(_AXIS_X)

    def move_y(self, mm: float) -> None:
        if self.enabled:
            steps = int(round(-mm * self.mm2steps_y))
            self._mvp_relative(_AXIS_Y, steps)
            self._wait_move(_AXIS_Y)

    def move_z(self, mm: float) -> None:
        if self.enabled:
            steps = int(round(-mm * self.mm2steps_z))
            self._mvp_relative(_AXIS_Z, steps)
            self._wait_move(_AXIS_Z)

    # ------------------------------------------------------------------
    # Absolute moves
    # ------------------------------------------------------------------

    def move_x_to(self, position: float) -> None:
        if self.enabled:
            target = int(round(position * self.mm2steps_x + self.offset_x))
            self._mvp_absolute(_AXIS_X, target)
            self._wait_move(_AXIS_X)

    def move_y_to(self, position: float) -> None:
        if self.enabled:
            target = int(round(-position * self.mm2steps_y + self.offset_y))
            self._mvp_absolute(_AXIS_Y, target)
            self._wait_move(_AXIS_Y)

    def move_z_to(self, position: float) -> None:
        if self.enabled:
            target = int(round(-position * self.mm2steps_z + self.offset_z))
            self._mvp_absolute(_AXIS_Z, target)
            self._wait_move(_AXIS_Z)

    # ------------------------------------------------------------------
    # Position readout
    # ------------------------------------------------------------------

    def get_x_pos(self) -> float:
        if not self.enabled:
            return float("nan")
        return (self._get_raw_pos(_AXIS_X) - self.offset_x) / self.mm2steps_x

    def get_y_pos(self) -> float:
        if not self.enabled:
            return float("nan")
        return -(self._get_raw_pos(_AXIS_Y) - self.offset_y) / self.mm2steps_y

    def get_z_pos(self) -> float:
        if not self.enabled:
            return float("nan")
        return -(self._get_raw_pos(_AXIS_Z) - self.offset_z) / self.mm2steps_z

    def get_x_pos_str(self) -> str:
        if not self.enabled:
            return "?"
        return f"{self.get_x_pos():.3f}mm"

    def get_y_pos_str(self) -> str:
        if not self.enabled:
            return "?"
        return f"{self.get_y_pos():.3f}mm"

    def get_z_pos_str(self) -> str:
        if not self.enabled:
            return "?"
        return f"{self.get_z_pos():.3f}mm"

    def close(self) -> None:
        """Release the USB connection."""
        if self._interface is not None:
            try:
                self._interface.close()
            except Exception:
                pass