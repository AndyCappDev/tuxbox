#!/usr/bin/env python3
"""TuxBox Driver - Unified entry point with auto-detection

Automatically detects whether the TourBox is connected via USB or Bluetooth
and launches the appropriate driver.

Priority:
1. USB (scans /dev/ttyACM* devices, probes each for TourBox response)
2. BLE (fallback)

Can be overridden with --usb or --ble flags.
"""

import sys
import os
import asyncio
import argparse
import logging
import glob
import time

try:
    from . import VERSION
except ImportError:
    # Fallback for broken editable installs (e.g. Python 3.14 + legacy setuptools)
    VERSION = "unknown"
from .config_loader import load_device_config, DEFAULT_CONNECTION_MODE

logger = logging.getLogger(__name__)

DEFAULT_USB_PORT = "/dev/ttyACM0"

# How often the auto-detect supervisor rescans for a USB TourBox while the
# BLE transport is active. Cheap glob check first; full probe only if a
# /dev/ttyACM* device is actually present.
USB_RESCAN_INTERVAL = 3.0

# Grace period to let the BLE driver wind down after kill_now is set before
# we forcibly cancel its task. Bleak scans can be up to ~10s, so this needs
# headroom.
BLE_SHUTDOWN_TIMEOUT = 15.0

# Unlock command used to probe for TourBox
UNLOCK_COMMAND = bytes.fromhex("5500078894001afe")

# Known TourBox USB (vid, pid) pairs. The supervisor uses these to filter
# /dev/ttyACM* candidates before sending the unlock probe, so devices that
# obviously aren't TourBoxes (Arduinos, 3D printer boards, modems) don't
# receive the unlock bytes every USB_RESCAN_INTERVAL.
#
# Conservative on purpose: the only entries here are pairs we have direct
# hardware evidence for. The manufacturer-string fallback below catches
# unrecognized firmware variants without weakening the filter for genuine
# non-TourBox hardware. If sysfs lookup itself fails (older kernels, unusual
# udev), the resolver returns None and the caller falls through to probing.
TOURBOX_USB_IDS = frozenset([
    (0xc251, 0x2005),  # TourBox Elite, Elite Plus (TourBoxTech via Keil VID)
    (0x2e3c, 0x5740),  # TourBox Neo (Artery AT32 generic CDC ID, shared with
                       # AT32 hobbyist boards; the negative-probe cache below
                       # stops repeat probing of false matches).
])

# Substring (case-insensitive) checked against the device's iManufacturer
# string from sysfs when the (vid, pid) pair isn't in the allowlist above.
TOURBOX_MANUFACTURER_HINT = "tourbox"

# Ports we've already logged a "not-a-TourBox" skip for. The supervisor
# rescans every USB_RESCAN_INTERVAL while in BLE mode, so without this
# guard a non-TourBox CDC-ACM device on the bus would emit a skip log
# every tick. First-sight only is enough to surface the device.
_SKIPPED_PORTS_LOGGED = set()

# Ports that passed the VID/PID filter but didn't respond to the unlock
# probe. Without this, a non-TourBox device sharing an allowlisted VID/PID
# (e.g. an AT32 hobbyist board on 2e3c:5740) would receive the unlock
# command every USB_RESCAN_INTERVAL. Cleared per pass for ports that have
# disappeared from /dev/ttyACM*, so a replug retriggers a fresh probe.
_PROBED_NEGATIVE_PORTS = set()


def _forget_disappeared_ports(current_ports):
    """Drop cached skip/negative state for ports no longer present."""
    _SKIPPED_PORTS_LOGGED.intersection_update(current_ports)
    _PROBED_NEGATIVE_PORTS.intersection_update(current_ports)


