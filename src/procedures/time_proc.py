"""
Description:
    Time-domain measurement.

    Holds the field (coil current) and the lock-in output voltage (which drives
    the sample current through the external current source) constant, and records
    the MOKE signals as they evolve in time.

    The per-point acquisition is shared with the position sweeps via
    ``read_signals`` (see position_sweep.py), so all measurements read the
    hardware identically.
"""

import time
import numpy as np

from pymeasure.experiment import Procedure, FloatParameter, Metadata

from src.classes import active_stage as stage, dac, hall_sensor, log
from src.classes import meas, dsp
from src.classes import proc_config
from .position_sweep import read_signals


class TimeMeasurement(Procedure):
    """Record the MOKE signals versus time at a fixed field and lock-in drive."""
    name = "Time"

    # Metadata
    exp_type_md = Metadata("Experiment type")
    sample_md   = Metadata("Sample name")
    nb_it_md    = Metadata("Total number of points")
    time_md     = Metadata("Beginning of experiment", fget=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())))

    section = proc_config.get_section(name)

    # ── Setpoints held constant during the trace ─────────────────────────────
    b    = FloatParameter('Field', units='A', default=section.get("b", 0.0), minimum=-6, maximum=6)
    volt = FloatParameter('Lockin output voltage (sample current)', units='V',
                          default=section.get("volt", 0.0), minimum=0, maximum=5)

    # ── Lock-in configuration (to read the MOKE signal) ──────────────────────
    sensi       = FloatParameter('Lockin sensitivity',   units='V',   default=section.get("sensi", 500.00e-6), minimum=1.0e-6, maximum=1)
    lockin_freq = FloatParameter('Lockin frequency',     units='Hz',  default=section.get("lockin_freq", 1777), minimum=173)
    time_const  = FloatParameter('Lockin time constant', units='s',   default=section.get("time_const", 0.5),  minimum=0.1, maximum=10)
    phase       = FloatParameter('Lockin phase',         units='deg', default=section.get("phase", 0),         minimum=-180, maximum=180)
    acq_time    = FloatParameter('Aquisition time',      units='s',   default=section.get("acq_time", 0.5),    minimum=1e-6)

    # ── Position to sit at ───────────────────────────────────────────────────
    x = FloatParameter('Position x', units='mm', default=section.get("x", 0))
    y = FloatParameter('Position y', units='mm', default=section.get("y", 0))

    # ── Time base ────────────────────────────────────────────────────────────
    duration = FloatParameter('Duration',          units='s', default=section.get("duration", 60), minimum=1e-3)
    interval = FloatParameter('Sampling interval',  units='s', default=section.get("interval", 0.5), minimum=1e-6)

    DATA_COLUMNS = [
        'Time (s)',
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
        dac.reserved         = True
        hall_sensor.reserved = True
        hall_sensor.set_aquisition_time(self.acq_time)
        proc_config.save_parameters_dict(self.name, self._parameters)

        self.exp_type_md = "Time-domain measurement"
        self.sample_md   = self.sample_name
        self._num_points = max(1, int(self.duration / self.interval))
        self.nb_it_md    = self._num_points

        # Apply the constant field and move to the measurement position.
        if self.b != 0:
            log.info(f"Setting field to {self.b} A, wait 1 s...")
            dac.set_outputs_and_reset([0., 0., self.b])
            time.sleep(1)
        log.info(f"Move stage to ({self.x} mm, {self.y} mm)")
        stage.move_x_to(self.x)
        stage.move_y_to(self.y)
        stage.wait_stable()

        dac.setup_aquisition(modulation_channel="None", frequency=self.lockin_freq,
                             acquisition_time=self.acq_time, sampling_rate=50000,
                             modulation_amp=0.)
        # Read the lock-in's first-harmonic outputs (dual-harmonic reference mode).
        dsp.set_reference_mode(1)
        dsp.setup_lockin_condition(lockin_voltage=self.volt, lockin_sensitivity=self.sensi,
                                   lockin_frequency=self.lockin_freq,
                                   lockin_time_constant=self.time_const, lockin_phase=self.phase)
        dac.coils_output = self.b       # field held constant

    def execute(self):
        log.info("Recording time trace...")
        n     = self._num_points
        start = time.perf_counter()
        for k in range(n):
            t_point  = time.perf_counter() - start
            deadline = start + (k + 1) * self.interval

            data = read_signals(self.b)
            data['Time (s)'] = t_point
            self.emit('results', data)
            self.emit('progress', 100 * (k + 1) / n)

            if self.should_stop():
                break

            # Keep the requested spacing between samples.
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

        meas.shutdown()

    def shutdown(self):
        log.info("Time trace done, turning off the outputs")
        try:
            dac.set_outputs_and_reset([0., 0., 0.])
            hall_sensor.set_aquisition_time(0.5)
        finally:
            dac.reserved         = False
            hall_sensor.reserved = False
