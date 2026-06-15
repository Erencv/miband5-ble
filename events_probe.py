#!/usr/bin/env python3
"""Capture device-event bytes. Subscribes to DEVICE_EVENT (h0010), WORKOUT
(h000f), and a wildcard over every notify char, then logs for 45s while you
interact with the band. Do these during the window:
   - press the button (touch area) a few times
   - long-press the button
   - open 'Find device'/'More'->find phone on the band if present
   - take it off / cover the sensor (non-wear)
"""
import asyncio
import time
from miband5 import MiBand5, DEVICE_EVENTS, UUID_DEVICE_EVENT, huami

UUID_WORKOUT = huami("000f")


async def main():
    band = await MiBand5.open()
    c = band.c
    print("AUTH OK ✅")
    b = await band.battery()
    print(f"Battery: {b.level}%\n")
    seen = []

    def mk(tag):
        def cb(_h, d):
            d = bytes(d)
            note = ""
            if tag == "EVENT" and d:
                note = " -> " + DEVICE_EVENTS.get(d[0], f"unknown_{d[0]:#04x}")
            line = f"{time.strftime('%H:%M:%S')} [{tag}] {d.hex(' ')}{note}"
            print("  " + line)
            seen.append(line)
        return cb

    # primary channels
    await c.start_notify(UUID_DEVICE_EVENT, mk("EVENT"))
    try:
        await c.start_notify(UUID_WORKOUT, mk("WORKOUT"))
    except Exception as e:
        print(f"(workout sub failed: {e})")

    # wildcard: every other notify char we haven't claimed
    claimed = {UUID_DEVICE_EVENT.lower(), UUID_WORKOUT.lower()}
    for svc in c.services:
        for ch in svc.characteristics:
            if "notify" in ch.properties and ch.uuid.lower() not in claimed:
                try:
                    await c.start_notify(ch.uuid, mk(ch.uuid[4:8]))
                    claimed.add(ch.uuid.lower())
                except Exception:
                    pass

    print(">>> INTERACT NOW (45s): press button, long-press, find-phone, take band off\n")
    try:
        await asyncio.sleep(45)
    finally:
        print(f"\n=== captured {len(seen)} packets ===")
        open("events_log.txt", "w").write("\n".join(seen))
        await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