def _read_sysfs_usb_attrs(port: str):
    """Read USB descriptor attributes for a /dev/ttyACM* port via sysfs.

    For a CDC-ACM device, /sys/class/tty/<name>/device is the interface
    directory; idVendor/idProduct/manufacturer live one level up on the
    parent USB device directory.

    Returns a dict with any subset of {vid, pid, manufacturer} that could
    be read, or None if no attributes were readable. None means the caller
    should fall through to probing (preserving master behavior on systems
    where sysfs isn't usable for whatever reason).
    """
    try:
        name = os.path.basename(port)
        device_dir = os.path.realpath(f"/sys/class/tty/{name}/device")
        usb_dev_dir = os.path.dirname(device_dir)
        out = {}
        for key, fname in (("vid", "idVendor"), ("pid", "idProduct")):
            try:
                with open(os.path.join(usb_dev_dir, fname)) as f:
                    out[key] = int(f.read().strip(), 16)
            except (OSError, ValueError):
                pass
        try:
            with open(os.path.join(usb_dev_dir, "manufacturer")) as f:
                out["manufacturer"] = f.read().strip()
        except OSError:
            pass
        return out if out else None
    except Exception:
        return None


def _is_likely_tourbox(port: str):
    """Decide whether `port` is worth sending the unlock probe to.

    Returns True if the port matches a known TourBox (vid, pid) pair or its
    iManufacturer string contains the TourBox hint. Returns False if sysfs
    positively identifies the port as something else. Returns None if sysfs
    isn't usable for this port, in which case the caller should fall through
    to probing.
    """
    attrs = _read_sysfs_usb_attrs(port)
    if not attrs:
        return None
    vid = attrs.get("vid")
    pid = attrs.get("pid")
    if vid is not None and pid is not None and (vid, pid) in TOURBOX_USB_IDS:
        return True
    mfr = attrs.get("manufacturer", "")
    if mfr and TOURBOX_MANUFACTURER_HINT in mfr.lower():
        if vid is not None and pid is not None:
            logger.info(
                f"{port} reports unrecognized USB ID {vid:04x}:{pid:04x} "
                f"with manufacturer {mfr!r}; probing anyway"
            )
        return True
    if vid is None or pid is None:
        # Partial sysfs read; safer to fall through and probe.
        return None
    return False


def _probe_if_eligible(port: str) -> bool:
    """Apply the not-a-TourBox filter, then probe if the port survives.

    Returns True if the port both passes the filter (or sysfs is unusable
    and we fall through) and responds to the unlock command. False means
    either sysfs identified the port as something else, or the probe came
    back empty.
    """
    if _is_likely_tourbox(port) is False:
        if port not in _SKIPPED_PORTS_LOGGED:
            logger.debug(f"  Skipping {port}: USB IDs do not match TourBox")
            _SKIPPED_PORTS_LOGGED.add(port)
        return False
    if port in _PROBED_NEGATIVE_PORTS:
        return False
    if probe_usb_device(port):
        return True
    _PROBED_NEGATIVE_PORTS.add(port)
    return False


def probe_usb_device(port: str) -> bool:
    """Probe a USB serial port to check if it's a TourBox Elite

    Sends the unlock command and checks for a valid response.

    Args:
        port: Serial port path to check

    Returns:
        True if the device responds like a TourBox, False otherwise
    """
    try:
        import serial
    except ImportError:
        logger.warning("pyserial not installed, cannot probe USB devices")
        return os.path.exists(port)  # Fall back to simple existence check

    try:
        logger.debug(f"Probing {port} for TourBox...")

        # Try to open the port
        ser = serial.Serial(port, baudrate=115200, timeout=0.5)
        ser.reset_input_buffer()

        # Send unlock command
        ser.write(UNLOCK_COMMAND)
        ser.flush()

        # Wait for response
        time.sleep(0.3)

        # Read response - TourBox should respond with ~26 bytes
        response = ser.read(100)
        ser.close()

        if response:
            logger.debug(f"  Response from {port}: {response.hex()[:40]}...")
            # TourBox unlock response is typically 26 bytes
            # Different firmware versions may have different first bytes (0x07, 0x7a, etc.)
            # Accept any response of reasonable length as a valid TourBox
            if len(response) >= 20:
                logger.info(f"  Found TourBox at {port} ({len(response)} bytes)")
                return True
            else:
                logger.debug(f"  {port} responded but too short ({len(response)} bytes)")
        else:
            logger.debug(f"  No response from {port}")

        return False

    except serial.SerialException as e:
        logger.debug(f"  Cannot open {port}: {e}")
        return False
    except Exception as e:
        logger.debug(f"  Error probing {port}: {e}")
        return False


