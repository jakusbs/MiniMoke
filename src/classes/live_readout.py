"""
A tiny shared snapshot of the most recent measurement values.

The "Live measurements" tab normally reads the DAC/Hall sensor itself, but it
must back off while a procedure owns the hardware (``reserved`` is True).  So
that the live cards keep updating during a scan instead of freezing, the running
procedure pushes its per-point values here and the Live tab reads them while the
hardware is reserved.

Plain attribute assignment is atomic under the GIL and the values are only used
for display, so no lock is needed.
"""

import math


class LiveReadout:
    def __init__(self):
        self.balanced_v  = 0.0    # balanced-diode DC (V)
        self.intensity_v = 0.0    # intensity-diode DC (V)
        self.field_mT    = 0.0    # Hall field (mT)

    def push(self, balanced_v, intensity_v, field_mT):
        """Store the latest point's values (call once per acquired point).

        ``field_mT`` may be None or NaN when the Hall sensor was skipped (very
        fast field sweeps); in that case the previous field value is kept rather
        than showing a blank/NaN card.
        """
        self.balanced_v  = balanced_v
        self.intensity_v = intensity_v
        if field_mT is not None and not (isinstance(field_mT, float) and math.isnan(field_mT)):
            self.field_mT = field_mT


# Global instance shared by the procedures (writers) and the Live tab (reader).
live_readout = LiveReadout()
