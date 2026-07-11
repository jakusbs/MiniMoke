# Future improvements (acquisition & instrumentation)

A short, honest backlog of technical improvements discussed during the
bug-fix pass. Items here are **deferred by choice** — they are not bugs, and the
software works without them. Each notes *why* it's deferred so the context isn't
lost.

## Done in this pass
- **Bus-level USB reset when the lock-in interface hard-hangs; Ethernet as a
  config option.** The 2026-07-11 overnight crash showed the limit of
  session-level recovery: after the device clear the *write* went through but
  the instrument never answered (read timeout), and it stayed dead for 10 hours
  — with USB power management already disabled, that points at a hard interface
  hang (EMI from the coil switching, or the 7270's USB firmware). Two additions:
  (1) from reconnect attempt 3 on, the retry ladder re-enumerates the USB device
  with `pnputil /restart-device <instance-from-VISA-resource>` — the software
  equivalent of replugging the cable, which forces the instrument to
  re-initialise its USB stack. Windows-only, touches only the 7270, and needs
  the program to run as Administrator (logged clearly when refused). When all
  recovery fails, the log now says exactly what to do (power-cycle / replug /
  consider Ethernet). (2) The lock-in VISA resource is now read from
  `configs/instruments_config.ini`, so the 7270 can be switched to its
  **Ethernet interface** (`TCPIP0::<ip>::50000::SOCKET`, same null-terminated
  protocol) with a one-line config edit — Ethernet sidesteps the whole USB
  hang/EMI class of problem.
- **A crashed run now resets the window and archives its partial data.** pymeasure
  emits `failed` (never `finished`) when a worker crashes, but the window only
  connected `finished` — so after an overnight crash the Abort button stayed
  armed (clicking it raised "Attempting to abort when no experiment is running")
  and `_archive_experiment` never ran, so the partial data that pymeasure had
  been streaming to the local CSV all along never got its server copy or
  lab-notebook row. `manager.failed` is now handled like `finished` (controls
  reset + archive), and clicking Abort when nothing is running quietly resets
  the button instead of logging an ERROR traceback.
- **Lock-in auto-reconnect (survives a USB drop/wedge mid-run).** When Windows
  suspends the USB device, the link drops, or an EMI glitch (e.g. the field coils
  switching) interrupts a command, the VISA session dies or the instrument wedges
  and reads throw NI-VISA/USB errors that abort the measurement. `Ametek7270.ask`
  now catches any I/O error, re-opens the VISA session **and issues a VISA device
  clear** (`reconnect()` — close + re-open to the same resource + `viClear`,
  keeping the instrument's settings), then retries — a few times with a
  progressively longer settle, since a power-suspended device can take several
  seconds (and more than one attempt) to wake. The device clear is the key part:
  field logs showed the session re-opening successfully yet the *next write still
  timing out*, because a fresh session alone doesn't flush a stuck USB
  buffer/parser — a `viClear` does. Every read goes through `ask` (measurement
  properties use `values` → `ask`), so per-point reads and commands are all
  covered; a transient disconnect/wedge recovers and the sweep continues instead
  of crashing. The underlying cause is best removed at the source: disable USB
  selective suspend / "allow the computer to turn off this device" in Windows,
  use a shielded USB cable with a ferrite and keep it away from the coil leads,
  and (if available) prefer GPIB/RS232 over USB for EMI immunity.
- **Lab notebook no longer shifts columns; clearer save errors.** The notebook
  header is written only when the file is new, so when a new column (`Setup`) was
  inserted into `LAB_NOTEBOOK_COLUMNS`, older files kept their old header and
  every later row shifted one column right. Appends now align to the file's *own*
  header, so a schema change can never shift an existing notebook (start a fresh
  notebook to pick up new columns). Also: the data-file save is wrapped so a
  permission/disk error shows a clear dialog instead of crashing the queue, the
  notebook/server warnings hint at the usual cause (file open in Excel), and an
  unmounted server drive is reported once ("server not reachable — saved locally
  only") instead of three cryptic `WinError 3`s.
- **Single reference mode (no more demod2 overload/spikes).** The AC lock-in
  measurements (X/Y/XY, AC B-sweep, Time) were using the 7270's dual-harmonic
  mode (`REFMODE 1`) and reading `meas.x1/…`. That runs a *second* demodulator at
  2f which we never use — it was overloading (~300 %) and injecting spikes, and a
  wedged instrument from that overload was making the next run's first command
  (`set_reference_mode`) time out over USB. Switched to single reference mode
  (`REFMODE 0`) reading `meas.x/y/mag/theta` (the fundamental at the modulation
  frequency, same physical quantity), so demod2 is gone. (Comms glitches after an
  overload are now handled by the lock-in auto-reconnect above.)
- **All AC measurements modulate from the lock-in oscillator (no DAC modulation).**
  The X/Y/XY position sweeps used to also program a DAC sine modulation
  (`demod`/`freq`/`mod_amp`), on top of the lock-in oscillator. That was redundant
  — the sample current is driven by the lock-in oscillator (`volt` at
  `lockin_freq`), the same way the Time measurement and the AC B-sweep already
  work — so the DAC modulation was removed and those parameters dropped. The
  `volt` control (which maps to the instrument's `OA.` oscillator-amplitude
  command) is relabelled **"Lock-in oscillator amplitude"** everywhere so it's
  clear it sets the current-drive amplitude.
- **B-Sweep LockIn uses AC lock-in detection (not a chopper).** The lock-in
  hysteresis loop now drives the modulation from the lock-in's own oscillator
  (`volt` at `lockin_freq`, driving the sample current) and reads the
  already-demodulated first-harmonic outputs in dual-harmonic reference mode
  (`meas.x1/y1/mag1/theta1`) — the same reads the X/Y/XY sweeps use. It no longer
  assumes an external optical chopper (single reference mode + AQN auto-phase) and
  generates **no** DAC modulation (the DAC only drives the field and opens the ADC
  window). It also averages the **signed** X (`Voltage X Average (V)`) in addition
  to R — R is a magnitude and can't show a hysteresis loop's sign flip, so
  averaging only R was wrong for a loop. The file was renamed
  `b_sweep_chopper.py` → `b_sweep_ac.py`.
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
  The XY scan itself is a **single-pass serpentine raster** at a fixed field:
  one measurement per grid point (it used to inherit the 1D sweeps' `+b/-b`
  doubling and scan every column twice), snaking in y so the stage never flies
  back to `y_min` between columns. `repeat_num` now repeats the whole map and
  defaults to 1.
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