def find_tuxbox_usb_port(configured_port: str = None) -> str:
    """Find the TourBox Elite USB port by scanning available devices

    Args:
        configured_port: User-configured port to try first

    Returns:
        Port path if found, None otherwise
    """
    # If a specific port is configured, try it first.
    if configured_port and os.path.exists(configured_port):
        logger.debug(f"Trying configured port: {configured_port}")
        if _probe_if_eligible(configured_port):
            return configured_port

    # Scan all ttyACM devices
    acm_devices = sorted(glob.glob("/dev/ttyACM*"))

    # Drop cached skip/negative-probe state for ports that have disappeared,
    # so a replug retriggers fresh evaluation.
    _forget_disappeared_ports(set(acm_devices))

    if not acm_devices:
        logger.debug("No /dev/ttyACM* devices found")
        return None

    logger.debug(f"Found {len(acm_devices)} ACM device(s): {acm_devices}")

    for port in acm_devices:
        # Skip if we already tried the configured port
        if port == configured_port:
            continue

        if _probe_if_eligible(port):
            return port

    return None


async def _wait_for_ble_to_stop(ble_task):
    """Wait for a TuxBoxBLE.start() task to wind down after kill_now is set.

    Falls back to cancellation if the driver does not stop within
    BLE_SHUTDOWN_TIMEOUT (e.g. stuck mid-scan inside bleak).
    """
    try:
        await asyncio.wait_for(asyncio.shield(ble_task), timeout=BLE_SHUTDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(
            f"BLE driver did not exit gracefully within {BLE_SHUTDOWN_TIMEOUT:.0f}s; "
            "cancelling"
        )
        ble_task.cancel()
        try:
            await ble_task
        except (asyncio.CancelledError, Exception):
            pass


async def usb_only_loop(args, configured_usb_port):
    """Wait for a USB TourBox and run it, never touching Bluetooth.

    Used by `connection = usb`. Unlike --usb this does not give up when no
    device is present: as a user service the driver typically starts before
    the cable is plugged in (or before the device is switched on), so it
    rescans until a TourBox shows up. Rescanning is a cheap /dev/ttyACM* glob,
    with no radio activity - the point of the setting on a laptop.
    """
    from .device_usb import TuxBoxUSB

    waiting_logged = False

    while True:
        usb_port = find_tuxbox_usb_port(configured_usb_port)

        if usb_port:
            logger.info(f"Found TourBox at {usb_port}")
            print(f"Found TourBox on USB ({usb_port})")
            await TuxBoxUSB(port=usb_port, config_path=args.config).start()
            return

        # Only announced once - this loop ticks every few seconds.
        if not waiting_logged:
            logger.info(
                "No TourBox USB device found; waiting for one "
                "(Bluetooth disabled by connection = usb)"
            )
            print("Waiting for a TourBox on USB (Bluetooth disabled)...")
            waiting_logged = True

        await asyncio.sleep(USB_RESCAN_INTERVAL)


async def auto_detect_loop(args, configured_usb_port):
    """Auto-detect transport with USB hot-plug awareness.

    Once USB is selected the supervisor steps out of the way: TuxBoxUSB has
    its own internal hot-plug + reconnect loop and handles cable
    disconnect/reconnect itself.

    When USB is absent at startup, the supervisor runs TuxBoxBLE alongside
    a watcher that promotes to USB the moment a TourBox-responsive
    /dev/ttyACM* device appears. This is the common case for users who
    log in before plugging the cable in, or who share the device across
    multiple computers.
    """
    from .device_usb import TuxBoxUSB
    from .device_ble import TuxBoxBLE

    while True:
        usb_port = find_tuxbox_usb_port(configured_usb_port)

        if usb_port:
            logger.info(f"Auto-detected TourBox at {usb_port}")
            print(f"Found TourBox on USB ({usb_port})")
            await TuxBoxUSB(port=usb_port, config_path=args.config).start()
            return

        logger.info("No TourBox USB device found, using BLE")
        print("No USB device found, using Bluetooth")
        ble_driver = TuxBoxBLE(config_path=args.config)
        ble_task = asyncio.create_task(ble_driver.start())
        promoted_to_usb = False

        try:
            while not ble_task.done():
                await asyncio.sleep(USB_RESCAN_INTERVAL)
                # Cheap glob first; only run the full probe if a port exists
                if not glob.glob("/dev/ttyACM*"):
                    continue
                detected = find_tuxbox_usb_port(configured_usb_port)
                if not detected:
                    continue
                logger.info(
                    f"USB device detected at {detected} - "
                    "switching from BLE to USB"
                )
                print("\nUSB cable detected - switching to USB connection...")
                ble_driver.killer.kill_now = True
                promoted_to_usb = True
                break
        finally:
            await _wait_for_ble_to_stop(ble_task)

        if not promoted_to_usb:
            # BLE task ended on its own (signal received, or unrecoverable error).
            return


def main():
    """Main entry point with auto-detection"""

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='TuxBox Driver (auto-detects USB or BLE)',
        epilog='By default, scans for USB first, then falls back to Bluetooth.'
    )
    parser.add_argument('--version', action='version',
                        version=f'TuxBox {VERSION}')
    parser.add_argument('--usb', action='store_true',
                        help='Force USB mode')
    parser.add_argument('--ble', action='store_true',
                        help='Force BLE mode')
    parser.add_argument('--port', '-p',
                        help=f'USB serial port (default: {DEFAULT_USB_PORT})')
    parser.add_argument('-c', '--config',
                        help='Path to custom config file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')

    args = parser.parse_args()

    # Enable debug logging if requested
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load device config
    device_config = load_device_config(args.config)

    # Determine USB port
    usb_port = args.port or device_config.get('usb_port', DEFAULT_USB_PORT)

    # Determine connection mode. Command line flags win over the config file.
    if args.usb and args.ble:
        print("Error: Cannot specify both --usb and --ble")
        sys.exit(1)

    connection = device_config.get('connection', DEFAULT_CONNECTION_MODE)
    if not args.usb and not args.ble and connection != DEFAULT_CONNECTION_MODE:
        logger.info(f"Connection mode '{connection}' set in config")

    try:
        if args.usb:
            logger.info("USB mode forced via --usb flag")
            from .device_usb import TuxBoxUSB

            # Scan for the device if no explicit port was given
            if not args.port:
                detected_port = find_tuxbox_usb_port(usb_port)
                if detected_port:
                    usb_port = detected_port
                elif not os.path.exists(usb_port):
                    print("Error: No TourBox found on USB")
                    print("Is the TourBox connected via USB cable?")
                    print("Checked: /dev/ttyACM* devices")
                    sys.exit(1)

            if not os.path.exists(usb_port):
                print(f"Error: USB port {usb_port} not found")
                print("Is the TourBox connected via USB?")
                sys.exit(1)

            asyncio.run(TuxBoxUSB(port=usb_port, config_path=args.config).start())

        elif args.ble or connection == 'ble':
            if args.ble:
                logger.info("BLE mode forced via --ble flag")
            from .device_ble import TuxBoxBLE
            asyncio.run(TuxBoxBLE(config_path=args.config).start())

        elif connection == 'usb':
            # USB only. Waits for the device rather than exiting when it is
            # absent, so the service survives a login with nothing plugged in.
            print("Scanning for TourBox on USB...")
            asyncio.run(usb_only_loop(args, usb_port))

        else:
            # Auto-detect with USB hot-plug awareness. The supervisor stays
            # alive across the full session so that plugging the cable in
            # after login (or replugging after using the device on another
            # computer) is picked up automatically without a service restart.
            print("Scanning for TourBox...")
            asyncio.run(auto_detect_loop(args, usb_port))

    except KeyboardInterrupt:
        print("\nExited by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
