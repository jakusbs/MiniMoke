"""
Description:
    Define the full experiment procedure for a magnetic sweep with fast repeated sweeps.

    Speed is controlled exclusively by 'sweep_freq' (full hysteresis loops per
    second) combined with 'b_step' (which sets the number of points per sweep).
    The hardware acquisition time per point is derived automatically from these
    two parameters — there is no separate acquisition time input.

    Timing model
    ------------
    Each point is allocated exactly  T_point = 1 / (sweep_freq * n_total)  seconds.
    A deadline is set at the START of each point; the code sets the field, reads
    the hall sensor and DAC, then sleeps only for the remaining budget — so all
    hardware latency is absorbed rather than added on top.

    At very high sweep frequencies (T_point < HALL_MIN_ACQ_S) the hall sensor
    cannot keep up.  In that mode the DAC set-point (Ampere) is used for the
    live field column and the real mT reading is only used for the averaged result
    (where the hardware has enough time because the DAC ramp is slow enough).

    Live data
    ---------
    * 'Voltage DC (V)'          – raw single-sweep value, emitted point-by-point.
    * 'Magnetic Field (mT)'     – measured field (or NaN if too fast), point-by-point.
    * 'Voltage DC Average (V)'  – emitted ONCE after all sweeps complete.
                                  Forward and backward branches are averaged
                                  independently (no cross-direction mixing).
"""

import time
import numpy as np

from pymeasure.experiment import (
    Procedure,
    FloatParameter,
    IntegerParameter,
    Metadata,
)

from src.classes import active_stage as stage, dac, hall_sensor, log
from src.classes import meas, dsp
from src.classes import proc_config, dac_config


# ---------------------------------------------------------------------------
# Minimum acquisition time the hall sensor hardware can honour.
# Measured / set empirically — adjust if your sensor differs.
# ---------------------------------------------------------------------------
HALL_MIN_ACQ_S = 0.002          # 2 ms  → max ~500 field-points/s from hall sensor
SETTLE_FRACTION = 0.05          # 5 % of T_point reserved for field settling
MIN_SETTLE_S    = 0.0           # no artificial floor — let sweep_freq drive it
DAC_SAMPLING_RATE = 50_000.0    # samples/s passed to dac.setup_aquisition


