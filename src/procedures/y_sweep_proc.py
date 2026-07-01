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

from pymeasure.experiment import FloatParameter, Metadata, ListParameter

from src.classes import proc_config, dac_config
from .position_sweep import PositionSweep


class Y_Sweep(PositionSweep):
    """
    Procedure for a sweep along the Y axis
    """
    name = "Y-Sweep"                                    # Define the name of the procedure

    # Create metadata objects, values will be stored during the startup
    exp_type_md = Metadata("Experiment type")
    sample_md   = Metadata("Sample name")
    nb_it_md    = Metadata("Total number of iterations (if success)")
    time_md     = Metadata("Beginning of experiment", fget=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())))

    # Define the AC channels
    AC_ports = dac_config.get_section('IO ports')
    AC_chan   = [f'AC_Output1 ({AC_ports.get("AC_Output1", "None")})', f'AC_Output2 ({AC_ports.get("AC_Output2", "None")})', 'None']

    section = proc_config.get_section(name)             # Get the saved parameters values from the config file

    # Define all the parameters with their type (float, bool), name, units and minimum and maximum
    volt       = FloatParameter('Lockin output voltage',  units='V',   default=section.get("volt", 1.0),          minimum=0,    maximum=5)
    sensi      = FloatParameter('Lockin sensitivity',    units='V',   default=section.get("sensi", 500.00e-6),   minimum=1.0e-6, maximum=1)
    lockin_freq= FloatParameter('Lockin frequency',       units='Hz',  default=section.get("lockin_freq", 1777),  minimum=173)
    time_const = FloatParameter('Lockin time constant',   units='s',   default=section.get("time_const", 0.5),    minimum=0.1,  maximum=10)
    phase      = FloatParameter('Lockin phase',           units='deg', default=section.get("phase", 0),           minimum=-180, maximum=180)
    acq_time   = FloatParameter('Aquisition time',        units='s',   default=section.get("acq_time", 1),        minimum=1e-6)
    freq       = FloatParameter('Field modulation Freq',  units='Hz',  default=section.get("freq", 1777),         minimum=1,    maximum=1e5)
    demod      = ListParameter( 'Modulation channel',     AC_chan,     default=section.get("demod", AC_chan[0]))
    y_min      = FloatParameter('From y',                 units='mm',  default=section.get("y_min", 0))
    y_max      = FloatParameter('To y',                   units='mm',  default=section.get("y_max", 0.1))
    y_step     = FloatParameter('Step',                   units='mm',  default=section.get("y_step", 0.01))
    x          = FloatParameter('Position x',             units='mm',  default=section.get("x", 0))
    b          = FloatParameter('Field ',                 units='A',   default=section.get("b", 0.),              minimum=-6,   maximum=6)
    repeat_num = FloatParameter('Repeat number ',         units='',    default=section.get("repeat_num", 5),      minimum=1,    maximum=1000)

    # Only active if modulation is used
    rate       = FloatParameter('Sampling rate',          units='Hz',  default=section.get("rate", 50000),        minimum=10,   maximum=1.25e6,
                                group_by='demod', group_condition=lambda v: 'AC_Output1' in v or 'AC_Output2' in v)
    lockin_bw  = FloatParameter('Lockin bandwith',        units='Hz',  default=section.get("lockin_bw", 50),      minimum=1,    maximum=1e5,
                                group_by='demod', group_condition=lambda v: 'AC_Output1' in v or 'AC_Output2' in v)
    mod_amp    = FloatParameter('Modulation amplitude',   units='V',   default=section.get("mod_amp", 1),         minimum=0,    maximum=2,
                                group_by='demod', group_condition=lambda v: 'AC_Output1' in v or 'AC_Output2' in v)

    # Active the correct input or the 2 of them if no modulation is required by the user
    cst_out1   = FloatParameter(f'Constant output 1 ({AC_ports.get("AC_Output1", "None")})',
                                units='V', default=section.get("cst_out", 0), minimum=0, maximum=2,
                                group_by='demod', group_condition=lambda v: v == 'None' or 'AC_Output2' in v)
    cst_out2   = FloatParameter(f'Constant output 2 ({AC_ports.get("AC_Output2", "None")})',
                                units='V', default=section.get("cst_out", 0), minimum=0, maximum=2,
                                group_by='demod', group_condition=lambda v: v == 'None' or 'AC_Output1' in v)

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
