"""
Description:
    This file defines a DAC class for signal generation and acquisition.
    This class interfaces the National Instruments DAQ card using the nidaqmx library.

    Performance note
    ----------------
    The original design created a new nidaqmx.Task() for the PFI0 trigger on every
    single measurement point (~10–50 ms Windows kernel overhead each time) and also
    called output.stop() / input.stop() between every point.  At high sweep
    frequencies this was the dominant bottleneck — the sweep could never go faster
    than ~20–100 points/s regardless of acquisition_time.

    The fix: a single persistent trigger task (_trigger_task) is created once in
    setup_dac() and reused for every fire_trigger() call.  stop/start calls are
    also eliminated from the hot path — tasks are only stopped in read_data() and
    only when necessary.
"""

import nidaqmx
import numpy as np
from scipy.signal import butter, filtfilt

from src.classes import dac_config


class DAC:
    def __init__(self) -> None:
        self.reserved       = False
        self.status_setup   = False
        self.enabled        = False
        self.dc_output      = [0., 0.]
        self.coils_output   = 0.
        self._trigger_task  = None      # persistent — created once, never recreated
        self._output_values = None      # pre-allocated output buffer
        self.setup_dac()

    def __del__(self) -> None:
        if not self.enabled:
            return
        self._close_trigger_task()
        self.output.close()
        self.input.close()

    # ── Trigger task (persistent) ─────────────────────────────────────────────

    def _open_trigger_task(self) -> None:
        """Create the PFI0 trigger task once.  Call from setup_dac only."""
        if self._trigger_task is not None:
            return
        self._trigger_task = nidaqmx.Task('TriggerTask')
        self._trigger_task.do_channels.add_do_chan("/Dev1/PFI0")

    def _close_trigger_task(self) -> None:
        if self._trigger_task is not None:
            try:
                self._trigger_task.stop()
                self._trigger_task.close()
            except Exception:
                pass
            self._trigger_task = None

    def fire_trigger(self) -> None:
        """
        Fire a single rising edge on PFI0 to start the hardware-triggered tasks.
        Reuses the persistent task — no Task() construction overhead.
        """
        if self._trigger_task is None:
            return
        self._trigger_task.write([True, False], auto_start=True)
        self._trigger_task.stop()   # stop the DO task so it can be rewritten next call

    # ── Acquisition setup ─────────────────────────────────────────────────────

    def setup_aquisition(self, modulation_channel='None', frequency=431,
                         sampling_rate=50000, acquisition_time=0.5,
                         modulation_amp=1.) -> None:
        self.f              = frequency
        self.sampling_rate  = sampling_rate
        self.modulation_amp = modulation_amp

        if modulation_channel != 'None':
            self.mod_chan = modulation_channel.split("(")[0].strip()
            self.set_acquisition_time(acquisition_time)
        else:
            self.mod_chan = None
            self.acquisition_time = acquisition_time

        if not self.enabled:
            return

        self.reset_tasks()
        print(f"Currently using {self.mod_chan} as the modulation channel")

        self.create_signals()

        n_samps = len(self.reference_signal_1f[0]) + 1
        self.output.timing.cfg_samp_clk_timing(sampling_rate, samps_per_chan=n_samps)
        self.input.timing.cfg_samp_clk_timing( sampling_rate, samps_per_chan=n_samps)

        # Pre-allocate the output buffer once — we only patch coils_output per point
        self._build_output_buffer()

        self.status_setup = True

    def set_acquisition_time(self, acquisition_time) -> None:
        """Snap acquisition_time to an integer number of reference periods."""
        N_periods = round(acquisition_time * self.f)
        self.acquisition_time = N_periods / self.f

    def create_signals(self) -> None:
        t = np.linspace(0, self.acquisition_time,
                        round(self.sampling_rate * self.acquisition_time),
                        endpoint=False)

        self.reference_signal_1f = [
            np.sin(2 * np.pi * self.f * t),
            np.sin(2 * np.pi * self.f * t + np.pi / 2),
        ]
        self.reference_signal_2f = [
            np.sin(2 * np.pi * 2 * self.f * t),
            np.sin(2 * np.pi * 2 * self.f * t + np.pi / 2),
        ]

    def _build_output_buffer(self) -> None:
        """
        Pre-allocate the 3-channel output array.
        Only the coils row (index 2) needs to change between field steps,
        so we patch just that row in start_tasks() rather than rebuilding
        the whole array each time.
        """
        n = len(self.reference_signal_1f[0])

        if self.mod_chan == "AC_Output1":
            ch0 = np.concatenate([self.reference_signal_1f[0] * self.modulation_amp,
                                   [self.modulation_amp / np.sqrt(2)]])
            ch1 = np.full(n + 1, self.dc_output[1])
        elif self.mod_chan == "AC_Output2":
            ch0 = np.full(n + 1, self.dc_output[0])
            ch1 = np.concatenate([self.reference_signal_1f[0] * self.modulation_amp,
                                   [self.modulation_amp / np.sqrt(2)]])
        else:
            ch0 = np.full(n + 1, self.dc_output[0])
            ch1 = np.full(n + 1, self.dc_output[1])

        ch2 = np.full(n + 1, self.coils_output)

        # Shape: (3, n+1) — nidaqmx expects (channels, samples)
        self._output_values = np.array([ch0, ch1, ch2])

    # ── Hot path ──────────────────────────────────────────────────────────────

    def start_tasks(self) -> None:
        """
        Arm input/output tasks and fire the trigger.

        Key change vs original:
        - No nidaqmx.Task() construction — trigger reuses _trigger_task.
        - Output buffer is pre-allocated; only the coils row is patched.
        - input.start() is called BEFORE output.write() so it is armed when
          the trigger fires.

        Tasks are explicitly stopped at the top of this method before writing
        to ensure they are in a clean, re-armable state.  NI-DAQmx finite
        generation tasks enter a "done" state after the last sample is clocked
        out; attempting to write into a done-but-not-stopped task raises
        DaqWriteError -200288.  Calling stop() resets the task to idle so the
        buffer can be rewritten and the task re-started for the next point.
        """
        if not self.enabled:
            return

        # Reset both tasks to idle — required before writing to a finite
        # output task that has already completed its previous generation.
        try:
            self.output.stop()
        except Exception:
            pass
        try:
            self.input.stop()
        except Exception:
            pass

        # Refresh the per-point values in the pre-allocated buffer:
        #   - row 2 (coils) changes between every field step,
        #   - rows 0/1 carry the constant DC bias (dc_output); they must be
        #     refreshed too because dc_output (e.g. cst_out1/cst_out2) is set by
        #     the procedure AFTER setup_aquisition built the buffer.  The
        #     channel currently used for modulation keeps its pre-built sine
        #     waveform and is left untouched.
        # This preserves the fast path (no Task creation, no full rebuild) while
        # ensuring the constant outputs actually take effect.
        if self._output_values is not None:
            self._output_values[2, :] = self.coils_output
            if self.mod_chan == "AC_Output1":
                self._output_values[1, :] = self.dc_output[1]
            elif self.mod_chan == "AC_Output2":
                self._output_values[0, :] = self.dc_output[0]
            else:
                self._output_values[0, :] = self.dc_output[0]
                self._output_values[1, :] = self.dc_output[1]
        else:
            self._build_output_buffer()

        # Arm input first, then write output (output write fires when trigger arrives)
        self.input.start()
        self.output.write(self._output_values, auto_start=False)
        self.output.start()

        # Fire trigger — reuses persistent task, no Task() constructor overhead
        self.fire_trigger()

    def read_data(self) -> tuple:
        """
        Wait for acquisition to complete and return (data_ai0, data_ai1).
        Tasks are stopped here (not in start_tasks) so wait_until_done is valid.
        """
        if not self.enabled:
            np_points = round(self.sampling_rate * self.acquisition_time) + 1
            return np.full(np_points, 0.), np.full(np_points, 0.)

        # nidaqmx defaults every wait/read timeout to 10 s, so an acquisition
        # window longer than that used to time out mid-measurement.  Give the
        # driver the actual window length plus a generous margin instead.
        timeout = float(self.acquisition_time) + 10.0
        self.output.wait_until_done(timeout=timeout)
        self.input.wait_until_done(timeout=timeout)

        n_read = len(self.reference_signal_1f[0]) + 1
        data_ai0, data_ai1 = self.input.read(number_of_samples_per_channel=n_read,
                                             timeout=timeout)

        # Strip the trailing RMS-hold sample
        data_ai0.pop()
        data_ai1.pop()

        self.output.stop()
        self.input.stop()

        return data_ai0, data_ai1

    # ── Utility ───────────────────────────────────────────────────────────────

    def reset_tasks(self) -> None:
        if not self.enabled:
            return

        try:
            timeout = float(getattr(self, "acquisition_time", 0.5)) + 10.0
            self.output.wait_until_done(timeout=timeout)
            self.input.wait_until_done(timeout=timeout)
        except Exception:
            pass

        self.status_setup = False
        self.coils_output = 0.
        self.dc_output    = [0., 0.]

        self.output.stop()
        self.input.stop()

    def demodulation(self, data, ref_signal, bandwith, offset=0, order=3) -> dict:
        lp_num, lp_den = butter(order, bandwith, fs=self.sampling_rate, btype='low')

        X = np.multiply(data - offset, ref_signal[0])
        Y = np.multiply(data - offset, ref_signal[1])

        X = filtfilt(lp_num, lp_den, np.concatenate([X, X, X]))[len(data):2 * len(data)]
        Y = filtfilt(lp_num, lp_den, np.concatenate([Y, Y, Y]))[len(data):2 * len(data)]

        return {
            "X":     np.sqrt(np.mean(X ** 2)),
            "Y":     np.sqrt(np.mean(Y ** 2)),
            "R":     np.mean(np.sqrt(X ** 2 + Y ** 2)),
            "theta": np.mean(np.arctan2(Y, X)),
        }

    def set_outputs_and_reset(self, outputs) -> None:
        if not self.enabled:
            return

        self.reset_tasks()
        self.output.timing.cfg_samp_clk_timing(10000, samps_per_chan=2)
        self.output.write(
            np.tile([outputs[0], outputs[1], outputs[2]], (2, 1)).T.tolist(),
            auto_start=True,
        )

        # Reuse persistent trigger task
        self.fire_trigger()

    def setup_dac(self) -> None:
        try:
            self.output = nidaqmx.Task('OutputTask')
            self.input  = nidaqmx.Task('InputTask')
            self.enabled = True
        except Exception:
            print("DAC not found!")
            return

        ports = dac_config.get_section("IO ports")

        self.output.ao_channels.add_ao_voltage_chan(ports.get("AC_Output1",             "Dev1/"))
        self.output.ao_channels.add_ao_voltage_chan(ports.get("AC_Output2",             "Dev1/"))
        self.output.ao_channels.add_ao_voltage_chan(ports.get("Coils_Output",           "Dev1/"))
        self.input.ai_channels.add_ai_voltage_chan( ports.get("Balanced_diodes_Input",  "Dev1/"))
        self.input.ai_channels.add_ai_voltage_chan( ports.get("Intensity_diode_Input",  "Dev1/"))

        self.output.triggers.start_trigger.cfg_dig_edge_start_trig(
            "/Dev1/PFI0", trigger_edge=nidaqmx.constants.Edge.RISING)
        self.input.triggers.start_trigger.cfg_dig_edge_start_trig(
            "/Dev1/PFI0", trigger_edge=nidaqmx.constants.Edge.RISING)

        # Create the persistent trigger task once — never recreated per-point
        self._open_trigger_task()