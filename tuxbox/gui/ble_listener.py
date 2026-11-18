#!/usr/bin/env python3
"""BLE event listener for TourBox Elite

Connects to the device and listens for button press events.
"""

import asyncio
import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal
from bleak import BleakClient
from tuxbox.i18n import _

logger = logging.getLogger(__name__)

# BLE Configuration (from device_ble.py)
VENDOR_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHAR = "0000fff2-0000-1000-8000-00805f9b34fb"

# Unlock and config commands (from device_ble.py)
UNLOCK_COMMAND = bytes.fromhex("5500078894001afe")
CONFIG_COMMANDS = [
    bytes.fromhex("b5005d0400050006000700080009000b000c000d"),
    bytes.fromhex("000e000f0026002700280029003b003c003d003e"),
    bytes.fromhex("003f004000410042004300440045004600470048"),
    bytes.fromhex("0049004a004b004c004d004e004f005000510052"),
    bytes.fromhex("0053005400a800a900aa00ab00fe"),
]


class BLEListener(QObject):
    """Listens for BLE events from TourBox Elite"""

    # Signals
    connected = Signal()
    disconnected = Signal()
    button_pressed = Signal(bytes)  # raw button data
    error_occurred = Signal(str)

    def __init__(self, mac_address: str, parent=None):
        super().__init__(parent)
        self.mac_address = mac_address
        self.client: Optional[BleakClient] = None
        self._running = False

    async def connect(self):
        """Connect to TourBox Elite via BLE"""
        try:
            logger.info(f"Connecting to TourBox at {self.mac_address}...")

            self.client = BleakClient(
                self.mac_address,
                timeout=5.0,
                disconnected_callback=self._on_disconnect
            )

            await self.client.connect()
            logger.info("Connected to TourBox Elite")

            # Enable notifications
            await self.client.start_notify(NOTIFY_CHAR, self._notification_handler)

            # Unlock device
            await self._unlock_device()

            self.connected.emit()
            self._running = True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.error_occurred.emit(_("Failed to connect: %s") % (e,))
            raise

    async def disconnect(self):
        """Disconnect from TourBox Elite"""
        self._running = False

        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(NOTIFY_CHAR)
                await self.client.disconnect()
                logger.info("Disconnected from TourBox Elite")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")

    async def _unlock_device(self):
        """Send unlock sequence to TourBox Elite"""
        logger.info("Unlocking device...")

        # Send unlock command
        await self.client.write_gatt_char(WRITE_CHAR, UNLOCK_COMMAND, response=False)
        await asyncio.sleep(0.1)

        # Send configuration commands
        for cmd in CONFIG_COMMANDS:
            await self.client.write_gatt_char(WRITE_CHAR, cmd, response=False)
            await asyncio.sleep(0.01)

        logger.info("Device unlocked")

    def _notification_handler(self, sender, data: bytearray):
        """Handle button notifications from TourBox Elite"""
        data_bytes = bytes(data)
        logger.debug(f"Received: {data_bytes.hex()}")
        self.button_pressed.emit(data_bytes)

    def _on_disconnect(self, client):
        """Handle disconnection"""
        logger.warning("TourBox Elite disconnected")
        self.disconnected.emit()
