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
from .live_readout import live_readout

dac         = DAC()
hall_sensor = HallSensor()
longitudinal_stage = LongitudinalStage()
stage = longitudinal_stage  # backward-compat alias (used by B-Sweep internally if needed)
polar_stage = PolarStage()
log         = logging.getLogger(__name__)


def _lockin_resource_from_config(path='configs/instruments_config.ini'):
    """Optional override of the lock-in VISA resource string.

    Lets the rig switch the 7270 to another interface (e.g. its Ethernet port,
    ``TCPIP0::<ip>::50000::SOCKET``) by editing a config file instead of the
    code.  Returns None when the file/section/key is absent, in which case the
    driver's built-in USB default is used.
    """
    import configparser
    try:
        cp = configparser.ConfigParser()
        if not cp.read(path):
            return None
        return cp.get('LockIn', 'resource', fallback=None) or None
    except Exception:
        return None


def _make_lockin():
    """Construct an Ametek 7270 lock-in, falling back to an offline stub.

    Unlike the other device classes, ``Ametek7270.__init__`` raises if the
    instrument (or a VISA backend) is unavailable.  Catching it here keeps the
    application launchable in exactly the same way a missing DAC / Hall sensor /
    stage already is, instead of crashing at import time.
    """
    resource = _lockin_resource_from_config()
    try:
        return Ametek7270(resource) if resource else Ametek7270()
    except Exception as err:
        # This runs at import time, before the GUI log exists, so also warn via
        # logging (console / any attached handler).  The procedures repeat this
        # warning in the run log at every startup while the stub is active.
        message = (f"Lock-in (Ametek 7270) not found at "
                   f"'{resource or 'USB default'}': {err} — starting with the OFFLINE "
                   f"stub; all lock-in channels will read zero.")
        print(message)
        log.warning(message)
        return OfflineLockin()


meas = _make_lockin()
# `meas` and `dsp` are the SAME physical Ametek 7270.  Opening two driver
# instances (two VISA sessions) to one instrument risks intermittent conflicts,
# so `dsp` is just an alias used by the configuration calls.
dsp  = meas


def try_revive_lockin():
    """If the lock-in is the offline stub, try to establish a real connection.

    Called at every AC run start, so a lock-in that was unreachable when the
    app launched (still booting, or its single Ethernet slot still held by a
    crashed session) is picked up without restarting the application.

    For a socket resource on the 7270's primary command port (50000) a refused
    connection is retried on its second command port (50001) — the instrument
    listens on both, so the spare usually accepts even while a stale connection
    still occupies the primary.

    On success the new driver replaces the stub everywhere it was imported
    (``src.classes`` and the procedure modules) and is returned; on failure
    returns None and the stub stays in place.
    """
    global meas, dsp
    if getattr(meas, "enabled", False):
        return meas          # already live — nothing to do

    resource = _lockin_resource_from_config()
    candidates = [resource]
    if resource and "::SOCKET" in resource.upper() and "::50000::" in resource:
        candidates.append(resource.replace("::50000::", "::50001::"))

    for res in candidates:
        try:
            new = Ametek7270(res) if res else Ametek7270()
        except Exception as err:
            log.warning(f"Lock-in reconnect attempt at '{res or 'USB default'}' failed: {err}")
            continue
        meas = dsp = new
        # The procedures imported the object directly, so rebind it there too.
        # (Imported here, not at module top, to avoid a circular import.)
        import src.procedures.position_sweep as _ps
        import src.procedures.b_sweep_ac as _ba
        import src.procedures.b_sweep_proc as _bp
        import src.procedures.time_proc as _tp
        for _mod in (_ps, _ba, _bp, _tp):
            _mod.meas = new
            _mod.dsp = new
        log.info(f"Lock-in connected at '{res or 'USB default'}'.")
        return new
    return None

log.setLevel(logging.INFO)

# ── Active stage proxy ────────────────────────────────────────────────────────
# Procedures import `active_stage` (and optionally `set_active_stage`) instead
# of importing longitudinal_stage or polar_stage directly.  The UI toggle calls
# set_active_stage() to redirect all future stage commands.

from . import active_stage                      # noqa: E402
from .active_stage import set_active_stage      # noqa: E402