class B_Sweep(Procedure):
    """
    Procedure for fast repeated sweeps of the magnetic field with averaging.
    Forward and backward branches are accumulated separately so that averaging
    never mixes measurements taken in opposite field directions.
    """
    name = "B-Sweep"

    # ── Metadata ──────────────────────────────────────────────────────────────
    exp_type_md   = Metadata("Experiment type")
    sample_md     = Metadata("Sample name")
    nb_it_md      = Metadata("Total number of field points per sweep")
    nb_sweeps_md  = Metadata("Number of sweeps averaged")
    time_md       = Metadata(
        "Beginning of experiment",
        fget=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
    )

    section = proc_config.get_section(name)

    # ── Parameters shown in the UI ────────────────────────────────────────────
    b_min      = FloatParameter(
        "From B", units="A",
        default=section.get("b_min", -0.5), minimum=-6, maximum=6,
    )
    b_max      = FloatParameter(
        "To B", units="A",
        default=section.get("b_max", 0.5), minimum=-6, maximum=6,
    )
    b_step     = FloatParameter(
        "Step", units="A",
        default=section.get("b_step", 0.04), minimum=1e-8, maximum=12,
    )
    sweep_freq = FloatParameter(
        "Sweep frequency", units="Hz",
        default=section.get("sweep_freq", 1.0), minimum=0.01, maximum=100,
    )
    num_sweeps = IntegerParameter(
        "Number of sweeps to average",
        default=section.get("num_sweeps", 5), minimum=1, maximum=1000,
    )

    # Position parameters (used for output columns; not listed in UI inputs)
    x = FloatParameter("Position x", units="mm", default=section.get("x", 0.0))
    y = FloatParameter("Position y", units="mm", default=section.get("y", 0.0))

    # ── Output columns ────────────────────────────────────────────────────────
    DATA_COLUMNS = [
        "Iteration",
        "X Position (m)",
        "Y Position (m)",
        "Magnetic Field (A)",
        "Magnetic Field (T)",
        'Voltage X 1f (V)',
        'Voltage Y 1f (V)',
        'Voltage R 1f (V)',
        'Voltage theta 1f (V)',
        "Voltage DC (V)",           # live: raw value from current sweep
        "Voltage DC Average (V)",
        'Intensity (V)',
        'Intensity STD (V)',   # emitted once at end: clean averaged loop
    ]

    # ── Helpers ───────────────────────────────────────────────────────────────
    def set_sample_name(self, sample_name: str):
        self.sample_name = sample_name

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def startup(self):
        """Reserve hardware, build the field arrays, and initialise accumulators."""
        dac.reserved         = True
        hall_sensor.reserved = True

        proc_config.save_parameters_dict(self.name, self._parameters)

        # Build forward and backward branches separately.
        # forward : b_min → b_max
        # backward: b_max → b_min  (b_max endpoint is not duplicated)
        n_pts = int(np.abs(self.b_max - self.b_min) // self.b_step + 1)
        self.b_forward  = np.linspace(self.b_min, self.b_max, n_pts, endpoint=True)
        self.b_backward = np.flip(self.b_forward).copy()

        n_fwd = len(self.b_forward)
        n_bwd = len(self.b_backward) - 1   # exclude shared b_max endpoint
        n_total = n_fwd + n_bwd

        self._n_fwd   = n_fwd
        self._n_bwd   = n_bwd
        self._n_total = n_total

        # ── Timing budget ────────────────────────────────────────────────────
        # T_point: total wall-clock time available per field step.
        # We use deadline-based sleeping: set the field, do all hardware reads,
        # then sleep only for the remaining portion of T_point.  This means
        # hardware latency is absorbed into the budget rather than added on top.
        self._T_point     = 1.0 / (self.sweep_freq * n_total)
        self._settle_time = max(MIN_SETTLE_S, self._T_point * SETTLE_FRACTION)

        # The DAC acquisition window is whatever is left after settling.
        # It must be at least 1 sample at the chosen sampling rate.
        min_dac_acq = 1.0 / DAC_SAMPLING_RATE
        self._acq_time = max(min_dac_acq, self._T_point * (1.0 - SETTLE_FRACTION))

        # Decide whether the hall sensor can keep up.
        # If T_point < HALL_MIN_ACQ_S we skip live hall reads (use DAC set-point
        # for the live 'Magnetic Field (mT)' column) and only do a slow single
        # hall read per averaged sweep at the end.
        self._hall_live = self._T_point >= HALL_MIN_ACQ_S
        hall_acq = min(self._acq_time, HALL_MIN_ACQ_S) if self._hall_live \
                   else HALL_MIN_ACQ_S
        hall_sensor.set_aquisition_time(hall_acq)

        log.info(
            f"Points per sweep: {n_total} ({n_fwd} fwd + {n_bwd} bwd) | "
            f"T_point: {self._T_point*1e3:.2f} ms | "
            f"Settle: {self._settle_time*1e3:.2f} ms | "
            f"DAC acq: {self._acq_time*1e3:.2f} ms | "
            f"Hall live reads: {self._hall_live}"
        )

        # Metadata
        self.exp_type_md  = "Fast repeated field sweeps with averaging"
        self.sample_md    = self.sample_name
        self.nb_it_md     = n_total
        self.nb_sweeps_md = self.num_sweeps

        # Pre-set field and move stage
        if self.b_min != 0:
            log.info(f"Setting magnetic field to {self.b_min} A, waiting 1 s...")
            dac.set_outputs_and_reset([0.0, 0.0, self.b_min])
            time.sleep(1)

        log.info(f"Moving stage to ({self.x} mm, {self.y} mm)")
        stage.move_x_to(self.x)
        stage.move_y_to(self.y)
        stage.wait_stable()

        dac.setup_aquisition(
            modulation_channel="None",
            frequency=1777.0,
            acquisition_time=self._acq_time,
            sampling_rate=DAC_SAMPLING_RATE,
            modulation_amp=0.0,
        )
        dac.coils_output = self.b_min

        # Separate accumulators for forward and backward branches.
        self._fwd_dc_sum       = np.zeros(n_fwd)
        self._fwd_b_sum        = np.zeros(n_fwd)
        self._fwd_intens_sum   = np.zeros(n_fwd)
        self._bwd_dc_sum       = np.zeros(n_bwd)
        self._bwd_b_sum        = np.zeros(n_bwd)
        self._bwd_intens_sum   = np.zeros(n_bwd)
        self._sweeps_completed = 0

    # ── Inner measurement helper ───────────────────────────────────────────────

    def _measure_point(self, b_set: float, deadline: float):
        """
        Set the field to `b_set`, read DAC + hall sensor, then sleep until
        `deadline` (absolute perf_counter timestamp).

        Returns (voltage_dc, B_mT).  B_mT is NaN when hall live mode is off —
        the caller should substitute the DAC set-point converted to mT if needed
        for display, but NaN is stored so averaging only uses real measurements.
        """
        dac.coils_output = b_set

        # Settle: sleep a fixed fraction, then start hardware tasks
        time.sleep(self._settle_time)

        dac.start_tasks()
        balanced_data, intensity_data = dac.read_data()
        voltage_dc = float(np.mean(balanced_data))
        intensity  = float(np.mean(intensity_data))

        if self._hall_live:
            B_mT = hall_sensor.read_mT()
        else:
            # Too fast for real hall reads — use the DAC set-point as a
            # proxy for the live plot.  Averaged result will use a real read.
            B_mT = float("nan")

        # Burn any remaining budget so the next point starts on time
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

        return voltage_dc, intensity, B_mT

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute(self):
        """
        Perform `num_sweeps` full hysteresis sweeps (forward + backward each time).

        Each point is assigned a hard deadline so the total sweep time matches
        1/sweep_freq regardless of hardware call latency.

        Averaging strategy
        ------------------
        Forward  branch: each set-point averaged over all forward  passes only.
        Backward branch: each set-point averaged over all backward passes only.
        """
        n_fwd    = self._n_fwd
        n_bwd    = self._n_bwd
        T_point  = self._T_point

        x_pos = stage.get_x_pos()
        y_pos = stage.get_y_pos()

        # Conversion factor: DAC Ampere → mT estimate for live display when
        # hall sensor is skipped.  Adjust the constant for your coil geometry.
        # Used ONLY in the live emit; averaged results always use real hall reads.
        A_TO_MT_APPROX = 1000.0   # placeholder — tune to your setup

        # ── Sweep loop ────────────────────────────────────────────────────────
        for sweep_num in range(self.num_sweeps):
            log.info(f"Sweep {sweep_num + 1}/{self.num_sweeps}")

            sweep_fwd_dc     = np.zeros(n_fwd)
            sweep_fwd_b      = np.zeros(n_fwd)
            sweep_fwd_intens = np.zeros(n_fwd)
            sweep_bwd_dc     = np.zeros(n_bwd)
            sweep_bwd_b      = np.zeros(n_bwd)
            sweep_bwd_intens = np.zeros(n_bwd)

            sweep_start = time.perf_counter()

            # ── Forward branch: b_min → b_max ─────────────────────────────
            for i, b_set in enumerate(self.b_forward):
                deadline = sweep_start + (i * T_point)
                voltage_dc, intensity, B_mT = self._measure_point(b_set, deadline)

                sweep_fwd_dc[i]     = voltage_dc
                sweep_fwd_b[i]      = B_mT   # may be NaN in fast mode
                sweep_fwd_intens[i] = intensity

                # For live display: if hall was skipped, show DAC-derived T
                live_T = (B_mT / 1000.0) if self._hall_live else b_set * A_TO_MT_APPROX / 1000.0

                self.emit("results", {
                    "Iteration":              i,
                    "X Position (m)":         x_pos / 1000.0,
                    "Y Position (m)":         y_pos / 1000.0,
                    "Magnetic Field (A)":     b_set,
                    "Magnetic Field (T)":     live_T,
                    "Voltage DC (V)":         voltage_dc,
                    "Voltage DC Average (V)": float("nan"),
                    "Intensity (V)":          intensity,
                    "Intensity STD (V)":      float("nan"),
                })

                if self.should_stop():
                    break

            if self.should_stop():
                break

            # ── Backward branch: b_max → b_min (skip shared b_max point) ──
            for j, b_set in enumerate(self.b_backward[1:]):
                deadline = sweep_start + ((n_fwd + j) * T_point)
                voltage_dc, intensity, B_mT = self._measure_point(b_set, deadline)

                sweep_bwd_dc[j]     = voltage_dc
                sweep_bwd_b[j]      = B_mT   # may be NaN in fast mode
                sweep_bwd_intens[j] = intensity

                live_T = (B_mT / 1000.0) if self._hall_live else b_set * A_TO_MT_APPROX / 1000.0

                self.emit("results", {
                    "Iteration":              n_fwd + j,
                    "X Position (m)":         x_pos / 1000.0,
                    "Y Position (m)":         y_pos / 1000.0,
                    "Magnetic Field (A)":     b_set,
                    "Magnetic Field (T)":     live_T,
                    "Voltage DC (V)":         voltage_dc,
                    "Voltage DC Average (V)": float("nan"),
                    "Intensity (V)":          intensity,
                    "Intensity STD (V)":      float("nan"),
                })

                if self.should_stop():
                    break

            # Accumulate into branch-specific sums.
            # In fast mode sweep_fwd_b / sweep_bwd_b are all NaN — that's
            # intentional; the final averaged emit does a slow real hall read.
            self._fwd_dc_sum     += sweep_fwd_dc
            self._fwd_intens_sum += sweep_fwd_intens
            if self._hall_live:
                self._fwd_b_sum += sweep_fwd_b
                self._bwd_b_sum += sweep_bwd_b
            self._bwd_dc_sum     += sweep_bwd_dc
            self._bwd_intens_sum += sweep_bwd_intens
            self._sweeps_completed += 1

            self.emit("progress", 100 * self._sweeps_completed / self.num_sweeps)

            if self.should_stop():
                break

        # ── Final emit: one clean averaged hysteresis loop ────────────────────
        n = self._sweeps_completed
        log.info(f"Emitting final averaged hysteresis loop ({n} sweeps)...")

        if self._hall_live:
            # _fwd_b_sum / _bwd_b_sum accumulated one reading per sweep, so the
            # per-point mean is the sum divided by the number of sweeps.
            fwd_b_avg = self._fwd_b_sum / n
            bwd_b_avg = self._bwd_b_sum / n
        else:
            # Fast mode: do a single slow hall read at each field set-point
            # now that we're no longer racing the sweep clock.  This gives
            # accurate mT values for the averaged (saved) result.  It is a
            # single measurement, so it must NOT be divided by num_sweeps.
            log.info("Fast mode: performing slow hall reads for averaged result...")
            hall_sensor.set_aquisition_time(HALL_MIN_ACQ_S)

            fwd_b_avg = np.zeros(n_fwd)
            bwd_b_avg = np.zeros(n_bwd)

            for i, b_set in enumerate(self.b_forward):
                dac.coils_output = b_set
                time.sleep(HALL_MIN_ACQ_S * 2)
                fwd_b_avg[i] = hall_sensor.read_mT()

            for j, b_set in enumerate(self.b_backward[1:]):
                dac.coils_output = b_set
                time.sleep(HALL_MIN_ACQ_S * 2)
                bwd_b_avg[j] = hall_sensor.read_mT()

        # Emit forward branch
        for i, b_set in enumerate(self.b_forward):
            self.emit("results", {
                "Iteration":              i,
                "X Position (m)":         x_pos / 1000.0,
                "Y Position (m)":         y_pos / 1000.0,
                "Magnetic Field (A)":     b_set,
                "Magnetic Field (T)":     fwd_b_avg[i] / 1000.0,
                "Voltage DC (V)":         float("nan"),
                "Voltage DC Average (V)": self._fwd_dc_sum[i] / n,
                "Intensity (V)":          float("nan"),
                "Intensity STD (V)":      self._fwd_intens_sum[i] / n,
            })

        # Emit backward branch
        for j, b_set in enumerate(self.b_backward[1:]):
            self.emit("results", {
                "Iteration":              n_fwd + j,
                "X Position (m)":         x_pos / 1000.0,
                "Y Position (m)":         y_pos / 1000.0,
                "Magnetic Field (A)":     b_set,
                "Magnetic Field (T)":     bwd_b_avg[j] / 1000.0,
                "Voltage DC (V)":         float("nan"),
                "Voltage DC Average (V)": self._bwd_dc_sum[j] / n,
                "Intensity (V)":          float("nan"),
                "Intensity STD (V)":      self._bwd_intens_sum[j] / n,
            })

        meas.shutdown()

    def shutdown(self):
        """Return hardware to a safe idle state."""
        log.info("Acquisition done — turning off outputs.")
        dac.set_outputs_and_reset([0.0, 0.0, 0.0])
        hall_sensor.set_aquisition_time(0.5)
        dac.reserved         = False
        hall_sensor.reserved = False