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
from src.classes import proc_config
from src.classes import live_readout


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HALL_MIN_ACQ_S      = 0.002     # minimum hall-sensor acquisition time (2 ms)
DAC_SAMPLING_RATE   = 50_000.0  # samples/s for the DAC ADC acquisition window
SETTLE_TC_MULTIPLES = 5         # number of time-constants to wait after field step
                                 # for the lock-in output to settle (5τ → <1 % error)


class B_Sweep_Lockin(Procedure):
    """
    Hysteresis-loop procedure (B-Sweep) with AC lock-in detection.

    The lock-in's own internal oscillator provides the modulation: it outputs
    ``volt`` at ``lockin_freq`` (driving the sample current through the external
    current source) and demodulates its input at that same reference, so we read
    the already-demodulated outputs (``meas.x/y/mag/theta``) in single reference
    mode, the same reads the X/Y/XY sweeps use.  No DAC modulation and no external
    optical chopper are involved.  Forward and backward branches are accumulated
    separately; the averaged loop is emitted once at the end.
    """
    name = "B-Sweep LockIn"
    DEFAULT_X_AXIS = "Magnetic Field (T)"   # plot x-axis when this tab is open

    # ── Metadata ──────────────────────────────────────────────────────────────
    exp_type_md  = Metadata("Experiment type")
    sample_md    = Metadata("Sample name")
    nb_it_md     = Metadata("Total number of field points per sweep")
    nb_sweeps_md = Metadata("Number of sweeps averaged")
    time_md      = Metadata(
        "Beginning of experiment",
        fget=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
    )

    section = proc_config.get_section(name)

    # ── Field sweep parameters ────────────────────────────────────────────────
    b_min      = FloatParameter(
        "From B",    units="A",
        default=section.get("b_min", -0.5),  minimum=-6, maximum=6,
    )
    b_max      = FloatParameter(
        "To B",      units="A",
        default=section.get("b_max",  0.5),  minimum=-6, maximum=6,
    )
    b_step     = FloatParameter(
        "Step",      units="A",
        default=section.get("b_step", 0.04), minimum=1e-8, maximum=12,
    )
    sweep_freq = FloatParameter(
        "Max sweep frequency", units="Hz",
        default=section.get("sweep_freq", 0.1), minimum=0.001, maximum=10,
    )
    num_sweeps = IntegerParameter(
        "Number of sweeps to average",
        default=section.get("num_sweeps", 5),   minimum=1, maximum=1000,
    )

    # ── Lock-in parameters ─────────────────────────────────────────────────────
    # The lock-in oscillator outputs `volt` at `lockin_freq` (the sample-current
    # modulation) and demodulates its input at that same reference.
    volt         = FloatParameter(
        "Lock-in oscillator amplitude",  units="V",
        default=section.get("volt", 1.0),            minimum=0,     maximum=5,
    )
    sensi        = FloatParameter(
        "Lock-in sensitivity",     units="V",
        default=section.get("sensi", 500e-6),        minimum=1e-9,  maximum=1,
    )
    lockin_freq  = FloatParameter(
        "Lock-in output / reference frequency", units="Hz",
        default=section.get("lockin_freq", 1777),    minimum=1,     maximum=102000,
    )
    time_const   = FloatParameter(
        "Lock-in time constant",   units="s",
        default=section.get("time_const", 0.1),      minimum=10e-6, maximum=100,
    )
    phase        = FloatParameter(
        "Lock-in phase",           units="deg",
        default=section.get("phase", 0),             minimum=-180,  maximum=180,
    )
    acq_time     = FloatParameter(
        "DAC acquisition time",    units="s",
        default=section.get("acq_time", 0.1),        minimum=1e-6,
    )

    # Position parameters (not shown in main input list but stored in data)
    x = FloatParameter("Position x", units="um", default=section.get("x", 0.0))
    y = FloatParameter("Position y", units="um", default=section.get("y", 0.0))

    # ── Output columns ────────────────────────────────────────────────────────
    DATA_COLUMNS = [
        "Iteration",
        "X Position (um)",
        "Y Position (um)",
        "Magnetic Field (A)",
        "Magnetic Field (T)",
        "Voltage X 1f (V)",
        "Voltage Y 1f (V)",
        "Voltage R 1f (V)",
        "Voltage theta 1f (V)",
        "Voltage DC (V)",           # live: DC mean from current sweep
        "Voltage DC Average (V)",   # emitted once at end: averaged DC
        "Voltage X Average (V)",    # emitted once at end: averaged lock-in X (signed)
        "Voltage R Average (V)",    # emitted once at end: averaged lock-in R (magnitude)
        "Intensity (V)",
        "Intensity STD (V)",
        "Loop",                     # loop index — used by the plot to break the line
    ]

    # ── Helpers ───────────────────────────────────────────────────────────────
    def set_sample_name(self, sample_name: str):
        self.sample_name = sample_name

    def queue_validation_error(self):
        """Return a message if, even after lock-in settling, each point would be
        faster than the Hall probe can follow, else None.

        This version already stretches the per-point time to fit the lock-in
        settle (5τ + acquisition), so it only rejects genuinely impossible
        combinations (very small τ / acquisition time at a high sweep frequency).
        """
        try:
            n_pts   = int(np.abs(self.b_max - self.b_min) // self.b_step + 1)
            n_total = n_pts + max(n_pts - 1, 0)
            if n_total < 1:
                return None
            settle_s = SETTLE_TC_MULTIPLES * self.time_const
            t_point  = max(settle_s + self.acq_time, 1.0 / (self.sweep_freq * n_total))
            if t_point < HALL_MIN_ACQ_S:
                return (
                    f"Even after lock-in settling, each point would take "
                    f"{t_point * 1e3:.2g} ms — below the {HALL_MIN_ACQ_S * 1e3:g} ms the "
                    f"Hall probe needs.\n\nLower the sweep frequency, increase the field "
                    f"step, or increase the acquisition time / time constant."
                )
        except Exception:
            return None
        return None

    # ── Startup ───────────────────────────────────────────────────────────────
    def startup(self):
        """Reserve hardware, configure lock-in, build field arrays, initialise accumulators."""
        dac.reserved         = True
        hall_sensor.reserved = True

        proc_config.save_parameters_dict(self.name, self._parameters)

        # ── Build field arrays ────────────────────────────────────────────────
        n_pts       = int(np.abs(self.b_max - self.b_min) // self.b_step + 1)
        self.b_forward  = np.linspace(self.b_min, self.b_max, n_pts, endpoint=True)
        self.b_backward = np.flip(self.b_forward).copy()

        n_fwd   = len(self.b_forward)
        n_bwd   = len(self.b_backward) - 1   # exclude shared b_max endpoint
        n_total = n_fwd + n_bwd

        self._n_fwd   = n_fwd
        self._n_bwd   = n_bwd
        self._n_total = n_total

        # ── Timing ───────────────────────────────────────────────────────────
        # Minimum time per point imposed by lock-in settling + DAC acquisition.
        # This is the hard floor: the lock-in output is meaningless before it.
        settle_s          = SETTLE_TC_MULTIPLES * self.time_const
        self._min_t_point = settle_s + self.acq_time

        # Requested time per point from sweep_freq ceiling
        T_point_requested = 1.0 / (self.sweep_freq * n_total)

        if T_point_requested < self._min_t_point:
            log.warning(
                f"sweep_freq={self.sweep_freq} Hz gives T_point={T_point_requested*1e3:.1f} ms, "
                f"which is shorter than the required lock-in settle+acq time "
                f"({self._min_t_point*1e3:.1f} ms = {SETTLE_TC_MULTIPLES}×τ + acq). "
                f"T_point extended to {self._min_t_point*1e3:.1f} ms automatically."
            )
            self._T_point = self._min_t_point
        else:
            self._T_point = T_point_requested

        # Hall sensor mode
        self._hall_live = self._T_point >= HALL_MIN_ACQ_S
        hall_acq = min(self.acq_time, HALL_MIN_ACQ_S) if self._hall_live else HALL_MIN_ACQ_S
        hall_sensor.set_aquisition_time(hall_acq)

        log.info(
            f"B-Sweep LockIn | Points: {n_total} ({n_fwd} fwd + {n_bwd} bwd) | "
            f"T_point: {self._T_point*1e3:.1f} ms | "
            f"Settle ({SETTLE_TC_MULTIPLES}×τ): {settle_s*1e3:.1f} ms | "
            f"DAC acq: {self.acq_time*1e3:.1f} ms | "
            f"Hall live: {self._hall_live}"
        )

        # ── Metadata ─────────────────────────────────────────────────────────
        self.exp_type_md  = "Hysteresis loop — AC lock-in (lock-in oscillator)"
        self.sample_md    = self.sample_name
        self.nb_it_md     = n_total
        self.nb_sweeps_md = self.num_sweeps

        # ── Configure lock-in amplifier ───────────────────────────────────────
        # The lock-in oscillator itself provides the modulation: it outputs
        # `volt` at `lockin_freq` (driving the sample current) and demodulates
        # its input at that same reference.  Single reference mode (REFMODE 0):
        # one demodulator at the modulation frequency, read as meas.x/y/mag/theta.
        # We deliberately avoid the dual-harmonic mode (REFMODE 1): its second
        # demodulator (2f) is unused here and would overload on the MOKE signal,
        # injecting spikes.  Set explicitly so the run never depends on whatever
        # mode the instrument was last left in.
        dsp.set_reference_mode(0)
        dsp.setup_lockin_condition(
            lockin_voltage       = self.volt,
            lockin_sensitivity   = self.sensi,
            lockin_frequency     = self.lockin_freq,
            lockin_time_constant = self.time_const,
            lockin_phase         = self.phase,
        )
        log.info(
            f"Lock-in configured (single reference): f={self.lockin_freq} Hz, "
            f"sensi={self.sensi*1e6:.1f} µV, τ={self.time_const*1e3:.1f} ms, "
            f"phase={self.phase}°"
        )

        # ── Configure DAC (no modulation — field + ADC acquisition only) ───────
        # The DAC does not generate any modulation; it only drives the coil
        # current (field) and opens the ADC window to sample the diode signals.
        dac.setup_aquisition(
            modulation_channel = "None",
            frequency          = self.lockin_freq,   # for the reference-signal arrays
            acquisition_time   = self.acq_time,
            sampling_rate      = DAC_SAMPLING_RATE,
            modulation_amp     = 0.0,
        )

        # ── Stage and initial field ───────────────────────────────────────────
        if self.b_min != 0:
            log.info(f"Setting magnetic field to {self.b_min} A, waiting 1 s...")
            dac.set_outputs_and_reset([0.0, 0.0, self.b_min])
            time.sleep(1)

        log.info(f"Moving stage to ({self.x} um, {self.y} um)")
        stage.move_x_to(self.x / 1000.0)   # µm (param) -> mm (stage)
        stage.move_y_to(self.y / 1000.0)
        stage.wait_stable()

        dac.coils_output = self.b_min

        # ── Accumulators (forward / backward, separate) ───────────────────────
        self._fwd_dc_sum = np.zeros(n_fwd)
        self._fwd_x_sum  = np.zeros(n_fwd)   # signed lock-in X (the hysteresis loop)
        self._fwd_r_sum  = np.zeros(n_fwd)   # lock-in R (magnitude)
        self._fwd_b_sum  = np.zeros(n_fwd)
        self._bwd_dc_sum = np.zeros(n_bwd)
        self._bwd_x_sum  = np.zeros(n_bwd)
        self._bwd_r_sum  = np.zeros(n_bwd)
        self._bwd_b_sum  = np.zeros(n_bwd)
        self._sweeps_completed = 0

    # ── Inner measurement helper ───────────────────────────────────────────────

    def _measure_point(self, b_set: float, deadline: float):
        """
        Set coil current to `b_set`, wait for lock-in to settle, read lock-in
        X/Y/R/θ plus DAC DC/intensity channels.  Sleep until `deadline`.

        The lock-in must settle for SETTLE_TC_MULTIPLES × time_const after the
        field (and hence the MOKE signal) changes; the DAC acquisition window
        then runs concurrently with the (non-blocking) lock-in reads.

        Returns
        -------
        lockin_x, lockin_y, lockin_r, lockin_theta : float
            Lock-in quadrature components and polar form.
        voltage_dc : float
            DC mean of balanced-diode ADC channel.
        intensity  : float
            Mean of intensity-diode ADC channel.
        intensity_std : float
            Std  of intensity-diode ADC channel.
        B_mT : float
            Hall sensor reading in mT, or NaN in fast mode.
        """
        # Step the field
        dac.coils_output = b_set

        # Wait for the lock-in output to settle after the MOKE signal has changed.
        # This is the dominant time per point at typical lock-in time constants.
        settle_s = SETTLE_TC_MULTIPLES * self.time_const
        time.sleep(settle_s)

        # Start the DAC acquisition window and simultaneously read the lock-in.
        # dac.start_tasks() is non-blocking until dac.read_data() is called,
        # so the lock-in reads happen in parallel with the DAC sampling window.
        dac.start_tasks()

        # Read the lock-in's demodulated outputs (X./Y./MAG./PHA.) — single
        # reference mode, set in startup() — the same reads the X/Y/XY sweeps use.
        lockin_x     = meas.x
        lockin_y     = meas.y
        lockin_r     = meas.mag
        lockin_theta = meas.theta

        # Wait for DAC acquisition to finish and collect ADC data
        balanced_data, intensity_data = dac.read_data()
        voltage_dc    = float(np.mean(balanced_data))
        intensity     = float(np.mean(intensity_data))
        intensity_std = float(np.std(intensity_data))

        # Hall sensor read
        if self._hall_live:
            B_mT = hall_sensor.read_mT()
        else:
            B_mT = float("nan")

        # Keep the Live tab cards updating from this running scan.
        live_readout.push(voltage_dc, intensity, B_mT)

        # Sleep any remaining budget so the sweep stays on schedule
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

        return lockin_x, lockin_y, lockin_r, lockin_theta, voltage_dc, intensity, intensity_std, B_mT

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute(self):
        """
        Perform `num_sweeps` full hysteresis loops (forward + backward each time).

        Each point reads the lock-in X/Y/R/θ as the primary MOKE signal.
        Averaging is performed branch-by-branch (forward and backward separately)
        so that field direction is never mixed in the average.
        """
        n_fwd   = self._n_fwd
        n_bwd   = self._n_bwd
        T_point = self._T_point

        x_pos = stage.get_x_pos() * 1000.0   # mm (stage) -> µm (data column)
        y_pos = stage.get_y_pos() * 1000.0

        A_TO_MT_APPROX = 1000.0   # placeholder for fast-mode live display

        for sweep_num in range(self.num_sweeps):
            log.info(f"Sweep {sweep_num + 1}/{self.num_sweeps}")

            sweep_fwd_dc = np.zeros(n_fwd)
            sweep_fwd_x  = np.zeros(n_fwd)
            sweep_fwd_r  = np.zeros(n_fwd)
            sweep_fwd_b  = np.zeros(n_fwd)
            sweep_bwd_dc = np.zeros(n_bwd)
            sweep_bwd_x  = np.zeros(n_bwd)
            sweep_bwd_r  = np.zeros(n_bwd)
            sweep_bwd_b  = np.zeros(n_bwd)

            sweep_start = time.perf_counter()

            # ── Forward branch: b_min → b_max ─────────────────────────────────
            for i, b_set in enumerate(self.b_forward):
                deadline = sweep_start + (i * T_point)
                (lx, ly, lr, lt,
                 vdc, inten, inten_std, B_mT) = self._measure_point(b_set, deadline)

                sweep_fwd_dc[i] = vdc
                sweep_fwd_x[i]  = lx
                sweep_fwd_r[i]  = lr
                sweep_fwd_b[i]  = B_mT   # may be NaN in fast mode

                live_T = (B_mT / 1000.0) if self._hall_live else b_set * A_TO_MT_APPROX / 1000.0

                self.emit("results", {
                    "Iteration":              i,
                    "X Position (um)":        x_pos,
                    "Y Position (um)":        y_pos,
                    "Magnetic Field (A)":     b_set,
                    "Magnetic Field (T)":     live_T,
                    "Voltage X 1f (V)":       lx,
                    "Voltage Y 1f (V)":       ly,
                    "Voltage R 1f (V)":       lr,
                    "Voltage theta 1f (V)":   lt,
                    "Voltage DC (V)":         vdc,
                    "Voltage DC Average (V)": float("nan"),
                    "Voltage X Average (V)":  float("nan"),
                    "Voltage R Average (V)":  float("nan"),
                    "Intensity (V)":          inten,
                    "Intensity STD (V)":      inten_std,
                    "Loop":                   sweep_num,
                })

                if self.should_stop():
                    break

            if self.should_stop():
                break

            # ── Backward branch: b_max → b_min (skip shared b_max point) ──────
            for j, b_set in enumerate(self.b_backward[1:]):
                deadline = sweep_start + ((n_fwd + j) * T_point)
                (lx, ly, lr, lt,
                 vdc, inten, inten_std, B_mT) = self._measure_point(b_set, deadline)

                sweep_bwd_dc[j] = vdc
                sweep_bwd_x[j]  = lx
                sweep_bwd_r[j]  = lr
                sweep_bwd_b[j]  = B_mT

                live_T = (B_mT / 1000.0) if self._hall_live else b_set * A_TO_MT_APPROX / 1000.0

                self.emit("results", {
                    "Iteration":              n_fwd + j,
                    "X Position (um)":        x_pos,
                    "Y Position (um)":        y_pos,
                    "Magnetic Field (A)":     b_set,
                    "Magnetic Field (T)":     live_T,
                    "Voltage X 1f (V)":       lx,
                    "Voltage Y 1f (V)":       ly,
                    "Voltage R 1f (V)":       lr,
                    "Voltage theta 1f (V)":   lt,
                    "Voltage DC (V)":         vdc,
                    "Voltage DC Average (V)": float("nan"),
                    "Voltage X Average (V)":  float("nan"),
                    "Voltage R Average (V)":  float("nan"),
                    "Intensity (V)":          inten,
                    "Intensity STD (V)":      inten_std,
                    "Loop":                   sweep_num,
                })

                if self.should_stop():
                    break

            # Accumulate branch sums
            self._fwd_dc_sum += sweep_fwd_dc
            self._fwd_x_sum  += sweep_fwd_x
            self._fwd_r_sum  += sweep_fwd_r
            self._bwd_dc_sum += sweep_bwd_dc
            self._bwd_x_sum  += sweep_bwd_x
            self._bwd_r_sum  += sweep_bwd_r
            if self._hall_live:
                self._fwd_b_sum += sweep_fwd_b
                self._bwd_b_sum += sweep_bwd_b
            self._sweeps_completed += 1

            self.emit("progress", 100 * self._sweeps_completed / self.num_sweeps)

            if self.should_stop():
                break

        # If the run was aborted, skip the (potentially long) post-processing and
        # averaged emit so the abort returns promptly instead of grinding through
        # every field point first.  This also avoids dividing by zero when the
        # abort happens before a single sweep completes.
        if self.should_stop():
            log.info("Aborted — skipping final averaged hysteresis loop.")
            meas.shutdown()
            return

        # ── Final emit: averaged hysteresis loop ──────────────────────────────
        n = self._sweeps_completed
        log.info(f"Emitting final averaged hysteresis loop ({n} sweeps)...")

        if self._hall_live:
            # _fwd_b_sum / _bwd_b_sum accumulated one reading per sweep, so the
            # per-point mean is the sum divided by the number of sweeps.
            fwd_b_avg = self._fwd_b_sum / n
            bwd_b_avg = self._bwd_b_sum / n
        else:
            # Fast mode: collect one slow hall read per set-point now that we're
            # off the sweep clock.  It is a single measurement, so it must NOT
            # be divided by num_sweeps.
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
                "X Position (um)":        x_pos,
                "Y Position (um)":        y_pos,
                "Magnetic Field (A)":     b_set,
                "Magnetic Field (T)":     fwd_b_avg[i] / 1000.0,
                "Voltage X 1f (V)":       float("nan"),
                "Voltage Y 1f (V)":       float("nan"),
                "Voltage R 1f (V)":       float("nan"),
                "Voltage theta 1f (V)":   float("nan"),
                "Voltage DC (V)":         float("nan"),
                "Voltage DC Average (V)": self._fwd_dc_sum[i] / n,
                "Voltage X Average (V)":  self._fwd_x_sum[i]  / n,
                "Voltage R Average (V)":  self._fwd_r_sum[i]  / n,
                "Intensity (V)":          float("nan"),
                "Intensity STD (V)":      float("nan"),
                "Loop":                   self.num_sweeps,   # averaged loop = own line
            })

        # Emit backward branch
        for j, b_set in enumerate(self.b_backward[1:]):
            self.emit("results", {
                "Iteration":              n_fwd + j,
                "X Position (um)":        x_pos,
                "Y Position (um)":        y_pos,
                "Magnetic Field (A)":     b_set,
                "Magnetic Field (T)":     bwd_b_avg[j] / 1000.0,
                "Voltage X 1f (V)":       float("nan"),
                "Voltage Y 1f (V)":       float("nan"),
                "Voltage R 1f (V)":       float("nan"),
                "Voltage theta 1f (V)":   float("nan"),
                "Voltage DC (V)":         float("nan"),
                "Voltage DC Average (V)": self._bwd_dc_sum[j] / n,
                "Voltage X Average (V)":  self._bwd_x_sum[j]  / n,
                "Voltage R Average (V)":  self._bwd_r_sum[j]  / n,
                "Intensity (V)":          float("nan"),
                "Intensity STD (V)":      float("nan"),
                "Loop":                   self.num_sweeps,   # averaged loop = own line
            })

        meas.shutdown()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self):
        """Return hardware to a safe idle state."""
        log.info("Acquisition done — turning off outputs.")
        try:
            dac.set_outputs_and_reset([0.0, 0.0, 0.0])
            hall_sensor.set_aquisition_time(0.5)
        finally:
            # Always release the hardware so the live tab resumes, even if a
            # teardown call above raised.
            dac.reserved         = False
            hall_sensor.reserved = False