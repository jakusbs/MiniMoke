"""
src/classes/active_stage.py

A thin proxy that forwards every stage call to the currently active stage
(longitudinal or polar).  All procedure files import this module instead of
importing longitudinal_stage or polar_stage directly.

Usage
-----
    from src.classes import active_stage          # in procedures
    from src.classes import set_active_stage      # in the UI toggle handler

    # Switch to polar:
    set_active_stage("polar")

    # Move as usual — hits whichever stage is active:
    active_stage.move_x_to(0.5)

Thread safety
-------------
A single ``threading.Lock`` (_hw_lock) serialises **all** hardware access —
both from procedure worker threads (pymeasure) and from the UI poll timer.
The motor-tab widgets import ``hw_lock`` and use it instead of a private
QMutex, so there is exactly one lock for each physical stage connection.
"""

import threading

from src.classes import longitudinal_stage, polar_stage

# The currently active stage instance.  Starts as longitudinal to match the
# default toggle state in UIWindowBase._setup_mode.
_active = longitudinal_stage

# ---------------------------------------------------------------------------
# Shared hardware lock
# ---------------------------------------------------------------------------
# All callers — procedure threads AND the UI tab's poll timer — must acquire
# this lock before touching the stage.  Using threading.Lock (not QMutex)
# means procedure threads (plain Python threads) can also hold it safely.
#
# The UI tab's _safe_update_positions() should use hw_lock.acquire(blocking=False)
# so the main thread is never blocked by a running move.
# ---------------------------------------------------------------------------
hw_lock = threading.Lock()


def set_active_stage(mode: str) -> None:
    """
    Point the proxy at the chosen stage.

    Args:
        mode: "longitudinal" or "polar"
    """
    global _active
    if mode == "polar":
        _active = polar_stage
    else:
        _active = longitudinal_stage


# ---------------------------------------------------------------------------
# Proxy helpers — every attribute / method access is forwarded to _active.
# Every call acquires hw_lock so procedure threads and the UI poll timer
# can never talk to the serial port simultaneously.
# ---------------------------------------------------------------------------

@property
def enabled() -> bool:
    return _active.enabled


def move_x(mm: float) -> None:
    with hw_lock:
        _active.move_x(mm)


def move_y(mm: float) -> None:
    with hw_lock:
        _active.move_y(mm)


def move_z(mm: float) -> None:
    with hw_lock:
        _active.move_z(mm)


def move_x_to(position: float) -> None:
    with hw_lock:
        _active.move_x_to(position)


def move_y_to(position: float) -> None:
    with hw_lock:
        _active.move_y_to(position)


def move_z_to(position: float) -> None:
    with hw_lock:
        _active.move_z_to(position)


def get_x_pos() -> float:
    with hw_lock:
        return _active.get_x_pos()


def get_y_pos() -> float:
    with hw_lock:
        return _active.get_y_pos()


def get_z_pos() -> float:
    with hw_lock:
        return _active.get_z_pos()


def get_x_pos_str() -> str:
    with hw_lock:
        return _active.get_x_pos_str()


def get_y_pos_str() -> str:
    with hw_lock:
        return _active.get_y_pos_str()


def get_z_pos_str() -> str:
    with hw_lock:
        return _active.get_z_pos_str()


def home_axis(axis=None) -> None:
    with hw_lock:
        _active.home_axis(axis)


def wait_stable() -> None:
    with hw_lock:
        _active.wait_stable()