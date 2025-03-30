"""High level helper class to organise methods for performing actions with a Linak Bed."""

import asyncio
from enum import Enum
import logging
import threading
import time

from bleak import BleakClient

from homeassistant.components import bluetooth
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
    last_time_used: int = 0
    stop_actions: bool = False
    _lock = asyncio.Lock()
    _disconnect_task = None
    hass = None

    moving_foot_active: bool = False
    moving_head_active: bool = False
    moving_head_to_position: 0
    moving_foot_to_position: 0


    def __init__(self, mac_address: str, device_name: str, logger: Logger, hass):
        self.mac_address = mac_address
        self.device_name = device_name
        self._disconnect_task = None
        self.logger = logger  # logging.getLogger(__name__)
        self.hass = hass
        self.head_increment = (
            100 / 130
        )  # Number of commands required to go from 0% to 100%
        self.feet_increment = 100 / 95

        # "State" - assume bed is in flat position on boot
        self.head_position = 0
        self.feet_position = 0
        self.stop_actions = False
        self.light_status = False
        self.client = None

    async def set_ble_device(self, client):
        self.logger.warning("Connecting to bed; %s", self.mac_address)
        if self.client is not None:
            self.logger.warning("Already connected to bed.")
            await self._connect_bed()

        else:
            self.client = BleakClient(address_or_ble_device=self.mac_address, use_bonding=True)
            await self._connect_bed()

    async def set_flat(self):
        self.logger.warning("Move bed to flat position.")
        await self._connect_bed()
        
        await self._move_to_flat()

    async def disconnect_callback(self):
        if self.client is None:
            self.logger.warning("Not connected, skipping disconnect.")
            return
        time_now = time.time()
        self.logger.warning("Disconnected from bed.", (time_now - self.last_time_used) > 4)
        if (time_now - self.last_time_used) > 4:
            self.logger.warning("Disconnecting from bed.")
            await self.client.disconnect()
            self.logger.warning("Disconnected from bed.")

    async def disconnect_callback_sync(self):
        if self.client is None:
            self.logger.warning("Not connected, skipping disconnect.")
            return
        time_now = time.time()
        self.logger.warning("Disconnected from bed.", (time_now - self.last_time_used) > 4)
        if (time_now - self.last_time_used) > 4:
            self.logger.warning("Disconnecting from bed.")
            self.client.disconnect()
            self.logger.warning("Disconnected from bed.")

    def set_max(self):
        self.set_max_head()
        self.set_max_foot()

    async def set_flat_head(self):
        await self.move_head_rest_to(0)

    async def set_max_head(self):
        await self.move_head_rest_to(100)

    async def set_flat_foot(self):
        await self.move_foot_rest_to(0)

    async def set_max_foot(self):
        await self.move_foot_rest_to(100)

    async def move_head_rest_to(self, position: float):
        self.logger.warning("Move head rest to %s", position)
        self.moving_head_to_position = position
        
        await self._connect_bed()
        if self.moving_head_active:
            self.logger.warning("Head movement already in progress.")
            return
        
        try:
            self.moving_head_active = True
            await self._move_head_to()
        except Exception as ex:
            self.logger.error("Error moving head to position: %s", ex)
        finally:
            self.moving_head_active = False



    async def move_foot_rest_to(self, position: float):
        self.moving_foot_to_position = position
        if self.moving_foot_active:
            self.logger.warning("Foot movement already in progress.")
            return

        try: 
            self.moving_foot_active = True

            self.stop_actions = False
            max_attempts = 500


            await self._connect_bed()

            while abs(self.feet_position - self.moving_foot_to_position) > 1.5:
                max_attempts -= 1
                if max_attempts == 0:
                    self.logger.error("Failed to move foot to position.")
                    break
                if self.stop_actions:
                    break
                self.logger.warning(
                    "Current foot position: %s - Moving to: %s",
                    self.feet_position,
                    self.moving_foot_to_position,
                )
                if self.feet_position < self.moving_foot_to_position:
                    await self._foot_up()
                else:
                    await self._foot_down()
        except Exception as ex:
            self.logger.error("Error moving foot to position: %s", ex)
        finally:
            self.moving_foot_active = False

    async def stop(self):
        self.stop_actions = True

    async def _schedule_disconnect(self):
        self.logger.info("Scheduling disconnect")
        try:
           await asyncio.sleep(20)
           await self._disconnect_bed()
        except asyncio.CancelledError:
           self.logger.info("Bed disconnect task was canceled.")


    async def _move_head_to(self):
        self.stop_actions = False
        max_attempts = 500

        while abs(self.head_position - self.moving_head_to_position) > 1.5:
            max_attempts -= 1
            if max_attempts == 0:
                self.logger.error("Failed to move head to position.")
                break
            if self.stop_actions:
                break
            self.logger.warning(
                "Current head position: %s - Moving to: %s",
                self.head_position,
                self.moving_head_to_position,
            )
            if self.head_position < self.moving_head_to_position:
                await self._head_up()
            else:
                await self._head_down()

    async def _move_to_flat(self):
        self.stop_actions = False
        max_attempts = 500
        self.head_position += 50
        self.feet_position += 50
        while abs(self.head_position) > 1.5 or abs(self.feet_position) > 1.5:
            max_attempts -= 1
            if max_attempts == 0:
                self.logger.error("Failed to move head to position.")
                break
            if self.stop_actions:
                break
            self.logger.warning("Moving bed down position")                
            await self._all_down()


    async def _head_up(self):
        """Move the head section of the bed up."""
        await self._write_char(_COMMAND_HEAD_UP)

        # Update state
        self.head_position = min(100, self.head_position + self.head_increment)
        self.head_position = round(self.head_position, 2)

    async def _all_down(self):
        """Move the head section of the bed up."""
        await self._write_char(_COMMAND_ALL_DOWN)

        # Update state
        self.head_position = max(0, self.head_position - self.head_increment)
        self.head_position = round(self.head_position, 2)
        self.feet_position = max(0, self.feet_position - self.feet_increment)
        self.feet_position = round(self.feet_position, 2)

    async def _head_down(self):
        """Move the head section of the bed down."""
        await self._write_char(_COMMAND_HEAD_DOWN)

        # Update state
        self.head_position = max(0, self.head_position - self.head_increment)
        self.head_position = round(self.head_position, 2)

    async def _foot_up(self):
        """Move the foot section of the bed up."""
        await self._write_char(_COMMAND_FOOT_UP)

        # Update state
        self.feet_position = min(100, self.feet_position + self.feet_increment)
        self.feet_position = round(self.feet_position, 2)

    async def _foot_down(self):
        """Move the foot section of the bed down."""
        await self._write_char(_COMMAND_FOOT_DOWN)

        # Update state
        self.feet_position = max(0, self.feet_position - self.feet_increment)
        self.feet_position = round(self.feet_position, 2)

    async def _disconnect_bed(self):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping disconnect.")
            return

        time_now = time.time()
        if (time_now - self.last_time_used) > 4 and self.client.is_connected:
            self.logger.warning("Disconnecting from bed.")
            await self.client.disconnect()
            self.logger.warning("Disconnected from bed.")
        else:
            if (time_now - self.last_time_used) < 4:
                self.logger.warning("Not disconnecting, bed was used recently.")
                

                async with self._lock:
                    if self._disconnect_task:
                        self._disconnect_task.cancel()
                    self._disconnect_task = asyncio.create_task(self._schedule_disconnect())

            self.logger.warning("Skipping disconnect. %s", self.client.is_connected)


    async def _connect_bed(self):
        if self.client is None:
            self.logger.warning("BLE device not found, skipping connecting.")
            return
        
        attempts = 0
        self.logger.warning("Is connected: %s", self.client.is_connected)
        while not self.client.is_connected:
            try:
                attempts += 1
                if attempts > 6:
                    self.logger.warning("Failed to connect to bed after 6 attempts.")
                    break
                
                self.logger.warning("Attempting to connect to bed.")
                device = bluetooth.async_ble_device_from_address(
                    self.hass, self.mac_address, connectable=True
                )
                #self.client = BleakClient(address_or_ble_device=self.mac_address)
                async with self._lock:
                    if self._disconnect_task:
                        self._disconnect_task.cancel()
                    self.logger.warning("Connected to bed.")
                    await self.client.connect()

                    # wait for gatt authorisation   
                    gatt_attempts = 0                 
                    while gatt_attempts < 10:
                        try:
                            gatt_attempts += 1
                            
                            services = await self.client.get_services()
                            self.logger.warning("Services retrieved successfully")
                            for service in services:
                                self.logger.warning(service)
       
                        except Exception as ex:
                            self.logger.warning("No auth: %s", ex)
                            await asyncio.sleep(1)
                        
                    self._disconnect_task = asyncio.create_task(self._schedule_disconnect())
                    self.logger.warning("Connected.")
                    await asyncio.sleep(1.5)

 
               
                self.last_time_used = time.time()
                return
            except Exception as ex:
                self.logger.warning("Error connecting to bed: %s", ex)
            self.logger.warning("Error connecting to bed, retrying in one second.")
            await asyncio.sleep(5)
        self.last_time_used = time.time()


    async def _write_char(self, cmd: bytearray):
        self.last_time_used = time.time()

        if self.client is None:
            self.logger.warning("BLE device not found, skipping writing.")
            return
        if not self.client.is_connected:
            self.logger.warning("Not connected, skipping writing.")
            return
        
        self.logger.debug(f"Attempting to transmit command bytes: {cmd}")
        try:
            await self.client.write_gatt_char(
                _UUID_COMMAND,
                cmd,
                response=True,
            )
            await asyncio.sleep(0.1)
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

#    def _print_characteristics(self):
 #       pass
        # try:
        #     for service in self.device.getServices():
        #         for chara in service.getCharacteristics():
        #             self.logger.debug("Characteristic UUID: %s" % chara.uuid)
        #             self.logger.debug("Handle: 0x%04x" % chara.getHandle())
        #             properties = chara.propertiesToString()
        #             self.logger.debug("Properties: %s" % properties)
        #             self.logger.debug(f"{'-'*58}")
        # except Exception as e:
        #     self.logger.error("Error accessing characteristic: %s" % str(e))
