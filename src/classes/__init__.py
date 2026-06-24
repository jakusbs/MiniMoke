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
from .ametek7270_class import Ametek7270, OfflineLockin

dac         = DAC()
hall_sensor = HallSensor()
longitudinal_stage = LongitudinalStage()
stage = longitudinal_stage  # backward-compat alias (used by B-Sweep internally if needed)
polar_stage = PolarStage()
log         = logging.getLogger(__name__)


def _make_lockin():
    """Construct an Ametek 7270 lock-in, falling back to an offline stub.

    Unlike the other device classes, ``Ametek7270.__init__`` raises if the
    instrument (or a VISA backend) is unavailable.  Catching it here keeps the
    application launchable in exactly the same way a missing DAC / Hall sensor /
    stage already is, instead of crashing at import time.
    """
    try:
        return Ametek7270()
    except Exception as err:
        print(f"Lock-in (Ametek 7270) not found: {err}")
        return OfflineLockin()


meas = _make_lockin()
dsp  = _make_lockin()

log.setLevel(logging.INFO)

# ── Active stage proxy ────────────────────────────────────────────────────────
# Procedures import `active_stage` (and optionally `set_active_stage`) instead
# of importing longitudinal_stage or polar_stage directly.  The UI toggle calls
# set_active_stage() to redirect all future stage commands.

from . import active_stage                      # noqa: E402
from .active_stage import set_active_stage      # noqa: E402