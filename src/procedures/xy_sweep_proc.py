"""
File:         procedures/xy_sweep_proc.py
Author:       Eliott Sarrey
Date:         June 2023
Email:        eliott.sarrey@gmail.com

Description:
    Experiment procedure for a grid sweep along both the X and Y axes.

    Only the grid-specific bits live here (the parameters, the metadata and the
    scan definition).  All the shared acquisition logic lives in
    ``PositionSweep`` (see position_sweep.py), which this class extends.
"""

import time
import numpy as np

from pymeasure.experiment import FloatParameter, Metadata

from src.classes import proc_config
from .position_sweep import PositionSweep


class XY_Sweep(PositionSweep):
    """
    Procedure for a grid sweep along X and Y axes
    """
    name = "XY-Sweep"                                   # Define the name of the procedure
    DEFAULT_X_AXIS = "X Position (um)"                   # plot x-axis when this tab is open

    # Create metadata objects, values will be stored during the startup
    exp_type_md = Metadata("Experiment type")
    sample_md   = Metadata("Sample name")
    nb_it_md    = Metadata("Total number of iterations (if success)")
    time_md     = Metadata("Beginning of experiment", fget=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())))

    section = proc_config.get_section(name)             # Get the saved parameters values from the config file

    # The lock-in's own oscillator provides the modulation: `volt` is the
    # oscillator amplitude (the voltage that drives the sample current through
    # the external current source) at `lockin_freq`.  No DAC modulation is used.
    volt       = FloatParameter('Lock-in oscillator amplitude', units='V', default=section.get("volt", 1.0), minimum=0, maximum=5)
    sensi      = FloatParameter('Lockin sensitivity',    units='V',   default=section.get("sensi", 500.00e-6),   minimum=1.0e-6, maximum=1)
    lockin_freq= FloatParameter('Lockin frequency',       units='Hz',  default=section.get("lockin_freq", 1777),  minimum=173)
    time_const = FloatParameter('Lockin time constant',   units='s',   default=section.get("time_const", 0.5),    minimum=0.1,  maximum=10)
    phase      = FloatParameter('Lockin phase',           units='deg', default=section.get("phase", 0),           minimum=-180, maximum=180)
    acq_time   = FloatParameter('Aquisition time',        units='s',   default=section.get("acq_time", 1),        minimum=1e-6)
    settle_time= FloatParameter('Settle time after move', units='s',   default=section.get("settle_time", 0.0),   minimum=0,    maximum=60)
    x_min      = FloatParameter('From x',                 units='um',  default=section.get("x_min", 0))
    x_max      = FloatParameter('To x',                   units='um',  default=section.get("x_max", 100))
    x_step     = FloatParameter('Step x',                 units='um',  default=section.get("x_step", 10))
    y_min      = FloatParameter('From y',                 units='um',  default=section.get("y_min", 0))
    y_max      = FloatParameter('To y',                   units='um',  default=section.get("y_max", 100))
    y_step     = FloatParameter('Step y',                 units='um',  default=section.get("y_step", 10))
    b          = FloatParameter('Field ',                 units='A',   default=section.get("b", 0.),              minimum=-6,   maximum=6)
    repeat_num = FloatParameter('Repeat number ',         units='',    default=section.get("repeat_num", 1),      minimum=1,    maximum=100)

    @staticmethod
    def _axis_points(lo, hi, step) -> int:
        """Number of scan points on one axis (single source of truth for both
        the scan grid and the 2D-map grid, so the two can never disagree)."""
        if not step:
            return 1
        return int(np.abs(hi - lo) // step + 1)

    def _configure_scan(self):
        # 2D map: raster the grid ONCE per point at a fixed field ``b`` — no
        # +b/-b field doubling (that scanned every column twice) — snaking in y
        # (serpentine) so the stage never flies back to y_min between columns:
        # each column sweeps y in the opposite direction to the previous one.
        # Each column is one "loop" (its own line in the results graph); the 2D
        # map bins by position, so the snaking visit order still fills the grid
        # correctly.  ``repeat_num`` repeats the whole map (its own loops).
        nx = self._axis_points(self.x_min, self.x_max, self.x_step)
        ny = self._axis_points(self.y_min, self.y_max, self.y_step)
        self.x_values = np.linspace(self.x_min, self.x_max, nx, endpoint=True)
        self.y_values = np.linspace(self.y_min, self.y_max, ny, endpoint=True)

        self._scan_sequence = []
        loop = 0
        for _ in range(max(int(self.repeat_num), 1)):
            for i, xv in enumerate(self.x_values):
                ys = self.y_values if (i % 2 == 0) else self.y_values[::-1]
                for yv in ys:
                    self._scan_sequence.append((xv, yv, self.b, i, loop))
                loop += 1   # each column is its own line segment

        self.exp_type_md = "Map along x and y (grid, serpentine)"
        self.nb_it_md    = len(self.x_values) * len(self.y_values)

    # ── 2D-map grid bounds ────────────────────────────────────────────────────
    # The results "2D Map" tab uses pymeasure's ImageWidget / ResultsImage, which
    # reads the grid extent from attributes named "<column>_start/_end/_step" in
    # that column's own units.  Positions are in micrometres here, same as the
    # parameters, so no unit conversion is needed.  The step is the *actual*
    # linspace spacing (span / (N-1)), not the requested x_step, so every image
    # cell lines up with a scan point even when the step does not divide the
    # range evenly.
    #
    # These are exposed lazily via __getattr__ so they are correct both for a
    # live queue (GUI values) and for a re-opened data file (values restored by
    # Results.load) — in neither case need startup() have run.  __getattr__ only
    # fires for names normal lookup misses, so it never shadows the parameters.
    _MAP_AXES = {
        "X Position (um)": ("x_min", "x_max", "x_step"),
        "Y Position (um)": ("y_min", "y_max", "y_step"),
    }

    def _grid_bounds(self, lo, hi, step):
        """(start, end, step) in micrometres, sized to one cell per scan point."""
        n = self._axis_points(lo, hi, step)
        start, end = min(lo, hi), max(lo, hi)
        span = end - start
        grid_step = span / (n - 1) if n > 1 and span else (abs(step) or 1.0)
        return start, end, grid_step

    def __getattr__(self, name):
        for col, (lo, hi, st) in XY_Sweep._MAP_AXES.items():
            for idx, suffix in enumerate(("_start", "_end", "_step")):
                if name == col + suffix:
                    bounds = self._grid_bounds(getattr(self, lo),
                                               getattr(self, hi),
                                               getattr(self, st))
                    return bounds[idx]
        raise AttributeError(name)
