"""BLE control of a Linak bed control box with closed-loop positioning.

Design notes:
- The control box only runs its motors for a short burst per command, so
  continuous movement requires refreshing the move command every few hundred
  milliseconds (the keep-alive loop in `_movement_cycle`).
- Real actuator positions are streamed as notifications on the reference
  output characteristics; movement is closed-loop against those, never
  estimated by counting commands.
- The connection is kept open permanently. Reconnection policy lives in the
  coordinator; this class reports disconnects through a listener.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CHAR_COMMAND,
    CHAR_POSITION_FOOT,
    CHAR_POSITION_HEAD,
    CONNECTION_TIMEOUT,
    DEAD_RECKON_FULL_TRAVEL,
    DEAD_RECKON_RESYNC_SECONDS,
    DEADBAND_PCT,
    END_STOP_TOLERANCE,
    KEEPALIVE_INTERVAL,
    MAX_MOVE_DURATION,
    POSITION_PROBE_TIMEOUT,
    STALL_TIMEOUT,
    STOP_WRITE_RETRIES,
)

_LOGGER = logging.getLogger(__name__)

COMMAND_STOP = 0xFF

# Combined move commands, keyed by (head_direction, foot_direction) where
# 1 = up, -1 = down, 0 = idle. Codes verified against the Linak hand-control
# protocol (back motor = head rest, leg motor = foot rest on 2-motor beds).
_MOVE_CODES: dict[tuple[int, int], int] = {
    (1, 0): 0x0B,
    (-1, 0): 0x0A,
    (0, 1): 0x09,
    (0, -1): 0x08,
    (1, 1): 0x01,  # "all up" — confirmed on TD4
    (-1, -1): 0x00,  # "all down" — confirmed on TD4
    (1, -1): 0x35,
    (-1, 1): 0x36,
}


@dataclass
class Motor:
    """State of one actuator."""

    name: str
    position_char: str
    raw_max: int
    raw: int | None = None
    speed: int = 0
    target_pct: float | None = None
    commanded_dir: int = 0
    has_feedback: bool = False
    last_raw_change: float = field(default=0.0, repr=False)
    # Dead-reckoning fallback state (used only when has_feedback is False):
    # estimated position (flat assumed at startup, like the physical remote's
    # mental model), and the deadline for overdriving into an end stop.
    est_pct: float = 0.0
    full_travel_s: float = DEAD_RECKON_FULL_TRAVEL
    overdrive_deadline: float | None = field(default=None, repr=False)

    @property
    def position_pct(self) -> float | None:
        """Current position as 0-100, or None if never observed."""
        if self.raw is not None:
            return min(100.0, self.raw / self.raw_max * 100)
        if not self.has_feedback:
            return self.est_pct
        return None

    @property
    def is_moving_up(self) -> bool:
        return self.speed > 0 or self.commanded_dir > 0

    @property
    def is_moving_down(self) -> bool:
        return self.speed < 0 or self.commanded_dir < 0


class LinakBed:
    """One Linak control box (2 motors: head and foot)."""

    def __init__(
        self,
        address: str,
        name: str,
        raw_max_head: int,
        raw_max_foot: int,
    ) -> None:
        self.address = address
        self.name = name
        self.head = Motor("head", CHAR_POSITION_HEAD, raw_max_head)
        self.foot = Motor("foot", CHAR_POSITION_FOOT, raw_max_foot)
        self._client: BleakClientWithServiceCache | None = None
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._mover_task: asyncio.Task | None = None
        self._wake_event = asyncio.Event()
        self._expected_disconnect = False
        self._supports_write_no_response = False
        self._state_callbacks: list[Callable[[], None]] = []
        self._disconnect_listener: Callable[[], None] | None = None
        self._raw_max_listener: Callable[[], None] | None = None

    # ---------------------------------------------------------------- state

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def register_state_callback(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired on any position/connection change."""
        self._state_callbacks.append(cb)

        def _unregister() -> None:
            self._state_callbacks.remove(cb)

        return _unregister

    def set_disconnect_listener(self, cb: Callable[[], None]) -> None:
        self._disconnect_listener = cb

    def set_raw_max_listener(self, cb: Callable[[], None]) -> None:
        """Called when a learned raw range should be persisted."""
        self._raw_max_listener = cb

    def _fire_state_callbacks(self) -> None:
        for cb in self._state_callbacks:
            try:
                cb()
            except Exception:  # noqa: BLE001 - never let a listener break control
                _LOGGER.exception("State callback failed")

    # ----------------------------------------------------------- connection

    async def connect(self, ble_device: BLEDevice) -> None:
        """Connect and subscribe to position notifications."""
        async with self._connect_lock:
            if self.is_connected:
                return
            self._expected_disconnect = False
            _LOGGER.debug("%s: connecting", self.name)
            client = await establish_connection(
                BleakClientWithServiceCache,
                device=ble_device,
                name=self.name,
                disconnected_callback=self._handle_disconnect,
                timeout=CONNECTION_TIMEOUT,
            )
            self._client = client
            try:
                command_char = client.services.get_characteristic(CHAR_COMMAND)
                if command_char is None:
                    raise BleakError(
                        f"{self.name}: command characteristic {CHAR_COMMAND} not found"
                    )
                self._supports_write_no_response = (
                    "write-without-response" in command_char.properties
                )
                for motor in (self.head, self.foot):
                    await self._setup_motor(client, motor)
                if not (self.head.has_feedback and self.foot.has_feedback):
                    self._log_gatt_layout(client)
            except Exception:
                # Any setup failure must release the control box's single BLE
                # slot, or every future reconnect attempt is doomed.
                self._expected_disconnect = True
                self._client = None
                await self._safe_disconnect(client)
                raise
            _LOGGER.info(
                "%s: connected (head=%s%%, foot=%s%%)",
                self.name,
                _fmt_pct(self.head.position_pct),
                _fmt_pct(self.foot.position_pct),
            )
            self._fire_state_callbacks()

    async def _setup_motor(self, client: BleakClientWithServiceCache, motor: Motor) -> None:
        char = client.services.get_characteristic(motor.position_char)
        if char is None:
            motor.has_feedback = False
            _LOGGER.warning(
                "%s: no position feedback for the %s motor (characteristic %s "
                "not found); falling back to timed movement with estimated "
                "positions — drive fully down or up once to sync the estimate",
                self.name,
                motor.name,
                motor.position_char,
            )
            return
        motor.has_feedback = True
        if "read" in char.properties:
            try:
                self._decode_position(motor, await client.read_gatt_char(char))
            except BleakError as ex:
                _LOGGER.debug("%s: initial %s position read failed: %s", self.name, motor.name, ex)
        await client.start_notify(
            char, lambda _char, data, m=motor: self._handle_notification(m, data)
        )

    def _log_gatt_layout(self, client: BleakClientWithServiceCache) -> None:
        """Log the box's services/characteristics once, to aid protocol discovery.

        Only called when the expected position characteristics are missing —
        the dump shows whether this box exposes them under other UUIDs.
        """
        lines = [f"{self.name}: GATT layout (position feedback missing):"]
        for service in client.services:
            lines.append(f"  service {service.uuid}")
            lines.extend(
                f"    char {char.uuid} [{', '.join(char.properties)}]"
                for char in service.characteristics
            )
        _LOGGER.warning("\n".join(lines))

    def _handle_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        if self._expected_disconnect:
            return
        _LOGGER.warning("%s: disconnected", self.name)
        for motor in (self.head, self.foot):
            motor.speed = 0
            motor.target_pct = None
            motor.commanded_dir = 0
        if self._mover_task is not None:
            self._mover_task.cancel()
            self._mover_task = None
        self._wake_event.clear()
        self._fire_state_callbacks()
        if self._disconnect_listener:
            self._disconnect_listener()

    async def async_shutdown(self) -> None:
        """Stop movement and disconnect."""
        self._expected_disconnect = True
        if self._mover_task is not None:
            self._mover_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._mover_task
            self._mover_task = None
        self.head.target_pct = None
        self.foot.target_pct = None
        if self.is_connected:
            await self._write_stop()
        if self._client:
            await self._safe_disconnect(self._client)
            self._client = None

    async def _safe_disconnect(self, client: BleakClientWithServiceCache) -> None:
        with contextlib.suppress(BleakError, TimeoutError):
            await client.disconnect()

    # -------------------------------------------------------- notifications

    def _handle_notification(self, motor: Motor, data: bytearray) -> None:
        if self._decode_position(motor, data):
            self._fire_state_callbacks()

    def _decode_position(self, motor: Motor, data: bytearray) -> bool:
        """Update motor state from a position packet; True if anything changed."""
        if len(data) < 2:
            return False
        if len(data) >= 4:
            raw, speed = struct.unpack("<Hh", data[:4])
        else:
            raw, speed = struct.unpack("<H", data[:2])[0], 0
        changed = False
        if raw != motor.raw:
            motor.last_raw_change = asyncio.get_running_loop().time()
            motor.raw = raw
            changed = True
        if speed != motor.speed:
            motor.speed = speed
            changed = True
        if raw > motor.raw_max:
            motor.raw_max = raw
            self._notify_raw_max()
            changed = True
        return changed

    def _notify_raw_max(self) -> None:
        _LOGGER.debug(
            "%s: learned raw range head=%d foot=%d",
            self.name,
            self.head.raw_max,
            self.foot.raw_max,
        )
        if self._raw_max_listener:
            self._raw_max_listener()

    # ------------------------------------------------------------- movement

    async def move_to(self, head: float | None = None, foot: float | None = None) -> None:
        """Set target positions (0-100) and start moving. Returns immediately."""
        if not self.is_connected:
            raise BleakError(f"{self.name} is not connected")
        now = asyncio.get_running_loop().time()
        for motor, target in ((self.head, head), (self.foot, foot)):
            if target is None:
                continue
            motor.target_pct = max(0.0, min(100.0, target))
            motor.last_raw_change = now
            motor.overdrive_deadline = None
        self._wake_event.set()
        if self._mover_task is None or self._mover_task.done():
            self._mover_task = asyncio.get_running_loop().create_task(self._run_mover())
        self._fire_state_callbacks()

    async def stop(self, motor_name: str | None = None) -> None:
        """Stop one motor (by clearing its target) or the whole bed."""
        if motor_name != "foot":
            self.head.target_pct = None
        if motor_name != "head":
            self.foot.target_pct = None
        if self.head.target_pct is None and self.foot.target_pct is None:
            # Stop everything right away; the mover loop notices the cleared
            # targets within one keep-alive tick and confirms with its own STOP.
            if self.is_connected:
                await self._write_stop()
        # A partial stop needs no write: the next keep-alive command simply no
        # longer includes this motor and it halts on its own.
        self._fire_state_callbacks()

    async def _run_mover(self) -> None:
        """Persistent mover: wait for targets, run one movement cycle, repeat.

        A single long-lived task (instead of one task per movement) avoids
        races between a finishing movement and a newly requested one.
        """
        while True:
            await self._wake_event.wait()
            self._wake_event.clear()
            try:
                await self._movement_cycle()
            except Exception:  # noqa: BLE001 - the task must survive, targets must clear
                _LOGGER.exception("%s: movement aborted", self.name)
                self.head.target_pct = None
                self.foot.target_pct = None

    async def _movement_cycle(self) -> None:
        """Keep-alive command loop: refresh the move command until targets are hit."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_tick = started
        commanded = False
        try:
            while True:
                now = loop.time()
                # Advance dead-reckoned position estimates for motors that were
                # being commanded during the last tick.
                dt = now - last_tick
                last_tick = now
                for motor in (self.head, self.foot):
                    if motor.commanded_dir and not motor.has_feedback:
                        motor.est_pct = max(
                            0.0,
                            min(
                                100.0,
                                motor.est_pct
                                + motor.commanded_dir * dt / motor.full_travel_s * 100,
                            ),
                        )
                if now - started > MAX_MOVE_DURATION:
                    _LOGGER.warning("%s: movement safety timeout hit, stopping", self.name)
                    self.head.target_pct = None
                    self.foot.target_pct = None
                    break
                head_dir = self._direction(self.head, now)
                foot_dir = self._direction(self.foot, now)
                self.head.commanded_dir = head_dir
                self.foot.commanded_dir = foot_dir
                if head_dir == 0 and foot_dir == 0:
                    break
                commanded = True
                await self._write_command(_MOVE_CODES[(head_dir, foot_dir)])
                await asyncio.sleep(KEEPALIVE_INTERVAL)
        finally:
            self.head.commanded_dir = 0
            self.foot.commanded_dir = 0
            if commanded:
                await self._write_stop()
                # Movement is over; don't let a lost final speed=0 notification
                # leave the covers stuck in an opening/closing state.
                self.head.speed = 0
                self.foot.speed = 0
            self._fire_state_callbacks()

    def _direction(self, motor: Motor, now: float) -> int:
        if motor.target_pct is None:
            return 0
        if not motor.has_feedback:
            return self._dead_reckon_direction(motor, now)
        if motor.raw is None:
            # Feedback exists but no value yet (initial read failed). Nudge
            # downward briefly: the first notification then enables closed-loop
            # control. last_raw_change was stamped when the target was set.
            if now - motor.last_raw_change >= POSITION_PROBE_TIMEOUT:
                _LOGGER.warning(
                    "%s: no position feedback arrived for %s motor, cancelling move",
                    self.name,
                    motor.name,
                )
                motor.target_pct = None
                return 0
            return -1
        pct = motor.position_pct
        assert pct is not None
        delta = motor.target_pct - pct
        if abs(delta) <= DEADBAND_PCT:
            motor.target_pct = None
            return 0
        direction = 1 if delta > 0 else -1
        if motor.commanded_dir == direction and now - motor.last_raw_change > STALL_TIMEOUT:
            # The motor is commanded but no longer moving: either the physical
            # end stop or an obstruction (pinch protection cut the motor).
            if (
                direction > 0
                and motor.target_pct >= 100 - DEADBAND_PCT
                and motor.raw >= motor.raw_max * END_STOP_TOLERANCE
            ):
                # Stalled near the assumed top while aiming for 100%: treat as
                # the real top and refine the calibration. A stall well below
                # the known range is an obstruction, not the end stop.
                motor.raw_max = motor.raw
                self._notify_raw_max()
            else:
                _LOGGER.warning(
                    "%s: %s motor stalled at %.1f%% (obstruction or end stop), "
                    "giving up on target %.1f%%",
                    self.name,
                    motor.name,
                    pct,
                    motor.target_pct,
                )
            motor.target_pct = None
            return 0
        return direction

    def _dead_reckon_direction(self, motor: Motor, now: float) -> int:
        """Direction for a motor without position feedback, by timed estimate.

        When the target is an end position (0 or 100), keep driving a while
        after the estimate reaches it: the control box stops safely at the
        physical limit, and hitting it re-syncs the estimate exactly.
        """
        assert motor.target_pct is not None
        delta = motor.target_pct - motor.est_pct
        if abs(delta) <= DEADBAND_PCT:
            seeking_bottom = motor.target_pct <= DEADBAND_PCT
            seeking_top = motor.target_pct >= 100 - DEADBAND_PCT
            if seeking_bottom or seeking_top:
                if motor.overdrive_deadline is None:
                    motor.overdrive_deadline = now + DEAD_RECKON_RESYNC_SECONDS
                if now < motor.overdrive_deadline:
                    return 1 if seeking_top else -1
            motor.overdrive_deadline = None
            motor.target_pct = None
            return 0
        return 1 if delta > 0 else -1

    # --------------------------------------------------------------- writes

    async def _write_command(self, code: int) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise BleakError("not connected")
        payload = bytes([code, 0x00])
        async with self._write_lock:
            if self.head.target_pct is None and self.foot.target_pct is None:
                # A stop() overtook this queued keep-alive while it waited for
                # the write lock; sending it now would restart the motors.
                return
            # Write-without-response keeps the keep-alive cadence tight through
            # an ESP32 proxy, where a write-with-response round trip can exceed
            # the refresh interval and make movement stutter.
            await client.write_gatt_char(
                CHAR_COMMAND, payload, response=not self._supports_write_no_response
            )

    async def _write_stop(self) -> None:
        client = self._client
        if client is None or not client.is_connected:
            return
        payload = bytes([COMMAND_STOP, 0x00])
        for attempt in range(STOP_WRITE_RETRIES):
            try:
                async with self._write_lock:
                    await client.write_gatt_char(CHAR_COMMAND, payload, response=True)
            except BleakError as ex:
                # The control box halts on its own without keep-alives, but a
                # confirmed STOP is quicker, so retry a couple of times.
                _LOGGER.debug("%s: STOP write attempt %d failed: %s", self.name, attempt + 1, ex)
                await asyncio.sleep(0.1)
            else:
                return
        _LOGGER.warning("%s: STOP command could not be delivered", self.name)


def _fmt_pct(value: float | None) -> str:
    return "?" if value is None else f"{value:.0f}"
