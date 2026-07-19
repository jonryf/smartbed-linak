"""Simulation test for the LinakBed movement engine.

Stubs out bleak and emulates a Linak control box: motors advance while a move
command is being refreshed, and coast to a halt when commands stop arriving.
"""

import asyncio
import importlib.util
import struct
import sys
import types

# ---------------------------------------------------------------- bleak stubs

bleak = types.ModuleType("bleak")
bleak_backends = types.ModuleType("bleak.backends")
bleak_backends_device = types.ModuleType("bleak.backends.device")
bleak_exc = types.ModuleType("bleak.exc")


class BLEDevice:  # noqa: D101
    def __init__(self, address="AA:BB", name="stub"):
        self.address = address
        self.name = name


class BleakError(Exception):  # noqa: D101
    pass


bleak_backends_device.BLEDevice = BLEDevice
bleak_exc.BleakError = BleakError
bleak.backends = bleak_backends
sys.modules["bleak"] = bleak
sys.modules["bleak.backends"] = bleak_backends
sys.modules["bleak.backends.device"] = bleak_backends_device
sys.modules["bleak.exc"] = bleak_exc

brc = types.ModuleType("bleak_retry_connector")


class BleakClientWithServiceCache:  # noqa: D101
    pass


async def establish_connection(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError


brc.BleakClientWithServiceCache = BleakClientWithServiceCache
brc.establish_connection = establish_connection
sys.modules["bleak_retry_connector"] = brc

# ------------------------------------------------- load the component modules

PKG_DIR = sys.argv[1] if len(sys.argv) > 1 else "custom_components/linak_bed_controller"
pkg = types.ModuleType("lbc")
pkg.__path__ = [PKG_DIR]
sys.modules["lbc"] = pkg
for mod_name in ("const", "bed_ble"):
    spec = importlib.util.spec_from_file_location(f"lbc.{mod_name}", f"{PKG_DIR}/{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"lbc.{mod_name}"] = mod
    spec.loader.exec_module(mod)

bed_ble = sys.modules["lbc.bed_ble"]
const = sys.modules["lbc.const"]

# Speed the test up 10x
bed_ble.KEEPALIVE_INTERVAL = 0.02
bed_ble.STALL_TIMEOUT = 0.3
bed_ble.POSITION_PROBE_TIMEOUT = 0.3
bed_ble.MAX_MOVE_DURATION = 8.0
bed_ble.DEAD_RECKON_RESYNC_SECONDS = 0.2

RAW_MAX_HEAD = 820
RAW_MAX_FOOT = 548
# Raw units the actuator travels per keep-alive tick while commanded.
STEP = 20
# How long a motor keeps running after the last command (Linak burst behavior).
BURST_TICKS = 3


class FakeControlBox:
    """Emulates the control box attached to a LinakBed instance."""

    def __init__(self, bed, head_raw=0, foot_raw=0, true_max_head=RAW_MAX_HEAD):
        self.bed = bed
        self.pos = {"head": head_raw, "foot": foot_raw}
        self.true_max = {"head": true_max_head, "foot": RAW_MAX_FOOT}
        self.burst = {"head": 0, "foot": 0}  # (direction, remaining ticks)
        self.dir = {"head": 0, "foot": 0}
        self.notify_enabled = {"head": True, "foot": True}
        self.writes = []
        self.stops = 0
        self.is_connected = True
        self._task = None

    def start(self):
        self._task = asyncio.get_running_loop().create_task(self._tick())

    async def _tick(self):
        while True:
            await asyncio.sleep(0.02)
            for m in ("head", "foot"):
                if self.burst[m] > 0:
                    self.burst[m] -= 1
                    old = self.pos[m]
                    self.pos[m] = max(0, min(self.true_max[m], old + self.dir[m] * STEP))
                    speed = self.dir[m] * 100 if self.pos[m] != old else 0
                    self._notify(m, speed)
                elif self.dir[m] != 0:
                    self.dir[m] = 0
                    self._notify(m, 0)

    def _notify(self, m, speed):
        if not self.notify_enabled[m]:
            return
        motor = self.bed.head if m == "head" else self.bed.foot
        data = bytearray(struct.pack("<Hh", self.pos[m], speed))
        self.bed._handle_notification(motor, data)

    async def write_gatt_char(self, char, payload, response=True):
        code = payload[0]
        self.writes.append(code)
        if code == 0xFF:
            self.stops += 1
            self.burst = {"head": 0, "foot": 0}
            for m in ("head", "foot"):
                if self.dir[m] != 0:
                    self.dir[m] = 0
                    self._notify(m, 0)
            return
        head_dir, foot_dir = next(
            (k for k, v in bed_ble._MOVE_CODES.items() if v == code), (0, 0)
        )
        if head_dir:
            self.dir["head"] = head_dir
            self.burst["head"] = BURST_TICKS
        else:
            self.burst["head"] = 0
        if foot_dir:
            self.dir["foot"] = foot_dir
            self.burst["foot"] = BURST_TICKS
        else:
            self.burst["foot"] = 0


def make_bed(head_raw=0, foot_raw=0, true_max_head=RAW_MAX_HEAD):
    bed = bed_ble.LinakBed("AA:BB", "TestBed", RAW_MAX_HEAD, RAW_MAX_FOOT)
    box = FakeControlBox(bed, head_raw, foot_raw, true_max_head)
    bed._client = box  # duck-typed: is_connected + write_gatt_char
    bed.head.raw = head_raw
    bed.foot.raw = foot_raw
    bed.head.has_feedback = True
    bed.foot.has_feedback = True
    return bed, box


async def wait_idle(bed, timeout=10.0):
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        if bed.head.target_pct is None and bed.foot.target_pct is None and not bed._wake_event.is_set():
            await asyncio.sleep(0.1)
            if bed.head.target_pct is None and bed.foot.target_pct is None:
                return
        await asyncio.sleep(0.02)
    raise AssertionError("bed never went idle")


async def test_move_head_to_50():
    bed, box = make_bed()
    box.start()
    await bed.move_to(head=50)
    await wait_idle(bed)
    pct = bed.head.position_pct
    assert abs(pct - 50) <= 3, f"head ended at {pct}"
    assert box.stops >= 1, "no STOP sent"
    assert 0x0B in box.writes, "head-up command never sent"
    print(f"  ok: head moved to {pct:.1f}% with {box.writes.count(0x0B)} keep-alives, {box.stops} stop(s)")


async def test_combined_move():
    bed, box = make_bed(head_raw=800, foot_raw=0)
    box.start()
    await bed.move_to(head=0, foot=100)
    await asyncio.sleep(0.1)
    assert 0x36 in box.writes, f"combined head-down+foot-up (0x36) not used: {set(box.writes)}"
    await wait_idle(bed)
    assert bed.head.position_pct <= 3, f"head at {bed.head.position_pct}"
    assert bed.foot.position_pct >= 97, f"foot at {bed.foot.position_pct}"
    print(f"  ok: combined move -> head {bed.head.position_pct:.1f}%, foot {bed.foot.position_pct:.1f}%")


async def test_stop_mid_move():
    bed, box = make_bed()
    box.start()
    await bed.move_to(head=100)
    await asyncio.sleep(0.2)
    await bed.stop()
    await wait_idle(bed)
    pct = bed.head.position_pct
    assert 5 < pct < 95, f"expected mid-travel stop, got {pct}"
    frozen = pct
    await asyncio.sleep(0.3)
    assert bed.head.position_pct == frozen, "kept moving after stop"
    print(f"  ok: stopped mid-move at {pct:.1f}%")


async def test_partial_stop():
    bed, box = make_bed()
    box.start()
    await bed.move_to(head=100, foot=100)
    await asyncio.sleep(0.2)
    await bed.stop("head")
    assert bed.foot.target_pct is not None, "foot target lost on partial stop"
    await wait_idle(bed)
    assert bed.foot.position_pct >= 97, f"foot at {bed.foot.position_pct}"
    assert bed.head.position_pct < 95, "head should have stopped early"
    print(f"  ok: partial stop -> head {bed.head.position_pct:.1f}%, foot {bed.foot.position_pct:.1f}%")


async def test_end_stop_learning():
    # Bed whose real top (700) is below the assumed raw_max (820):
    # aiming for 100% must stall at the top and re-learn raw_max.
    bed, box = make_bed(true_max_head=700)
    learned = []
    bed.set_raw_max_listener(lambda: learned.append(bed.head.raw_max))
    box.start()
    await bed.move_to(head=100)
    await wait_idle(bed)
    assert bed.head.raw_max == 700, f"raw_max not learned: {bed.head.raw_max}"
    assert abs(bed.head.position_pct - 100) < 1
    assert learned, "raw_max listener not fired"
    print(f"  ok: end-stop learning -> raw_max {bed.head.raw_max}, position {bed.head.position_pct:.0f}%")


async def test_obstruction_does_not_recalibrate():
    # Motor jams at raw 300 (far below the known 820 range) while targeting
    # 100%: must give up WITHOUT rewriting raw_max.
    bed, box = make_bed()
    learned = []
    bed.set_raw_max_listener(lambda: learned.append(bed.head.raw_max))
    box.start()
    box.true_max["head"] = 300  # simulated obstruction
    await bed.move_to(head=100)
    await wait_idle(bed)
    assert bed.head.raw_max == RAW_MAX_HEAD, f"raw_max corrupted to {bed.head.raw_max}"
    assert not learned, "obstruction stall wrongly persisted a new raw_max"
    print(f"  ok: obstruction at raw 300 cancelled move, raw_max still {bed.head.raw_max}")


def make_dead_reckon_bed():
    """Bed whose head motor has no position feedback at all."""
    bed, box = make_bed()
    bed.head.raw = None
    bed.head.has_feedback = False
    bed.head.full_travel_s = 0.6
    box.notify_enabled["head"] = False
    return bed, box


async def test_dead_reckon_open_close():
    bed, box = make_dead_reckon_bed()
    box.start()
    await bed.move_to(head=100)
    await wait_idle(bed)
    assert bed.head.position_pct == 100, f"est after open: {bed.head.position_pct}"
    assert 0x0B in box.writes, "head-up never commanded"
    up_writes = box.writes.count(0x0B)
    # Overdrive must keep commanding past the estimate reaching 100 (~30 ticks
    # for travel + ~10 ticks of resync margin).
    assert up_writes > 35, f"no end-stop overdrive, only {up_writes} up writes"
    await bed.move_to(head=0)
    await wait_idle(bed)
    assert bed.head.position_pct == 0, f"est after close: {bed.head.position_pct}"
    print(f"  ok: dead-reckon open/close synced at both ends ({up_writes} up writes)")


async def test_dead_reckon_set_position():
    bed, box = make_dead_reckon_bed()
    box.start()
    await bed.move_to(head=50)
    await wait_idle(bed)
    est = bed.head.position_pct
    assert 40 <= est <= 60, f"est {est} far from 50"
    assert box.stops >= 1, "no STOP after dead-reckoned move"
    frozen = est
    await asyncio.sleep(0.3)
    assert bed.head.position_pct == frozen, "est kept integrating after stop"
    print(f"  ok: dead-reckon set-position landed at {est:.1f}%")


async def test_new_target_during_finish():
    # Regression for the finish/new-target race: fire a new move right as the
    # previous one completes, repeatedly.
    bed, box = make_bed()
    box.start()
    for target in (30, 60, 20, 80):
        await bed.move_to(head=target)
        await wait_idle(bed)
        assert abs(bed.head.position_pct - target) <= 3, (
            f"target {target} ended at {bed.head.position_pct}"
        )
    print("  ok: sequential retargeting converged every time")


async def test_write_failure_aborts():
    bed, box = make_bed()
    box.start()
    await bed.move_to(head=100)
    await asyncio.sleep(0.1)

    async def failing_write(*a, **k):
        raise BleakError("gone")

    box.write_gatt_char = failing_write
    await asyncio.sleep(1.0)  # write failure + STOP retry backoff need ~0.4s
    assert bed.head.target_pct is None, "target not cleared after write failure"
    print("  ok: write failure aborts movement cleanly")


async def main():
    for test in (
        test_move_head_to_50,
        test_combined_move,
        test_stop_mid_move,
        test_partial_stop,
        test_end_stop_learning,
        test_obstruction_does_not_recalibrate,
        test_dead_reckon_open_close,
        test_dead_reckon_set_position,
        test_new_target_during_finish,
        test_write_failure_aborts,
    ):
        print(test.__name__)
        await test()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
