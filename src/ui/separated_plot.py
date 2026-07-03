"""
Plot widget that draws each measurement loop as its own line segment.

When a procedure records several loops in one experiment (repeated field sweeps,
or repeated X/Y scans), connecting every point with a single line joins the end
of one loop to the start of the next, which is visually misleading.  The
procedures now emit a ``Loop`` column (an integer that changes at every new
loop); this widget uses it to break the connecting line between loops, while the
saved data itself is unchanged.

If a data set has no ``Loop`` column (e.g. an older file), it falls back to a
normal connected line.
"""

import numpy as np
import pyqtgraph as pg

from pymeasure.display.curves import ResultsCurve
from pymeasure.display.widgets import PlotWidget


def loop_connect(loop_values) -> np.ndarray:
    """Build a pyqtgraph ``connect`` array from a per-point loop index.

    ``connect[i] == 1`` joins point *i* to *i+1*; it is 0 at loop boundaries (and
    at the final point), so consecutive points with a different loop index are
    not connected.
    """
    loop = np.asarray(loop_values)
    n = loop.shape[0]
    connect = np.zeros(n, dtype=np.uint8)
    if n > 1:
        connect[:-1] = (loop[:-1] == loop[1:]).astype(np.uint8)
    return connect


class SeparatedResultsCurve(ResultsCurve):
    """A ResultsCurve that breaks the line between loops using the ``Loop`` column."""

    def update_data(self):
        if self.force_reload:
            self.results.reload()
        data = self.results.data
        xdata = data[self.x]
        ydata = data[self.y]
        try:
            if "Loop" in data.columns and len(data) > 1:
                self.setData(xdata, ydata,
                             connect=loop_connect(data["Loop"].to_numpy()))
                return
        except Exception:
            pass  # never let a plotting quirk break acquisition — fall back below
        self.setData(xdata, ydata)


class SeparatedPlotWidget(PlotWidget):
    """PlotWidget whose curves break the line between loops."""

    def new_curve(self, results, color=pg.intColor(0), **kwargs):
        if 'pen' not in kwargs:
            kwargs['pen'] = pg.mkPen(color=color, width=self.linewidth)
        if 'antialias' not in kwargs:
            kwargs['antialias'] = False
        curve = SeparatedResultsCurve(
            results,
            wdg=self,
            x=self.plot_frame.x_axis,
            y=self.plot_frame.y_axis,
            **kwargs,
        )
        curve.setSymbol(None)
        curve.setSymbolBrush(None)
        return curve
