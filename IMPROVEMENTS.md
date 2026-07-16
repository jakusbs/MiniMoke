# Future improvements (acquisition & instrumentation)

A short, honest backlog of technical improvements discussed during the
bug-fix pass. Items here are **deferred by choice** — they are not bugs, and the
software works without them. Each notes *why* it's deferred so the context isn't
lost.

## Done in this pass
- **Pause/Continue for running sweeps; hardware errors pause instead of
  killing the run.** A new Pause button (between Queue and Abort) holds the
  running sweep after the current point — position, field and outputs stay in
  place — and Continue resumes it; Abort still works while paused. The same
  gate arms automatically: when a device drops out mid-run (DAQ USB unplugged,
  lock-in Ethernet adapter disconnected and its reconnect ladder exhausted),
  the run now PAUSES with a clear log message instead of failing — fix the
  cable, press Continue, and the *same point* is retried after a best-effort
  hardware re-init (the DAQ tasks are rebuilt, the field re-asserted; the
  lock-in recovers via its own reconnect ladder). Nothing measured is lost.
  Applies to X/Y/XY, Time (whose time axis keeps honest gaps while the
  sampling interval resumes cleanly) and the AC B-sweep (whose per-point
  schedule shifts by the pause). The DC B-sweep's fast hardware-timed loops
  can't pause point-wise and keep their abort-on-error behaviour.
- **Acquisition windows longer than 10 s no longer time out; per-point settle
  time.** nidaqmx defaults every `wait_until_done`/`read` timeout to 10 s, so an
  integration (acquisition) time above 10 s crashed the point — the DAC now
  passes `acquisition_time + 10 s` to the driver instead. And the position
  sweeps (X/Y/XY) gained a **"Settle time after move"** parameter (default 0 —
  no behaviour change): an optional pause between the stage move and the
  acquisition, so vibrations die out and the lock-in output (time constant)
  settles at the new spot before the integration window opens.
- **Lock-in "Ethernet refresh": auto-revive at run start, spare-port fallback,
  clean disconnect on exit.** The 7270 accepts one Ethernet client per port; a
  crashed session can leave its dead connection occupying port 50000, and the
  next app launch then silently fell back to the offline stub (all-zero
  channels) until the instrument was power-cycled — operationally no better
  than USB. Three changes remove the power-cycle from the loop: (1) every AC
  run start calls `try_revive_lockin()` — if the app is on the offline stub it
  attempts a real connection and, on success, swaps the live driver in
  everywhere, so recovery needs no app restart; (2) when a socket connect to
  port 50000 is refused, the revive retries on the 7270's second command port
  50001, which usually accepts even while a stale connection holds the primary;
  (3) closing the app now closes the VISA session deliberately (clean TCP FIN),
  so the instrument frees its slot and stale held sockets stop accumulating.
- **Ethernet socket framing auto-sync (and stale-response flush).** The first
  Ethernet run (2026-07-15) desynchronised immediately: the 7270's socket
  interface appends a status-prompt chunk to every response that its USB
  interface doesn't send. Unread, each command left one chunk behind, shifting
  all later reads — property sets failed with "Incorrect return from previously
  set property" on alternating commands, and the first `XY.` read got an empty
  string (run 1) / a single foreign token (run 2). The driver now runs
  `_sync_protocol()` at connect and after every reconnect: with a short read
  timeout it flushes any queued backlog (also covers stale responses a crashed
  run leaves behind on USB), sends one `ID` probe, counts the response chunks,
  and thereafter drains the extra chunk(s) after every transaction (`ask` and
  `check_set_errors`). USB behaviour is unchanged (probe finds one chunk); the
  socket interface stays response-aligned indefinitely.
- **Batched lock-in readout: one transaction per point instead of four.** Every
  measured point used to issue four separate queries (`X.`, `Y.`, `MAG.`,
  `PHA.`) — four USB round-trips, four chances per point for the link to glitch
  (the 2026-07-11 crash died on `MAG.`, the third of the burst). All procedures
  now read one `XY.` batch query and derive R/θ from that same sample — which is
  exactly what the instrument's `MAG.`/`PHA.` outputs are internally, with the
  bonus that all four recorded values now describe the *same* instant rather
  than four slightly different ones. Columns and their meaning are unchanged.
  (The deeper batching — arming the 7270's internal curve buffer and streaming
  it out at the end of a sweep — remains a future idea; it doesn't fit the
  per-point DAC acquisition windows.)
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
  the program to run as Administrator (logged clearly when refused). Field
  evidence supports this route: PC restarts (which bus-reset every USB device at
  boot, without ever cutting the self-powered instrument's power) have revived
  the link — but sometimes only after several restarts, so the ladder attempts
  up to four targeted resets (six reconnect attempts total, ~2–3 min worst case
  before the run is declared failed). When all
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
- **Streaming lock-in readout (curve buffer).** The per-point readout is now a
  single `XY.` transaction (see Done); the remaining idea is arming the 7270's
  internal curve buffer once and dumping it at the end of a sweep — only worth
  it if the per-point DAC acquisition window is ever replaced by a streamed
  acquisition.
