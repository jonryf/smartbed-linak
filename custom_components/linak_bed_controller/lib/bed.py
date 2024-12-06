"""High level helper class to organise methods for performing actions with a Linak Bed."""

import asyncio
from enum import Enum
import logging
import threading
import time

from bleak import BleakClient

from homeassistant.helpers.entity_platform import Logger


class Command(Enum):
    """Enum for bed commands."""

    ALL_DOWN = "0000"
    ALL_UP = "0100"
    STOP_MOVEMENT = "FF00"
    HEAD_UP = "0B00"  # [0x0B, 0x00]
    HEAD_DOWN = "0A00"  # [0x0A, 0x00]
    FOOT_UP = "0900"  # [0x09, 0x00]
    FOOT_DOWN = "0800"  # [0x08, 0x00]


class Bed:
    client: BleakClient | None
    is_connected: bool = False  # TODO: ...
    last_time_used: int = 0

    def __init__(self, mac_address: str, device_name: str, logger: Logger):
        self.mac_address = mac_address
        self.device_name = device_name
        self.logger = logger  # logging.getLogger(__name__)

        self.head_increment = (
            100 / 85
        )  # Number of commands required to go from 0% to 100%
        self.feet_increment = 100 / 60

        # "State" - assume bed is in flat position on boot
        self.head_position = 0
        self.feet_position = 0
        self.light_status = False
        self.client = None

    def set_ble_device(self, device):
        self.device = device

    def set_flat(self):
        pass

    def disconnect_callback(self):
        if self.client is None:
            self.logger.warning("Not connected, skipping disconnect.")
            return
        time_now = time.time()
        if (time_now - self.last_time_used) > 4:
            self.logger.info("Disconnecting from bed.")
            self.client.disconnect()
            self.logger.info("Disconnected from bed.")
            self.is_connected = False

    def set_max(self):
        self.set_max_head()
        self.set_max_foot()

    async def set_flat_head(self):
        await self.move_head_rest_to(0)

    async def set_max_head(self):
        await self.move_head_rest_to(100)

    async def set_flat_foot(self):
        pass

    async def set_max_foot(self):
        pass

    async def move_head_rest_to(self, position: float):
        self.logger.info("Move head rest to %s", position)
        await self._connect_bed()
        self._move_head_to(position)

    async def move_foot_rest_to(self, position: float):
        pass

    def stop(self):
        pass

    def _move_head_to(self, position):
        while abs(self.head_position - position) > 0.1:
            if self.head_position < position:
                self._head_up()
            else:
                self._head_down()

    def _head_up(self):
        """Move the head section of the bed up."""
        self._write_char(Command.HEAD_UP.value)

        # Update state
        self.head_position = min(100, self.head_position + self.head_increment)
        self.head_position = round(self.head_position, 2)

    def _head_down(self):
        """Move the head section of the bed down."""
        self._write_char(Command.HEAD_DOWN.value)

        # Update state
        self.head_position = max(0, self.head_position - self.head_increment)
        self.head_position = round(self.head_position, 2)

    async def _connect_bed(self):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping connecting.")
            return

        while self.client.is_connected is False:
            try:
                self.logger.warning("Attempting to connect to bed.")
                await self.client.connect()
                self.logger.warning("Connected to bed.")
                self.is_connected = True
                self._print_characteristics()
                self.logger.warning("Connected to bed.")
                self.logger.warning("Enabling bed control.")
                self.device.readCharacteristic(0x000D)
                self.logger.warning("Bed control enabled.")

                # Schedule delayed_function to run after 20 seconds
                timer = threading.Timer(20, self.disconnect_callback)
                timer.start()
                self.last_time_used = time.time()
                return
            except Exception as ex:
                self.logger.warning("Error connecting to bed", ex)
            self.logger.warning("Error connecting to bed, retrying in one second.")
            await asyncio.sleep(1)

    def _write_char(self, cmd):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping writing.")

        self.logger.debug(f"Attempting to transmit command bytes: {cmd}")
        try:
            self.device.writeCharacteristic(
                0x000E,
                bytes.fromhex(cmd),
                withResponse=False,
            )
        except Exception as e:
            self.logger.error(str(e))
        self.logger.debug("Command sent successfully.")

    # def send_command(self, name):
    #     cmd = self.commands.get(name, None)
    #     if cmd is None:
    #         self.logger.warning("Received unknown command... ignoring.")
    #         return {}

    #     self.write_in_progress = True
    #     try:
    #         self._write_char(cmd)
    #         return self.update_state_based_on_command(name)
    #     except Exception:
    #         self.logger.error("Error sending command, attempting reconnect.")
    #         start = time.time()
    #         self._connect_bed()
    #         end = time.time()
    #         if (end - start) < 5:
    #             try:
    #                 self._write_char(self, cmd)
    #             except Exception:
    #                 self.logger.error(
    #                     "Command failed to transmit despite second attempt, dropping command."
    #                 )
    #         else:
    #             self.logger.warning(
    #                 "Bluetooth reconnect took more than five seconds, dropping command."
    #             )
    #     finally:
    #         self.write_in_progress = False

    def _print_characteristics(self):
        try:
            for service in self.device.getServices():
                for chara in service.getCharacteristics():
                    self.logger.debug("Characteristic UUID: %s" % chara.uuid)
                    self.logger.debug("Handle: 0x%04x" % chara.getHandle())
                    properties = chara.propertiesToString()
                    self.logger.debug("Properties: %s" % properties)
                    self.logger.debug(f"{'-'*58}")
        except Exception as e:
            self.logger.error("Error accessing characteristic: %s" % str(e))
