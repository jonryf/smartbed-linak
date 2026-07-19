#!/usr/bin/env python3
"""Standalone probe for a Linak bed control box.

Validates the assumptions the integration is built on, directly against your
hardware, without Home Assistant in the loop. Run it on any machine with
Bluetooth in range of the bed (e.g. the Raspberry Pi, with HA stopped or the
bed's config entry disabled so the connection is free).

Usage:
    pip install bleak
    python3 probe_bed.py --scan                     # find control boxes
    python3 probe_bed.py <ADDRESS>                  # dump GATT + watch positions
    python3 probe_bed.py <ADDRESS> --test-move      # 1s head-up pulse, then STOP

While watching, move the bed with the physical remote and note the raw
position ranges printed for each characteristic (needed only if the
integration's auto-calibration ever looks off).
"""

import argparse
import asyncio
import struct
import sys

from bleak import BleakClient, BleakScanner

CONTROL_SERVICE = "99fa0001-338a-1024-8a49-009c0215f78a"
COMMAND_CHAR = "99fa0002-338a-1024-8a49-009c0215f78a"
OUTPUT_SERVICE = "99fa0020-338a-1024-8a49-009c0215f78a"

# All possible reference-output channels; a 2-motor bed typically uses
# 0x0027 (leg = foot rest) and 0x0028 (back = head rest).
OUTPUT_CHANNELS = {f"99fa002{i}-338a-1024-8a49-009c0215f78a": f"out{i}" for i in range(1, 9)}

CMD_HEAD_UP = bytes([0x0B, 0x00])
CMD_STOP = bytes([0xFF, 0x00])


async def scan() -> None:
    print("Scanning 10s for Linak control boxes...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    found = False
    for device, adv in devices.values():
        if CONTROL_SERVICE in (adv.service_uuids or []):
            print(f"  {device.address}  {device.name or '?'}  RSSI={adv.rssi}")
            found = True
    if not found:
        print("  none found (bed already connected elsewhere, or out of range?)")


def decode(data: bytearray) -> str:
    if len(data) >= 4:
        raw, speed = struct.unpack("<Hh", data[:4])
        return f"raw={raw} speed={speed}"
    if len(data) >= 2:
        return f"raw={struct.unpack('<H', data[:2])[0]}"
    return f"bytes={data.hex()}"


async def probe(address: str, test_move: bool, watch_seconds: float) -> None:
    print(f"Connecting to {address}...")
    async with BleakClient(address, timeout=30.0) as client:
        print("Connected. GATT layout:\n")
        for service in client.services:
            print(f"  service {service.uuid}")
            for char in service.characteristics:
                print(f"    char {char.uuid}  [{', '.join(char.properties)}]")
        print()

        subscribed = []
        for uuid, label in OUTPUT_CHANNELS.items():
            char = client.services.get_characteristic(uuid)
            if char is None:
                continue
            if "read" in char.properties:
                try:
                    value = await client.read_gatt_char(char)
                    print(f"  {label} ({uuid[:13]}): {decode(value)}")
                except Exception as ex:  # noqa: BLE001
                    print(f"  {label}: read failed: {ex}")
            if "notify" in char.properties:
                def handler(_char, data, label=label):
                    print(f"  notify {label}: {decode(data)}")
                await client.start_notify(char, handler)
                subscribed.append(uuid)
        print(f"\nSubscribed to: {[OUTPUT_CHANNELS[u] for u in subscribed]}")

        if test_move:
            print("\nTest move: head up for 1s (commands refreshed every 200ms)...")
            for _ in range(5):
                await client.write_gatt_char(COMMAND_CHAR, CMD_HEAD_UP, response=False)
                await asyncio.sleep(0.2)
            await client.write_gatt_char(COMMAND_CHAR, CMD_STOP, response=True)
            print("STOP sent.")

        print(f"\nWatching notifications for {watch_seconds:.0f}s — "
              "move the bed with the physical remote now.")
        await asyncio.sleep(watch_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", nargs="?", help="Bluetooth address of the control box")
    parser.add_argument("--scan", action="store_true", help="scan for control boxes")
    parser.add_argument("--test-move", action="store_true", help="pulse head-up for 1s")
    parser.add_argument("--watch", type=float, default=60.0, help="seconds to watch notifications")
    args = parser.parse_args()

    if args.scan or not args.address:
        asyncio.run(scan())
        return
    try:
        asyncio.run(probe(args.address, args.test_move, args.watch))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
