# Moving the 7270 lock-in from USB to Ethernet

A direct, private cable between the PC and the lock-in — no ETHZ network
involvement, no IT registration, immune to the USB interface hangs.

**You need:** a USB-to-Ethernet adapter (USB 2.0, 10/100 is plenty), one normal
Ethernet patch cable long enough to reach the 7270's rear panel, and admin
rights on the PC.

---

## 1. Plug in the adapter (PC side)

1. Plug the adapter into a USB port — preferably a **rear port** directly on the
   PC, not a front-panel port or hub.
2. Windows 10/11 installs the driver by itself. Check **Device Manager →
   Network adapters**: a new entry appears (typically "Realtek USB FE/GbE Family
   Controller" or "ASIX AX88772").
3. If it doesn't appear, run Windows Update once, or install the driver from
   the adapter vendor's site.

## 2. Disable power saving on the adapter

- Device Manager → Network adapters → right-click the new adapter →
  **Properties → Power Management** → untick *"Allow the computer to turn off
  this device to save power"*.
- Optional, same dialog under **Advanced**: disable *Energy-Efficient Ethernet*
  / *Green Ethernet* if the properties exist.

## 3. Give the adapter a fixed IP

Control Panel → Network and Sharing Center → **Change adapter settings** →
right-click the new adapter (it will be named "Ethernet 2" or similar) →
Properties → **Internet Protocol Version 4 (TCP/IPv4)** → Properties:

| Field           | Value             |
|-----------------|-------------------|
| IP address      | `192.168.77.1`    |
| Subnet mask     | `255.255.255.0`   |
| Default gateway | **leave empty**   |
| DNS servers     | **leave empty**   |

Leaving the gateway empty is what keeps all internet/server traffic on the
normal network port — only lock-in traffic uses this adapter. Windows will
label the link "Unidentified network / Public"; that's fine (we only make
outgoing connections).

## 4. Configure the 7270 (instrument side)

1. Connect the patch cable: adapter ↔ the Ethernet socket on the 7270's rear
   panel. (No crossover cable needed — the ports auto-detect.)
2. On the 7270 front panel: **Main Menu → Communications → Ethernet** and set:
   - IP address: `192.168.77.2`
   - Subnet mask: `255.255.255.0`
   - Gateway: `0.0.0.0` / none
3. Apply; if the firmware asks to restart the interface (or if in doubt),
   power-cycle the instrument once.
4. The link LEDs on both the adapter and the 7270's port should now be lit.

## 5. Test the link

Open Command Prompt on the PC:

```
ping 192.168.77.2
```

You want four replies with ~1 ms times. Then prove the command socket is
listening (PowerShell):

```
Test-NetConnection 192.168.77.2 -Port 50000
```

`TcpTestSucceeded : True` means the instrument is ready to be controlled.

If the ping fails: re-check the cable is in the right ports, both IPs and both
subnet masks, and that the 7270 applied its settings (power-cycle it once).

## 6. Point MiniMOKE at Ethernet

Edit `configs/instruments_config.ini`:

```ini
[LockIn]
# resource = USB0::0x0A2D::0x001B::15342534::RAW
resource = TCPIP0::192.168.77.2::50000::SOCKET
```

Start the app and do a short supervised test sweep — check the lock-in values
look normal. Unplug the USB cable from the 7270 once Ethernet works, so there's
only one active control path.

Switching back to USB is the same edit in reverse (swap which line is
commented) plus an app restart.

## 7. If something misbehaves

- **App starts with "Lock-in (Ametek 7270) not found"** — the socket didn't
  open: redo step 5.
- **"Incorrect return from previously set property" on alternating commands,
  or an XY-read crash right at the first point** — you are running a version
  older than 2026-07-15. The socket interface appends a status-prompt chunk to
  every response that USB doesn't send; the driver now probes the framing at
  connect and drains the extra chunk automatically. `git pull` and restart.
- The auto-recovery ladder still applies over Ethernet (session re-open +
  retry); the USB-replug step skips itself automatically since there is no USB
  device to reset.
