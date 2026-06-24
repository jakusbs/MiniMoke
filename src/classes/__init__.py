"""
Description:
    Imports all classes and initialises global instances used across the app.
"""

from .config_handler import proc_config, dac_config, longitudinal_stage_config, polar_stage_config
from .dac_class import DAC
from .hallsensor_class import HallSensor
from .statusbar_class import StatusBarHandler, logging
from .longitudinal_stage_class import LongitudinalStage
from .polar_stage_class import PolarStage
from .ametek7270_class import Ametek7270

dac         = DAC()
hall_sensor = HallSensor()
longitudinal_stage = LongitudinalStage()
stage = longitudinal_stage  # backward-compat alias (used by B-Sweep internally if needed)
polar_stage = PolarStage()
log         = logging.getLogger(__name__)

meas = Ametek7270()
dsp  = Ametek7270()

log.setLevel(logging.INFO)

# ── Active stage proxy ────────────────────────────────────────────────────────
# Procedures import `active_stage` (and optionally `set_active_stage`) instead
# of importing longitudinal_stage or polar_stage directly.  The UI toggle calls
# set_active_stage() to redirect all future stage commands.

from . import active_stage                      # noqa: E402
from .active_stage import set_active_stage      # noqa: E402