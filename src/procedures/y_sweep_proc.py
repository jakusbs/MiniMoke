"""
File:         procedures/y_sweep_proc.py
Author:       Eliott Sarrey
Date:         June 2023
Email:        eliott.sarrey@gmail.com

Description:
    Experiment procedure for a sweep along the Y axis.

    Only the Y-specific bits live here (the parameters, the metadata and the
    scan definition).  All the shared acquisition logic lives in
    ``PositionSweep`` (see position_sweep.py), which this class extends.
"""

import time
import numpy as np

from pymeasure.experiment import FloatParameter, Metadata

from src.classes import proc_config
from .position_sweep import PositionSweep


class Y_Sweep(PositionSweep):
    """
    Procedure for a sweep along the Y axis
    """
    name = "Y-Sweep"                                    # Define the name of the procedure
    DEFAULT_X_AXIS = "Y Position (um)"                   # plot x-axis when this tab is open

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
    y_min      = FloatParameter('From y',                 units='um',  default=section.get("y_min", 0))
    y_max      = FloatParameter('To y',                   units='um',  default=section.get("y_max", 100))
    y_step     = FloatParameter('Step',                   units='um',  default=section.get("y_step", 10))
    x          = FloatParameter('Position x',             units='um',  default=section.get("x", 0))
    b          = FloatParameter('Field ',                 units='A',   default=section.get("b", 0.),              minimum=-6,   maximum=6)
    repeat_num = FloatParameter('Repeat number ',         units='',    default=section.get("repeat_num", 5),      minimum=1,    maximum=1000)

    def _configure_scan(self):
        # Sweep y at the fixed x; for each field direction, step through every y.
        # Order: field outer, position inner.  Iteration = position index.
        self.y_values = np.linspace(self.y_min, self.y_max,
                                    int(np.abs(self.y_max - self.y_min) // self.y_step + 1),
                                    endpoint=True)
        # Each field pass over all positions is one loop (own line in the plot).
        field_seq = [self.b, -self.b] * int(self.repeat_num)
        self._scan_sequence = [(self.x, yv, item, i, loop)
                               for loop, item in enumerate(field_seq)
                               for i, yv in enumerate(self.y_values)]

        self.exp_type_md = "Sweep along y"
        self.nb_it_md    = len(self.y_values)
