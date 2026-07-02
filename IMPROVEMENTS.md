# Future improvements (acquisition & instrumentation)

A short, honest backlog of technical improvements discussed during the
bug-fix pass. Items here are **deferred by choice** — they are not bugs, and the
software works without them. Each notes *why* it's deferred so the context isn't
lost.

## Done in this pass
- **B-Sweep LockIn uses the current-modulation scheme (not a chopper).** The
  lock-in hysteresis loop now configures the DAC modulation and reads the lock-in
  first-harmonic outputs (dual-harmonic reference mode, `meas.x1/y1/mag1/theta1`)
  exactly like the X/Y/XY sweeps, instead of assuming an external optical chopper
  (single reference mode + AQN auto-phase). It also averages the **signed** X
  (`Voltage X Average (V)`) in addition to R — R is a magnitude and can't show a
  hysteresis loop's sign flip, so averaging only R was wrong for a loop. (The
  file is still named `b_sweep_chopper.py`; only the behaviour changed.)
- **Positions are in micrometres.** All X/Y position parameters (scan
  start/stop/step and the fixed spot position), the recorded position columns
  (`X/Y Position (um)`), and the plot/2D-map axes are now micrometres — the
  natural unit for this setup's µm-scale moves. The stages are still commanded in
  millimetres; conversion happens only at the hardware boundary (helpers in
  `position_sweep.py`). Old data files (`… (mm)` / `… (m)` columns) are converted
  on open, and the stored config values were migrated ×1000.
- **2D colour map for the XY grid scan.** The results panel gained a "2D Map"
  tab (pymeasure `ImageWidget`) that renders the XY grid as a colour map instead
  of overlapping line traces. The `XY_Sweep` exposes the grid extent
  (`X/Y Position (um)_start/_end/_step`, in micrometres) that `ResultsImage`
  reads; the step is the *actual* linspace spacing (`span/(N-1)`), so every image
  cell lines up with a scan point even when the requested step doesn't divide the
  range evenly. The colour (z) axis is user-selectable (defaults to
  `Voltage DC (V)`). Line and map update live side by side; procedures that are
  not a grid (B/X/Y/Time) contribute no image curve and leave the map empty.
- **Single lock-in session.** `meas` and `dsp` now refer to one `Ametek7270`
  instance (was two VISA sessions to the same instrument).
- **Explicit lock-in reference mode.** X/Y/XY sweeps select dual-harmonic mode
  in `startup()` before reading `x1/y1/mag1/theta1`, so a run no longer depends
  on whatever mode the instrument was last left in.
- **De-duplicated the X/Y/XY sweep procedures.** The shared logic (hardware
  setup, per-point measurement, the sweep loop and teardown) now lives once in
  `src/procedures/position_sweep.py::PositionSweep`. Each procedure is reduced to
  its parameters/metadata plus a small `_configure_scan()` that builds an ordered
  list of `(x, y, field, iteration)` points; the base walks it. Visit order and
  saved columns are unchanged (locked by `test_sweep_visit_order_preserved`).
  This removes the copy-paste drift that let the XY-only progress bug exist.

## Deferred — hardware-dependent
- **Continuous field ramp + streaming acquisition.**
  Replacing the step-and-settle staircase with a continuously clocked triangle
  field ramp and a streamed AI acquisition would give faster, smoother
  hysteresis loops with no per-point settle dead-time.
  *Blocked by hardware:* the Hall probe is currently read over **USB**, not the
  DAQ card, so the field readback and the streamed samples cannot be
  time-aligned (the USB latency mismatch is too large). Revisit once the Hall
  probe is wired to the DAQ via **BNC** — then the field can be sampled on the
  same clock as the diode signal and binned/aligned exactly. Until then,
  ramp-and-wait is the correct choice.

## Deferred — considered and declined
- **Intensity normalization (balanced ÷ intensity).** Declined: for this
  balanced detector the intensity diode mainly tracks spot size/defocus rather
  than common-mode laser power, so dividing by it would not cleanly reject
  power drift (and could add noise) until defocus becomes large.
- **Software (digital) lock-in.** Declined: AC measurements use the hardware
  Ametek 7270, and DC loops run with no modulation, so an in-software
  demodulator isn't needed. (The unused, result-discarded demodulation that used
  to run every point in X/Y/XY was removed.)
- **Raw-waveform saving.** Declined: not needed for the current workflow.

## Optional, low-risk (not yet done)
- **NPLC (mains-cycle) DC averaging.** Snapping the per-point acquisition window
  to an integer number of 50 Hz line cycles (multiples of 20 ms) makes mains
  pickup average to ~zero. Trade-off: it imposes a ≥20 ms/point floor, which
  conflicts with fast DC sweeps — so it's best offered as an opt-in for careful,
  slow measurements rather than always on.
- **Per-point error handling.** Record `NaN` and continue on a transient
  instrument read error instead of aborting the whole sweep.
- **Faster lock-in readout.** Reading `x1,y1,mag1,theta1` is four VISA queries
  per point; the 7270 can return several values per command, or its internal
  curve buffer can be armed once and dumped at the end of a sweep.
