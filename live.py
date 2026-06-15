#!/usr/bin/env python3
"""Live monitor. If a VALID auth key is in auth_key.txt, authenticates and
streams heart rate + realtime steps + battery. Otherwise falls back to the
no-auth data the band exposes: battery, firmware, time.

Get an auth key: pair the band ONCE with the official Zepp Life / Mi Fitness
app, then extract the key (see README). Drop the 32-hex-char key in auth_key.txt.
"""
import asyncio
import os
import time
from bleak import BleakClient
from band import (resolve, UUID_AUTH, UUID_HR_MEASURE, UUID_HR_CONTROL,
                  UUID_STEPS, UUID_BATTERY)

KEY_FILE = "auth_key.txt"


def parse_battery(d: bytes) -> str:
    # Huami battery: byte[1] = level %, byte[2] = status (1=charging)
    lvl = d[1] if len(d) > 1 else "?"
    chg = "charging" if len(d) > 2 and d[2] == 1 else "not charging"
    return f"{lvl}% ({chg})"


def parse_steps(d: bytes) -> str:
    # realtime steps notify: little-endian u32 at [1:5] (steps)
    if len(d) >= 5:
        steps = int.from_bytes(d[1:5], "little")
        return f"{steps} steps"
    return d.hex(" ")


def parse_hr(d: bytes) -> str:
    # 0x2A37: flags byte then HR. bpm = byte[1] for 8-bit format
    if len(d) >= 2:
        return f"{d[1]} bpm"
    return d.hex(" ")


async def try_auth(client) -> bool:
    if not os.path.exists(KEY_FILE):
        print("No auth_key.txt — running in NO-AUTH mode (battery/info only).")
        return False
    from Crypto.Cipher import AES
    key = bytes.fromhex(open(KEY_FILE).read().strip())
    if len(key) != 16:
        print("auth_key.txt is not 16 bytes — ignoring.")
        return False
    ev = asyncio.Event()
    ok = {"v": False}

    def cb(_h, d):
        if len(d) >= 3 and d[0] == 0x10:
            if d[1] == 0x02 and d[2] in (1, 0x81) and len(d) >= 19:
                enc = AES.new(key, AES.MODE_ECB).encrypt(bytes(d[3:19]))
                asyncio.create_task(client.write_gatt_char(UUID_AUTH, b"\x03\x00" + enc, response=False))
            elif d[1] == 0x03:
                ok["v"] = d[2] == 1
                ev.set()

    await client.start_notify(UUID_AUTH, cb)
    await client.write_gatt_char(UUID_AUTH, b"\x02\x00", response=False)
    try:
        await asyncio.wait_for(ev.wait(), 15)
    except asyncio.TimeoutError:
        pass
    print("AUTH OK ✅" if ok["v"] else "AUTH failed — key invalid/not bound. NO-AUTH mode.")
    return ok["v"]


async def main():
    dev = await resolve(tries=10)
    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    print(f"Connected: {client.is_connected}\n")
    try:
        authed = await try_auth(client)

        b = await client.read_gatt_char(UUID_BATTERY)
        print(f"Battery: {parse_battery(b)}")

        if not authed:
            print("\nNo-auth mode: only battery/info available. Polling battery every 30s.\n")
            while True:
                b = await client.read_gatt_char(UUID_BATTERY)
                print(f"{time.strftime('%H:%M:%S')}  battery {parse_battery(b)}")
                await asyncio.sleep(30)

        # Authed: stream steps + HR
        await client.start_notify(UUID_STEPS, lambda _h, d: print(f"{time.strftime('%H:%M:%S')}  {parse_steps(d)}"))
        await client.start_notify(UUID_HR_MEASURE, lambda _h, d: print(f"{time.strftime('%H:%M:%S')}  {parse_hr(d)}"))
        # start continuous HR: stop single (0x15 0x02 0x00), start continuous (0x15 0x01 0x01)
        await client.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x02, 0x00]), response=True)
        await client.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x01, 0x01]), response=True)
        print("\nStreaming HR + steps. Ctrl-C to stop.\n")
        # keep HR alive: ping every 12s
        while True:
            await asyncio.sleep(12)
            await client.write_gatt_char(UUID_HR_CONTROL, bytes([0x16]), response=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
