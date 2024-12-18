"""High level helper class to organise methods for performing actions with a Linak Bed."""

import asyncio
from enum import Enum
import logging
import threading
import time

from bleak import BleakClient

from homeassistant.helpers.entity_platform import Logger

_UUID_COMMAND: str = "99fa0002-338a-1024-8a49-009c0215f78a"

_COMMAND_ALL_DOWN: bytearray = bytearray([0x00, 0x00])
_COMMAND_ALL_UP: bytearray = bytearray([0x01, 0x00])
_COMMAND_STOP_MOVEMENT: bytearray = bytearray([0xFF, 0x00])

_COMMAND_HEAD_UP: bytearray = bytearray([0x0B, 0x00])
_COMMAND_HEAD_DOWN: bytearray = bytearray([0x0A, 0x00])
_COMMAND_FOOT_UP: bytearray = bytearray([0x09, 0x00])
_COMMAND_FOOT_DOWN: bytearray = bytearray([0x08, 0x00])
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

    async def set_ble_device(self, client):
        self.logger.warning("Connectin to bed; %s", self.mac_address)
        self.client = BleakClient(address_or_ble_device=self.mac_address)
        await self.client.connect()


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
        await self._move_head_to(position)

    async def move_foot_rest_to(self, position: float):
        pass

    def stop(self):
        pass

    async def _move_head_to(self, position):
        while abs(self.head_position - position) > 1.5:
            self.logger.warning(
                "Current head position: %s - Moving to: %s",
                self.head_position,
                position,
            )
            if self.head_position < position:
                await self._head_up()
            else:
                await self._head_down()

    async def _head_up(self):
        """Move the head section of the bed up."""
        await self._write_char(_COMMAND_HEAD_UP)

        # Update state
        self.head_position = min(100, self.head_position + self.head_increment)
        self.head_position = round(self.head_position, 2)

    async def _head_down(self):
        """Move the head section of the bed down."""
        await self._write_char(_COMMAND_HEAD_DOWN)

        # Update state
        self.head_position = max(0, self.head_position - self.head_increment)
        self.head_position = round(self.head_position, 2)

    async def _connect_bed(self):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping connecting.")
            return
        
        if self.client:
            return

        while self.client.is_connected is False:
            try:
                self.logger.warning("Attempting to connect to bed.")
                await self.client.connect()
                self.logger.warning("Connected to bed.")
                self.is_connected = True
                self._print_characteristics()
                self.logger.warning("Connected to bed.")
                # Schedule delayed_function to run after 20 seconds
                timer = threading.Timer(20, self.disconnect_callback)
                timer.start()
                self.last_time_used = time.time()
                return
            except Exception as ex:
                self.logger.warning("Error connecting to bed", ex)
            self.logger.warning("Error connecting to bed, retrying in one second.")
            await asyncio.sleep(1)

    async def _write_char(self, cmd: bytearray):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping writing.")
            return
        self.logger.warning(f"Is connected: {self.client.is_connected}")
        
        self.logger.debug(f"Attempting to transmit command bytes: {cmd}")
        try:
            await self.client.write_gatt_char(
                _UUID_COMMAND,
                cmd,
                response=False,
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
