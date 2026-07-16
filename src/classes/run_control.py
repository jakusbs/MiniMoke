"""
A tiny shared pause switch for the running measurement.

The Pause button (GUI thread) and the hardware-error handler (worker thread)
both set ``pause_requested``; the procedure loops check it between points and
hold — position, field and all outputs stay where they are — until it clears.
Plain attribute assignment is atomic under the GIL, so no lock is needed.

``auto_paused`` records that the pause came from a hardware error (a
disconnected USB/Ethernet device) rather than the button, so the UI can show
"Continue" and the log can say what to fix.
"""


class RunControl:
    def __init__(self):
        self.pause_requested = False
        self.auto_paused     = False   # True when a hardware error caused the pause

    def request_pause(self, auto=False):
        self.pause_requested = True
        self.auto_paused     = auto

    def clear(self):
        self.pause_requested = False
        self.auto_paused     = False


# Global instance shared by the UI (button) and the procedures (loops).
run_control = RunControl()


def hold_while_paused(should_stop, logger=None):
    """Block while a pause is requested; the measurement holds in place.

    Returns the seconds spent paused (0.0 if not paused at all), or None if the
    user aborted while paused — the caller then stops its sweep.  ``should_stop``
    is the running procedure's abort check.
    """
    import time
    if not run_control.pause_requested:
        return 0.0
    if logger:
        logger.warning("Measurement PAUSED — press Continue to resume (or Abort to stop).")
    t0 = time.perf_counter()
    while run_control.pause_requested:
        if should_stop():
            return None
        time.sleep(0.2)
    if logger:
        logger.info("Measurement resumed.")
    return time.perf_counter() - t0
