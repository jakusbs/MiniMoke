#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2023 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

from pymeasure.instruments import Instrument
from pymeasure.instruments.validators import modular_range, truncated_discrete_set, truncated_range, strict_range

import sys
import time
import subprocess
import logging
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Auto-reconnect tuning: how many times to re-open the VISA session (clearing the
# device each time) and retry a failed command, and the base settle time after
# each re-open.  The wait grows with the attempt number (1x, 2x, 3x ...) so a
# power-suspended USB device, which can take several seconds to actually resume,
# gets progressively more time before the retry.
RECONNECT_ATTEMPTS = 4
RECONNECT_SETTLE_S = 1.0
# From this attempt on, escalate to a bus-level USB re-enumeration (the software
# equivalent of unplugging and replugging the cable) before re-opening the
# session — a hard-hung instrument interface ignores session re-opens and device
# clears but re-initialises its USB stack on a bus reset.
USB_RESET_FROM_ATTEMPT = 3
USB_RESET_SETTLE_S     = 5.0   # give Windows time to re-enumerate the device


def check_read_not_empty(value):
    """Called by some properties to check if the reply is not an empty string
    that would mean the properties is currently invalid (probably because the reference mode
    is on single or dual)"""
    if value == '':
        raise ValueError('Invalid response from measurement call, '
                         'probably because the reference mode is set on single or dual')
    else:
        return value


class Ametek7270(Instrument):
    """This is the class for the Ametek DSP 7270 lockin amplifier

    In this instrument, some measurements are defined only for specific modes,
    called Reference modes, see :meth:`set_reference_mode` and will raise errors
    if called incorrectly
    """

    # Mirrors the ``enabled`` flag used by the other device classes (DAC,
    # HallSensor, stages) so callers can uniformly test whether the hardware
    # is available.  A successfully constructed instrument is enabled; the
    # OfflineLockin fallback (below) reports False.
    enabled = True

    SENSITIVITIES = [
        0.0, 2.0e-9, 5.0e-9, 10.0e-9, 20.0e-9, 50.0e-9, 100.0e-9,
        200.0e-9, 500.0e-9, 1.0e-6, 2.0e-6, 5.0e-6, 10.0e-6,
        20.0e-6, 50.0e-6, 100.0e-6, 200.0e-6, 500.0e-6, 1.0e-3,
        2.0e-3, 5.0e-3, 10.0e-3, 20.0e-3, 50.0e-3, 100.0e-3,
        200.0e-3, 500.0e-3, 1.0
    ]

    SENSITIVITIES_IMODE = {0: SENSITIVITIES,
                           1: [sen * 1e-6 for sen in SENSITIVITIES],
                           2: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2e-15, 5e-15, 10e-15,
                               20e-15, 50e-15, 100e-15, 200e-15, 500e-15, 1e-12, 2e-12]}

    TIME_CONSTANTS = [
        10.0e-6, 20.0e-6, 50.0e-6, 100.0e-6, 200.0e-6, 500.0e-6,
        1.0e-3, 2.0e-3, 5.0e-3, 10.0e-3, 20.0e-3, 50.0e-3, 100.0e-3,
        200.0e-3, 500.0e-3, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0,
        100.0, 200.0, 500.0, 1.0e3, 2.0e3, 5.0e3, 10.0e3,
        20.0e3, 50.0e3, 100.0e3
    ]

    sensitivity = Instrument.control(  # NOTE: only for IMODE = 1.
        "SEN", "SEN %d",
        """ A floating point property that controls the sensitivity
        range in Volts, which can take discrete values from 2 nV to
        1 V. This property can be set. """,
        validator=truncated_discrete_set,
        values=SENSITIVITIES,
        map_values=True,
        check_set_errors=True,
        dynamic=True,
    )

    slope = Instrument.control(
        "SLOPE", "SLOPE %d",
        """ A integer property that controls the filter slope in
        dB/octave, which can take the values 6, 12, 18, or 24 dB/octave.
        This property can be set. """,
        validator=truncated_discrete_set,
        values=[6, 12, 18, 24],
        map_values=True,
        check_set_errors=True,
    )

    time_constant = Instrument.control(  # NOTE: only for NOISEMODE = 0
        "TC", "TC %d",
        """ A floating point property that controls the time constant
        in seconds, which takes values from 10 microseconds to 100,000
        seconds. This property can be set. """,
        validator=truncated_discrete_set,
        values=TIME_CONSTANTS,
        map_values=True,
        check_set_errors=True,
    )

    x = Instrument.measurement("X.",
                               """ Reads the X value in Volts """,
                               get_process=check_read_not_empty,
                               )
    y = Instrument.measurement("Y.",
                               """ Reads the Y value in Volts """,
                               get_process=check_read_not_empty,
                               )
    x1 = Instrument.measurement("X1.",
                                """ Reads the first harmonic X value in Volts """,
                                get_process=check_read_not_empty,
                                )
    y1 = Instrument.measurement("Y1.",
                                """ Reads the first harmonic Y value in Volts """,
                                get_process=check_read_not_empty,
                                )
    x2 = Instrument.measurement("X2.",
                                """ Reads the second harmonic X value in Volts """,
                                get_process=check_read_not_empty,
                                )
    y2 = Instrument.measurement("Y2.",
                                """ Reads the second harmonic Y value in Volts """,
                                get_process=check_read_not_empty,
                                )
    xy = Instrument.measurement("XY.",
                                """ Reads both the X and Y values in Volts """,
                                get_process=check_read_not_empty,
                                )
    mag = Instrument.measurement("MAG.",
                                 """ Reads the magnitude in Volts (single reference mode). """,
                                 get_process=check_read_not_empty,
                                 )

    theta = Instrument.measurement("PHA.",
                                   """ Reads the signal phase in degrees (single reference mode). """,
                                   get_process=check_read_not_empty,
                                   )

    mag1 = Instrument.measurement("MAG1.",
                                  """ Reads the first-harmonic magnitude in Volts (dual harmonic mode only). """,
                                  get_process=check_read_not_empty,
                                  )

    theta1 = Instrument.measurement("PHA1.",
                                    """ Reads the first-harmonic phase in degrees (dual harmonic mode only). """,
                                    get_process=check_read_not_empty,
                                    )

    harmonic = Instrument.control(
        "REFN", "REFN %d",
        """ An integer property that represents the reference
        harmonic mode control, taking values from 1 to 127.
        This property can be set. """,
        validator=truncated_discrete_set,
        values=list(range(1, 128)),
        check_set_errors=True,
    )
    phase = Instrument.control(
        "REFP.", "REFP. %g",
        """ A floating point property that represents the reference
        harmonic phase in degrees. This property can be set. """,
        validator=modular_range,
        values=[0, 360],
        check_set_errors=True,
    )
    voltage = Instrument.control(
        "OA.", "OA. %g",
        """ A floating point property that represents the voltage
        in Volts. This property can be set. """,
        validator=truncated_range,
        values=[0, 5],
        check_set_errors=True,
    )
    frequency = Instrument.control(
        "OF.", "OF. %g",
        """ A floating point property that represents the lock-in
        frequency in Hz. This property can be set. """,
        validator=truncated_range,
        values=[0, 2.5e5],
        check_set_errors=True,
    )
    dac1 = Instrument.control(
        "DAC. 1", "DAC. 1 %g",
        """ A floating point property that represents the output
        value on DAC1 in Volts. This property can be set. """,
        validator=truncated_range,
        values=[-10, 10],
        check_set_errors=True,
    )
    dac2 = Instrument.control(
        "DAC. 2", "DAC. 2 %g",
        """ A floating point property that represents the output
        value on DAC2 in Volts. This property can be set. """,
        validator=truncated_range,
        values=[-10, 10],
        check_set_errors=True,
    )
    dac3 = Instrument.control(
        "DAC. 3", "DAC. 3 %g",
        """ A floating point property that represents the output
        value on DAC3 in Volts. This property can be set. """,
        validator=truncated_range,
        values=[-10, 10],
        check_set_errors=True,
    )
    dac4 = Instrument.control(
        "DAC. 4", "DAC. 4 %g",
        """ A floating point property that represents the output
        value on DAC4 in Volts. This property can be set. """,
        validator=truncated_range,
        values=[-10, 10],
        check_set_errors=True,
    )
    adc1 = Instrument.measurement("ADC. 1",
                                  """ Reads the input value of ADC1 in Volts """,
                                  get_process=check_read_not_empty,
                                  )
    adc2 = Instrument.measurement("ADC. 2",
                                  """ Reads the input value of ADC2 in Volts """,
                                  get_process=check_read_not_empty,
                                  )
    adc3 = Instrument.measurement("ADC. 3",
                                  """ Reads the input value of ADC3 in Volts """,
                                  get_process=check_read_not_empty,
                                  )
    adc4 = Instrument.measurement("ADC. 4",
                                  """ Reads the input value of ADC4 in Volts """,
                                  get_process=check_read_not_empty,
                                  )

    def __init__(self, adapter='USB0::0x0A2D::0x001B::15342534::RAW', name="Ametek DSP 7270",
                 read_termination='\x00',
                 write_termination='\x00',
                 **kwargs):

        super().__init__(
            adapter,
            name,
            includeSCPI=False, #new line for updated pymeasure instrument class
            read_termination=read_termination,
            write_termination=write_termination,
            **kwargs)


    def check_set_errors(self):
        """mandatory to be used for property setter

        The Ametek protocol expect the default null character to be read to check the property
        has been correctly set. With default termination character set as Null character,
        this turns out as an empty string to be read.
        """
        if self.read() == '':
            return []
        else:
            return ['Incorrect return from previously set property']

    def ask(self, command, query_delay=0):
        """Send a command and read the response, stripping white spaces.

        On a communication failure (e.g. the USB link dropped or was suspended
        by Windows mid-run), reconnect the VISA session and retry the command
        once, so a transient disconnect does not abort a running measurement.
        Every read goes through here — the measurement properties use
        :meth:`~pymeasure.instruments.common_base.CommonBase.values`, which calls
        ``ask`` — so this single guard covers per-point reads and commands alike.
        """
        try:
            return super().ask(command, query_delay).strip()
        except Exception as exc:   # noqa: BLE001 - any VISA/USB I/O failure
            log.warning(f"Lock-in I/O error on '{command}' ({exc}); "
                        f"re-opening the USB link and retrying.")

        # A dropped or power-suspended USB link can need a moment — and more than
        # one attempt — to come back, so reconnect and retry a few times before
        # giving up (rather than aborting the whole measurement on one glitch).
        last_exc = None
        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            if attempt >= USB_RESET_FROM_ATTEMPT:
                # Session re-open + device clear didn't help: the instrument's
                # USB interface is likely hard-hung.  Escalate to a bus-level
                # reset (re-enumerate the device, as if the cable was replugged).
                self._reset_usb_device()
            self.reconnect()
            time.sleep(RECONNECT_SETTLE_S * attempt)   # progressively longer for a slow-to-resume device
            try:
                result = super().ask(command, query_delay).strip()
                if attempt > 1:
                    log.info(f"Lock-in link recovered after {attempt} reconnect attempts.")
                return result
            except Exception as exc:   # noqa: BLE001
                last_exc = exc
                log.warning(f"Lock-in still unreachable after reconnect attempt "
                            f"{attempt}/{RECONNECT_ATTEMPTS}.")
        log.error(
            "Lock-in did not respond after re-opening, clearing and resetting the "
            "USB link %d times — its interface looks hard-hung. Power-cycle the "
            "7270 (or unplug/replug its USB cable). If this keeps happening, "
            "consider running it over Ethernet instead of USB (see "
            "configs/instruments_config.ini).", RECONNECT_ATTEMPTS)
        raise last_exc

    def reconnect(self):
        """Re-open the VISA session *and clear the device* to recover a dropped,
        power-suspended, or wedged USB link, without a power cycle.

        A fresh session alone is often not enough: if the instrument's USB I/O
        buffers or command parser are stuck — e.g. a command was interrupted by
        an EMI glitch when the field coils switched, or the parser hung after an
        input overload — the re-open succeeds but the very next write still times
        out (exactly the symptom seen in the field logs).  So after re-opening we
        issue a VISA device clear (``viClear``), which flushes the device's I/O
        buffers and un-wedges it.  The instrument keeps its settings across a
        suspend/clear, so the running measurement resumes.  Best-effort: logs and
        returns even if a step fails (the retrying caller then surfaces the
        original error).
        """
        conn     = getattr(self.adapter, "connection", None)
        resource = getattr(self.adapter, "resource_name", None)
        manager  = getattr(self.adapter, "manager", None)
        # Match the new session to the current one's terminations/timeout.
        read_term  = getattr(conn, "read_termination", "\x00")
        write_term = getattr(conn, "write_termination", "\x00")
        timeout    = getattr(conn, "timeout", None)
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        if resource is None or manager is None:
            log.warning("Lock-in reconnect skipped: no VISA resource/manager available.")
            return
        try:
            new_conn = manager.open_resource(resource, read_termination=read_term,
                                             write_termination=write_term)
            if timeout is not None:
                new_conn.timeout = timeout
            # Flush the device's I/O buffers so a wedged parser/endpoint accepts
            # the next command — a fresh session by itself does not do this.
            try:
                new_conn.clear()
            except Exception as exc:   # noqa: BLE001 - not every backend implements clear()
                log.debug(f"Lock-in device clear skipped: {exc}")
            self.adapter.connection = new_conn
            log.info("Lock-in VISA session reconnected (device cleared).")
        except Exception as exc:   # noqa: BLE001 - never let recovery itself crash
            log.warning(f"Lock-in reconnect failed: {exc}")

    @staticmethod
    def _usb_instance_id(resource_name):
        """Derive the Windows device-instance ID from a VISA USB resource name.

        'USB0::0x0A2D::0x001B::15342534::RAW' -> 'USB\\VID_0A2D&PID_001B\\15342534'
        Returns None for non-USB resources (e.g. Ethernet) or unparsable strings.
        """
        parts = str(resource_name or "").split("::")
        if len(parts) < 4 or not parts[0].upper().startswith("USB"):
            return None
        try:
            vid = f"{int(parts[1], 0):04X}"   # int(_, 0) accepts 0x0A2D and 2605 alike
            pid = f"{int(parts[2], 0):04X}"
        except ValueError:
            return None
        return f"USB\\VID_{vid}&PID_{pid}\\{parts[3]}"

    def _reset_usb_device(self):
        """Bus-level recovery: re-enumerate the USB device — the software
        equivalent of unplugging and replugging the cable.

        A hard-hung instrument interface (e.g. after an EMI glitch from the field
        coils) ignores session re-opens and device clears, but a USB bus reset
        forces it to re-initialise its USB stack.  Uses
        ``pnputil /restart-device`` with the instance ID derived from the VISA
        resource, so only the lock-in is touched.  Windows-only; needs the
        program to run with administrator rights; best-effort (returns False on
        any failure and the reconnect ladder simply continues).
        """
        if sys.platform != "win32":
            return False
        instance = self._usb_instance_id(getattr(self.adapter, "resource_name", ""))
        if not instance:
            return False   # not connected over USB — nothing to reset
        log.warning("Re-opening the session didn't help — re-enumerating the USB "
                    "device (software replug).")
        try:
            proc = subprocess.run(["pnputil", "/restart-device", instance],
                                  capture_output=True, text=True, timeout=30)
        except Exception as exc:   # noqa: BLE001 - pnputil missing, timeout, ...
            log.warning(f"USB re-enumeration could not run: {exc}")
            return False
        if proc.returncode == 0:
            log.info(f"USB device re-enumerated ({instance}).")
            time.sleep(USB_RESET_SETTLE_S)   # let Windows finish enumeration
            return True
        detail = (proc.stdout or proc.stderr or "").strip()[:200]
        log.warning(f"USB re-enumeration refused (pnputil exit {proc.returncode}) — "
                    f"this usually needs the program to run as Administrator. {detail}")
        return False

    def set_reference_mode(self, mode: int = 0):
        """Set the instrument in Single, Dual or harmonic mode.

        :param mode: the integer specifying the mode: 0 for Single, 1 for Dual harmonic, and 2 for
            Dual reference.

        """
        if mode not in [0, 1, 2]:
            raise ValueError('Invalid reference mode')
        # ask() already reconnects + retries once on a communication error.
        self.ask(f'REFMODE {mode}')

    def set_voltage_mode(self):
        """ Sets instrument to voltage control mode """
        self.ask("IMODE 0")
        self.sensitivity_values = self.SENSITIVITIES_IMODE[0]

    def set_differential_mode(self, lineFiltering=True):
        """ Sets instrument to differential mode -- assuming it is in voltage mode """
        self.ask("VMODE 3")
        self.ask("LF %d 0" % 3 if lineFiltering else 0)

    def set_current_mode(self, low_noise=False):
        """ Sets instrument to current control mode with either low noise or high bandwidth"""
        if low_noise:
            self.ask("IMODE 2")
            self.sensitivity_values = self.SENSITIVITIES_IMODE[2]
        else:
            self.ask("IMODE 1")
            self.sensitivity_values = self.SENSITIVITIES_IMODE[1]

    def set_channel_A_mode(self):
        """ Sets instrument to channel A mode -- assuming it is in voltage mode """
        self.ask("VMODE 1")

    def setup_lockin_condition(self, lockin_voltage=1.0, lockin_sensitivity=100.00e-6, lockin_frequency=773, lockin_time_constant=0.2, lockin_phase=0)-> None:
        self.voltage = lockin_voltage
        self.sensitivity = lockin_sensitivity
        self.frequency = lockin_frequency
        self.time_constant = lockin_time_constant
        self.phase = lockin_phase


    @property
    def id(self):
        """Get the instrument ID and firmware version"""
        return f"{self.ask('ID')}/{self.ask('VER')}"

    @property
    def auto_gain(self):
        return int(self.ask("AUTOMATIC")) == 1

    @auto_gain.setter
    def auto_gain(self, setval):
        if setval:
            self.ask("AUTOMATIC 1")
        else:
            self.ask("AUTOMATIC 0")

    def shutdown(self):
        """ Ensures the instrument in a safe state """
        log.info("Shutting down %s" % self.name)
        self.voltage = 0.
        super().shutdown()


