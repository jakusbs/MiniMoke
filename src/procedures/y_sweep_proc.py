"""
File:         procedures/y_sweep_proc.py
Author:       Eliott Sarrey
Date:         June 2023
Email:        eliott.sarrey@gmail.com

Description: 
    Define the full experiment procedure for a sweep along the Y axis.
    This file defines the necessary parameters, which are automatically used by
    the UI thanks to pymeasure.
    Then, it proceed to the main loop and perform the DC and AC measurements of the voltage
    and save many other values. It also modulates the magnetic field at a given frequency.
    All the results are saved in the DATA_COLUMNS object and plotted live in the main UI.
"""

import time
import numpy as np

from pymeasure.experiment import Procedure, FloatParameter, Metadata, ListParameter

from src.classes import active_stage as stage, dac, hall_sensor, log
from src.classes import meas, dsp
from src.classes import proc_config, dac_config


class Y_Sweep(Procedure):
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

    # Define all the data columns which will be recorded in the procedure
    DATA_COLUMNS = [
        'Iteration',
        'X Position (m)',
        'Y Position (m)',
        'Magnetic Field (A)',
        'Magnetic Field (T)',
        'Voltage X 1f (V)',
        'Voltage Y 1f (V)',
        'Voltage R 1f (V)',
        'Voltage theta 1f (V)',
        'Voltage DC (V)',
        'Voltage DC STD (V)',
        'Intensity (V)',
        'Intensity STD (V)',
    ]

    def set_sample_name(self, sample_name):
        self.sample_name = sample_name

    def startup(self):
        """
        Define the tasks to do at the procedure's startup
        """
        dac.reserved         = True
        hall_sensor.reserved = True
        hall_sensor.set_aquisition_time(self.acq_time)
        proc_config.save_parameters_dict(self.name, self._parameters)

        # Define the values of positions for the sweep
        self.y_values = np.linspace(self.y_min, self.y_max,
                                    int(np.abs(self.y_max - self.y_min) // self.y_step + 1),
                                    endpoint=True)

        # Set the values of the metadata
        self.exp_type_md = "Sweep along y"
        self.sample_md   = self.sample_name
        self.nb_it_md    = len(self.y_values)

        # If the first value of the magnetic field is not zero, set it up and wait 1s
        if self.b != 0:
            log.info(f"Setting up magnetic field to {self.b}A, wait 1s")
            dac.set_outputs_and_reset([0., 0., self.b])
            time.sleep(1)

        # Go to the required position and wait for the motors to be stable
        log.info(f"Move stage to ({self.x}mm, {self.y_min}mm)")
        stage.move_x_to(self.x)
        stage.move_y_to(self.y_min)
        stage.wait_stable()

        # Setup the acquisition in the DAC with our parameters
        dac.setup_aquisition(modulation_channel=self.demod, frequency=self.freq,
                             acquisition_time=self.acq_time, sampling_rate=self.rate,
                             modulation_amp=self.mod_amp)
        # This scan reads the lock-in's first-harmonic outputs
        # (meas.x1/y1/mag1/theta1), which are only valid in dual-harmonic
        # reference mode.  Set it explicitly so the run never depends on whatever
        # mode the instrument was last left in (otherwise those reads return an
        # empty string and raise mid-sweep).
        dsp.set_reference_mode(1)
        dsp.setup_lockin_condition(lockin_voltage=self.volt, lockin_sensitivity=self.sensi,
                                   lockin_frequency=self.lockin_freq,
                                   lockin_time_constant=self.time_const, lockin_phase=self.phase)
        dac.dc_output = [self.cst_out1, self.cst_out2]

    def execute(self):
        """
        Define the core of the procedure
        """
        log.info("Aquisition...")
        count = -1
        for item in [self.b, -self.b] * int(self.repeat_num):
            count += 1
            dac.coils_output = item

            # Start sweeping loop
            for i in range(len(self.y_values)):

                # We move the stage to the next position
                stage.move_y_to(self.y_values[i])

                # We first trigger the task which will take acquisition time to complete on the DAC
                dac.start_tasks()
                # In the meantime we read the magnetic field
                B_measurement = hall_sensor.read_mT()
                # Then we read the data on the DAC; read_data will wait for the task to be done
                balanced_diodes_data, intensity_diode_data = dac.read_data()
                balanced_diodes_DC = np.mean(balanced_diodes_data)

                # The 1f MOKE signal columns are read directly from the lock-in
                # amplifier (meas.x1/y1/mag1/theta1) below.  The software
                # demodulation that used to run here was computed but never used
                # (its result was discarded), so it has been removed to avoid the
                # dead per-point filtfilt cost.

                data = {
                    'Iteration':            i,
                    'X Position (m)':       stage.get_x_pos() / 1000.0,
                    'Y Position (m)':       stage.get_y_pos() / 1000.0,
                    'Magnetic Field (A)':   item,
                    'Magnetic Field (T)':   B_measurement / 1000.0,
                    'Voltage X 1f (V)':     meas.x1,
                    'Voltage Y 1f (V)':     meas.y1,
                    'Voltage R 1f (V)':     meas.mag1,
                    'Voltage theta 1f (V)': meas.theta1,
                    # 'Voltage R 2f (V)':   balanced_diodes_2f["R"],
                    # 'Voltage X 2f (V)':   meas.x2,
                    # 'Voltage Y 2f (V)':   meas.y2,
                    # 'Voltage theta 2f (V)':balanced_diodes_2f["theta"],
                    'Voltage DC (V)':       balanced_diodes_DC,
                    'Voltage DC STD (V)':   np.std(balanced_diodes_data),
                    'Intensity (V)':        np.mean(intensity_diode_data),
                    'Intensity STD (V)':    np.std(intensity_diode_data),
                }

                log.debug("Produced numbers: %s" % data)
                self.emit('results', data)
                prog = count * len(self.y_values) + i
                self.emit('progress', 100 * prog / len(self.y_values) /
                          len([self.b] * int(self.repeat_num) + [-self.b] * int(self.repeat_num)))
                if self.should_stop():
                    break
        meas.shutdown()  # Set the lockin output to zero

    def shutdown(self):
        """
        Define the tasks to do at the procedure's end
        """
        log.info("Aquisition done, turning off the outputs")
        try:
            # On abort, stop where we are: the move back to the start is long and
            # not abortable, and running it here is the main reason an abort can
            # appear to hang the app (pymeasure only finishes the abort once
            # shutdown() returns).  The field is still switched off below.
            if not self.should_stop():
                stage.move_x_to(self.x)
                stage.move_y_to(self.y_min)
            dac.set_outputs_and_reset([0., 0., 0.])
            hall_sensor.set_aquisition_time(0.5)
        finally:
            # Always release the hardware so the live tab resumes, even if a
            # teardown call above raised.
            dac.reserved         = False
            hall_sensor.reserved = False