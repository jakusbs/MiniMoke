"""
Shared base class for the position sweeps (X-Sweep, Y-Sweep, XY-Sweep).

These three procedures are identical apart from *which* stage axis (or axes) is
stepped and in what loop order.  To avoid the copy-paste drift that previously
let bugs live in only one of the three (e.g. the XY progress overflow), all the
common logic — hardware setup, the per-point measurement, the sweep loop and the
teardown — lives here.

Each concrete procedure only needs to:
  * declare its own Parameters / Metadata (kept in the subclass so each keeps its
    own ``[X-Sweep]`` / ``[Y-Sweep]`` / ``[XY-Sweep]`` config section and the
    "remember last settings" behaviour), and
  * implement ``_configure_scan()`` to build ``self._scan_sequence`` — an ordered
    list of ``(x_target, y_target, field_value, iteration)`` tuples — and set the
    ``exp_type_md`` / ``nb_it_md`` metadata.

The base then runs one flat loop over that sequence, so the exact visit order and
emitted columns of each procedure are preserved.
"""

import time
import numpy as np

from pymeasure.experiment import Procedure

from src.classes import active_stage as stage, dac, hall_sensor, log
from src.classes import meas, dsp
from src.classes import proc_config


class PositionSweep(Procedure):
    """Common engine for the X / Y / XY position sweeps."""

    # Every position sweep records exactly these columns.
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

    # ------------------------------------------------------------------
    # Subclass hook
    # ------------------------------------------------------------------
    def _configure_scan(self) -> None:
        """Build ``self._scan_sequence`` and set ``exp_type_md`` / ``nb_it_md``.

        ``self._scan_sequence`` is an ordered list of
        ``(x_target, y_target, field_value, iteration)`` tuples; the base
        ``execute()`` visits them in order.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def startup(self):
        """Reserve hardware, build the scan, move to the start and configure the
        DAC and lock-in."""
        dac.reserved         = True
        hall_sensor.reserved = True
        hall_sensor.set_aquisition_time(self.acq_time)
        proc_config.save_parameters_dict(self.name, self._parameters)

        # Subclass defines the ordered list of points and the descriptive metadata
        self._configure_scan()
        self.sample_md = self.sample_name

        # The first scan point doubles as the "home" we return to on a normal finish.
        self._home = (self._scan_sequence[0][0], self._scan_sequence[0][1])

        # If the first value of the magnetic field is not zero, set it up and wait 1s
        if self.b != 0:
            log.info(f"Setting up magnetic field to {self.b}A, wait 1s")
            dac.set_outputs_and_reset([0., 0., self.b])
            time.sleep(1)

        # Go to the start position and wait for the motors to be stable
        x0, y0 = self._home
        log.info(f"Move stage to ({x0}mm, {y0}mm)")
        stage.move_x_to(x0)
        stage.move_y_to(y0)
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
        dac.coils_output = self.b
        dac.dc_output    = [self.cst_out1, self.cst_out2]

    def _measure_point(self, item, iteration) -> dict:
        """Acquire one point and return the results row.

        ``item`` is the commanded coil current; ``iteration`` is the value stored
        in the ``Iteration`` column (defined by the subclass's scan sequence).
        """
        # Trigger the DAC task (takes the acquisition time to complete) ...
        dac.start_tasks()
        # ... read the magnetic field while it runs ...
        B_measurement = hall_sensor.read_mT()
        # ... then read the DAC data (waits for the task to finish).
        balanced_diodes_data, intensity_diode_data = dac.read_data()
        balanced_diodes_DC = np.mean(balanced_diodes_data)

        # The 1f MOKE signal columns come directly from the lock-in amplifier.
        return {
            'Iteration':            iteration,
            'X Position (m)':       stage.get_x_pos() / 1000.0,
            'Y Position (m)':       stage.get_y_pos() / 1000.0,
            'Magnetic Field (A)':   item,
            'Magnetic Field (T)':   B_measurement / 1000.0,
            'Voltage X 1f (V)':     meas.x1,
            'Voltage Y 1f (V)':     meas.y1,
            'Voltage R 1f (V)':     meas.mag1,
            'Voltage theta 1f (V)': meas.theta1,
            'Voltage DC (V)':       balanced_diodes_DC,
            'Voltage DC STD (V)':   np.std(balanced_diodes_data),
            'Intensity (V)':        np.mean(intensity_diode_data),
            'Intensity STD (V)':    np.std(intensity_diode_data),
        }

    def execute(self):
        """Walk the scan sequence, measuring one point at each step.

        Only the axes/field that actually change between consecutive points are
        re-commanded, so the hardware sees the same moves the original nested
        loops produced.
        """
        log.info("Aquisition...")
        seq   = self._scan_sequence
        total = len(seq)

        last_x, last_y = self._home    # already positioned there by startup()
        last_item = None

        for done, (xt, yt, item, iteration) in enumerate(seq):
            if item != last_item:
                dac.coils_output = item
                last_item = item
            if xt != last_x:
                stage.move_x_to(xt)
                last_x = xt
            if yt != last_y:
                stage.move_y_to(yt)
                last_y = yt

            data = self._measure_point(item, iteration)
            log.debug("Produced numbers: %s" % data)
            self.emit('results', data)
            self.emit('progress', 100 * (done + 1) / total)

            if self.should_stop():
                break

        meas.shutdown()  # Set the lockin output to zero

    def shutdown(self):
        """Turn off the outputs and release the hardware."""
        log.info("Aquisition done, turning off the outputs")
        # _home is only set once startup() builds the scan; if startup failed
        # earlier, fall back to no move-back so the hardware is still released.
        home = getattr(self, "_home", None)
        try:
            # On abort, stop where we are: the move back to the start is long and
            # not abortable, and running it here is the main reason an abort can
            # appear to hang the app (pymeasure only finishes the abort once
            # shutdown() returns).  The field is still switched off below.
            if home is not None and not self.should_stop():
                x0, y0 = home
                stage.move_x_to(x0)
                stage.move_y_to(y0)
            dac.set_outputs_and_reset([0., 0., 0.])
            hall_sensor.set_aquisition_time(0.5)
        finally:
            # Always release the hardware so the live tab resumes, even if a
            # teardown call above raised.
            dac.reserved         = False
            hall_sensor.reserved = False
