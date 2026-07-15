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
from src.classes import live_readout


def read_signals(field_A) -> dict:
    """Acquire one point of the common MOKE signals and return them as a dict.

    Triggers the DAC acquisition, reads the Hall field while it runs, then reads
    the balanced/intensity diodes and the lock-in first-harmonic outputs.  Also
    updates the Live tab snapshot.  Shared by the position sweeps and the
    time-domain measurement so the acquisition lives in exactly one place.

    ``field_A`` is the commanded coil current (recorded as the field set-point).
    """
    dac.start_tasks()
    B_measurement = hall_sensor.read_mT()
    balanced_diodes_data, intensity_diode_data = dac.read_data()
    balanced_diodes_DC = np.mean(balanced_diodes_data)
    intensity_DC       = np.mean(intensity_diode_data)

    # Keep the Live tab cards updating from this running measurement.
    live_readout.push(balanced_diodes_DC, intensity_DC, B_measurement)

    # One lock-in transaction per point ('XY.'); R/theta derived from the same
    # sample — instead of four separate queries (X./Y./MAG./PHA.).
    lockin_x, lockin_y, lockin_r, lockin_theta = meas.read_xy_rt()

    return {
        'Magnetic Field (A)':   field_A,
        'Magnetic Field (T)':   B_measurement / 1000.0,
        'Voltage X 1f (V)':     lockin_x,
        'Voltage Y 1f (V)':     lockin_y,
        'Voltage R 1f (V)':     lockin_r,
        'Voltage theta 1f (V)': lockin_theta,
        'Voltage DC (V)':       balanced_diodes_DC,
        'Voltage DC STD (V)':   np.std(balanced_diodes_data),
        'Intensity (V)':        intensity_DC,
        'Intensity STD (V)':    np.std(intensity_diode_data),
    }


DAC_SAMPLING_RATE = 50_000.0    # samples/s for the DAC ADC acquisition window


# The stages are commanded in millimetres, but every user-facing position
# (parameters, data columns, plot/map axes) is in micrometres — easier to read
# and type for the µm-scale moves this setup makes.  Convert only here, at the
# hardware boundary, so mm never leaks into the user-facing layer.
UM_PER_MM = 1000.0


def move_x_um(x_um):
    """Command the stage X axis to a target given in micrometres."""
    stage.move_x_to(x_um / UM_PER_MM)


def move_y_um(y_um):
    """Command the stage Y axis to a target given in micrometres."""
    stage.move_y_to(y_um / UM_PER_MM)


def pos_x_um():
    """Current stage X position in micrometres."""
    return stage.get_x_pos() * UM_PER_MM


def pos_y_um():
    """Current stage Y position in micrometres."""
    return stage.get_y_pos() * UM_PER_MM


class PositionSweep(Procedure):
    """Common engine for the X / Y / XY position sweeps."""

    # Every position sweep records exactly these columns.
    DATA_COLUMNS = [
        'Iteration',
        'X Position (um)',
        'Y Position (um)',
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
        'Loop',                 # loop index — used by the plot to break the line
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
        log.info(f"Move stage to ({x0}um, {y0}um)")
        move_x_um(x0)
        move_y_um(y0)
        stage.wait_stable()

        # The lock-in's own oscillator provides the modulation: it outputs `volt`
        # at `lockin_freq` (driving the sample current through the external
        # current source).  The DAC generates NO modulation — it only drives the
        # coil current (field) and opens the ADC window to sample the diodes.
        dac.setup_aquisition(modulation_channel="None", frequency=self.lockin_freq,
                             acquisition_time=self.acq_time, sampling_rate=DAC_SAMPLING_RATE,
                             modulation_amp=0.0)

        # The offline stub returns exact zeros for every lock-in channel — a run
        # would "work" but record nothing.  Say so loudly in the run log (the
        # fallback itself happens at import time, before the GUI log exists).
        if not getattr(meas, "enabled", True):
            from src.classes import try_revive_lockin
            if try_revive_lockin() is not None:
                log.info("Lock-in reconnected — continuing this run with the live instrument.")
        if not getattr(meas, "enabled", True):
            log.warning("Lock-in is OFFLINE (it was not reachable when the app started) — "
                        "Voltage X/Y/R/theta will all be zero! Close the app, make sure the "
                        "lock-in is reachable (power-cycle it if a previous session crashed, "
                        "it only accepts one Ethernet connection), then start the app again.")

        # Single reference mode (REFMODE 0): one demodulator at the modulation
        # frequency, read as meas.x/y/mag/theta.  We deliberately do NOT use the
        # dual-harmonic mode (REFMODE 1): its second demodulator (the 2f channel)
        # is unused here and would overload on the MOKE signal, injecting spikes.
        # Set it explicitly so the run never depends on whatever mode the
        # instrument was last left in.
        dsp.set_reference_mode(0)
        dsp.setup_lockin_condition(lockin_voltage=self.volt, lockin_sensitivity=self.sensi,
                                   lockin_frequency=self.lockin_freq,
                                   lockin_time_constant=self.time_const, lockin_phase=self.phase)
        dac.coils_output = self.b

    def _measure_point(self, item, iteration) -> dict:
        """Acquire one point and return the results row.

        ``item`` is the commanded coil current; ``iteration`` is the value stored
        in the ``Iteration`` column (defined by the subclass's scan sequence).
        """
        data = read_signals(item)
        data['Iteration']       = iteration
        data['X Position (um)'] = pos_x_um()
        data['Y Position (um)'] = pos_y_um()
        return data

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

        for done, (xt, yt, item, iteration, loop) in enumerate(seq):
            if item != last_item:
                dac.coils_output = item
                last_item = item
            moved = False
            if xt != last_x:
                move_x_um(xt)
                last_x = xt
                moved = True
            if yt != last_y:
                move_y_um(yt)
                last_y = yt
                moved = True

            # Optional pause between the move and the acquisition, so stage
            # vibrations die out and the lock-in output (time constant) settles
            # at the new spot before the integration window opens.
            settle = float(getattr(self, "settle_time", 0.0) or 0.0)
            if moved and settle > 0:
                time.sleep(settle)

            data = self._measure_point(item, iteration)
            data['Loop'] = loop
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
                move_x_um(x0)
                move_y_um(y0)
            dac.set_outputs_and_reset([0., 0., 0.])
            hall_sensor.set_aquisition_time(0.5)
        finally:
            # Always release the hardware so the live tab resumes, even if a
            # teardown call above raised.
            dac.reserved         = False
            hall_sensor.reserved = False