class OfflineLockin:
    """Drop-in stand-in used when no Ametek 7270 lock-in (or VISA backend) is
    available.

    The real :class:`Ametek7270` is constructed at import time in
    ``src/classes/__init__.py``.  If the instrument is not connected, that
    construction raises and would otherwise crash the whole application before
    the UI ever appears — unlike every other device (DAC, Hall sensor, stages),
    which degrade gracefully.  This stub mirrors the subset of the Ametek API
    the procedures and UI actually use so the program can still start and run
    (returning zeros) when the lock-in is missing.
    """

    enabled = False

    # Measurement reads — always 0.0 when offline.
    x = y = x1 = y1 = x2 = y2 = 0.0
    mag = mag1 = theta = theta1 = xy = 0.0
    adc1 = adc2 = adc3 = adc4 = 0.0
    auto_gain = False

    def __init__(self):
        self.name = "Ametek DSP 7270 (offline)"
        # Settable controls — stored but otherwise ignored.
        self.voltage = self.sensitivity = self.frequency = 0.0
        self.time_constant = self.phase = 0.0
        self.harmonic = 1
        self.sensitivity_values = self.SENSITIVITIES if hasattr(self, "SENSITIVITIES") else []

    @property
    def id(self):
        return "Ametek DSP 7270 (offline)/n.a."

    # Command/configuration helpers — all no-ops returning empty/neutral values.
    def ask(self, command, query_delay=0):
        return ""

    def reconnect(self):
        pass

    def set_reference_mode(self, mode: int = 0):
        pass

    def set_voltage_mode(self):
        pass

    def set_current_mode(self, low_noise=False):
        pass

    def set_differential_mode(self, lineFiltering=True):
        pass

    def set_channel_A_mode(self):
        pass

    def setup_lockin_condition(self, *args, **kwargs):
        pass

    def shutdown(self):
        pass
