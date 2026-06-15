#!/usr/bin/env python3
"""One batched verification session for PROTOCOL.md open items:
  1. vibrate via Alert Level 0x03 (confirm buzz)
  2. capture raw 13-byte realtime-steps packet (decode tail)
  3. subscribe device events; press the band button to capture event bytes
  4. write config 24h toggle, capture the ack on h0003
"""
import asyncio
from bleak import BleakClient
from band import resolve, UUID_AUTH, UUID_STEPS, huami
from miband5 import MiBand5, UUID_CONFIG, UUID_DEVICE_EVENT, DEVICE_EVENTS

UUID_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"


async def main():
    band = await MiBand5.open()
    c = band.c
    print("AUTH OK ✅\n")
    try:
        b = await band.battery()
        print(f"Battery: {b.level}% charging={b.charging}\n")

        # 1. vibrate 0x03
        print(">>> VIBRATE 0x03 for 1.5s — watch the band")
        await c.write_gatt_char(UUID_ALERT, b"\x03", response=False)
        await asyncio.sleep(1.5)
        await c.write_gatt_char(UUID_ALERT, b"\x00", response=False)
        print("    sent (buzz?)\n")

        # 2. raw realtime steps (read current 13-byte value directly)
        print(">>> Raw realtime-steps packet:")
        try:
            d = bytes(await c.read_gatt_char(UUID_STEPS))
            print(f"    {d.hex(' ')}  (len={len(d)}, steps_u16={int.from_bytes(d[1:3],'little')})")
            if len(d) >= 13:
                print(f"    tail bytes [3:13] = {d[3:13].hex(' ')}  (distance/calories?)")
        except Exception as e:
            print(f"    steps read failed: {e}")

        # 3. config ack (write-WITHOUT-response!)
        print("\n>>> CONFIG: toggle 24h time, capture ack on h0003")
        def cfg_cb(_h, d):
            print(f"    config ack: {bytes(d).hex(' ')}")
        await c.start_notify(UUID_CONFIG, cfg_cb)
        try:
            await c.write_gatt_char(UUID_CONFIG, bytes([0x06, 0x02, 0x00, 0x01]), response=False)
        except Exception as e:
            print(f"    config write failed: {e}")

        # 4. device events — capture window
        print("\n>>> DEVICE EVENTS — press the band button a few times (20s)")
        def ev_cb(_h, d):
            name = DEVICE_EVENTS.get(d[0], f"unknown_{d[0]:#04x}") if d else "?"
            print(f"    event: {bytes(d).hex(' ')}  -> {name}")
        await c.start_notify(UUID_DEVICE_EVENT, ev_cb)

        await asyncio.sleep(20)
        print("\nDone.")
    finally:
        await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
