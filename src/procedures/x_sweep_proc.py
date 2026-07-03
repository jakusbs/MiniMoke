"""
Description:
    Experiment procedure for a sweep along the X axis.

    Only the X-specific bits live here (the parameters, the metadata and the
    scan definition).  All the shared acquisition logic — hardware setup, the
    per-point measurement, the sweep loop and teardown — lives in
    ``PositionSweep`` (see position_sweep.py), which this class extends.
"""

import time
import numpy as np

from pymeasure.experiment import FloatParameter, Metadata

from src.classes import proc_config
from .position_sweep import PositionSweep


class X_Sweep(PositionSweep):
    """
    Procedure for a sweep along the X axis
    """
    name = "X-Sweep"                                    # Define the name of the procedure
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
    x_min      = FloatParameter('From x',                 units='um',  default=section.get("x_min", 0))
    x_max      = FloatParameter('To x',                   units='um',  default=section.get("x_max", 100))
    x_step     = FloatParameter('Step',                   units='um',  default=section.get("x_step", 10))
    y          = FloatParameter('Position y',             units='um',  default=section.get("y", 0))
    b          = FloatParameter('Field ',                 units='A',   default=section.get("b", 0.),              minimum=-6,   maximum=6)
    repeat_num = FloatParameter('Repeat number ',         units='',    default=section.get("repeat_num", 5),      minimum=1,    maximum=1000)

    def _configure_scan(self):
        # Sweep x at the fixed y; for each field direction, step through every x.
        # Order: field outer, position inner.  Iteration = position index.
        self.x_values = np.linspace(self.x_min, self.x_max,
                                    int(np.abs(self.x_max - self.x_min) // self.x_step + 1),
                                    endpoint=True)
        # Each field pass over all positions is one loop (own line in the plot).
        field_seq = [self.b, -self.b] * int(self.repeat_num)
        self._scan_sequence = [(xv, self.y, item, i, loop)
                               for loop, item in enumerate(field_seq)
                               for i, xv in enumerate(self.x_values)]

        self.exp_type_md = "Sweep along x"
        self.nb_it_md    = len(self.x_values)
