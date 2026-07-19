# smartbed-linak

Home Assistant custom integration for beds with Linak BLE control boxes
(e.g. Nordic Dream Aura with 2× Linak controllers, each driving a head and a
foot actuator).

Each control box appears as one device with:

- **Bed Head Rest** cover — open/close/stop and set position (0–100 %)
- **Bed Foot Rest** cover — open/close/stop and set position (0–100 %)
- **Set Flat** button — moves both sections to flat

## How it works

- **Closed-loop positioning.** The integration subscribes to the control
  box's reference-output characteristics (`99fa0028` = head/back motor,
  `99fa0027` = foot/leg motor), which stream the real actuator position and
  speed. Movement targets are tracked against actual positions — the position
  in HA stays correct even when someone uses the physical remote.
- **Keep-alive movement.** Linak boxes run their motors only for a short
  burst per command, so the integration refreshes the move command every
  200 ms (using write-without-response for low latency through ESP32 BLE
  proxies) and sends a confirmed STOP when the target is reached.
- **Persistent connection.** The connection is established once and kept
  open, so commands execute immediately — no connect-on-demand delay.
  On disconnect the integration reconnects automatically with backoff, and a
  BLE advertisement from the bed triggers an immediate retry.
- **Auto-calibration.** The raw actuator range is learned from notifications
  and end-stop detection, then persisted in the config entry options.
- **Timed fallback.** If a control box exposes no position characteristics at
  all (reported for some TD4 Standard configurations), the integration falls
  back to timed movement with estimated positions: open/close/stop and set
  position keep working, the estimate assumes a flat bed at startup, and it
  re-syncs automatically every time a section is driven fully up or down
  (the box stops itself at the physical limit). The log states clearly which
  mode each motor is running in.

## Installation

1. Install via HACS (custom repository) or copy
   `custom_components/linak_bed_controller` into your `config/custom_components`.
2. Restart Home Assistant.
3. Beds in range are auto-discovered (Settings → Devices & Services). You can
   also add one manually via **Add Integration → Linak Bed Controller**, which
   lists discovered control boxes.

## Bluetooth setup

Any HA-supported Bluetooth path works. Recommended: one ESP32 running the
ESPHome Bluetooth proxy placed near each control box — see
[esp32_optimization.yaml](esp32_optimization.yaml). Key points:

- Use the `esp-idf` framework and `power_save_mode: none`.
- `bluetooth_proxy: active: true` is required (the integration keeps an
  active connection).
- An ESP32 proxy supports ~3 concurrent connections; one bed per proxy plus
  headroom is comfortable.

## Troubleshooting / protocol validation

[scripts/probe_bed.py](scripts/probe_bed.py) is a standalone script (only
needs `bleak`) that connects to a control box, dumps its GATT layout, streams
position notifications, and can send a 1-second test movement. Use it to
verify which characteristics your control box exposes if something doesn't
behave — run it on a machine with Bluetooth in range while HA is not holding
the connection (disable the bed's config entry first).

If movement won't start at all, the control box may require one-time
Bluetooth pairing: put it in pairing mode (see the bed manual) and pair from
the host once.
