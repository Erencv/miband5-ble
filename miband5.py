#!/usr/bin/env python3
"""miband5 — clean async client for the Mi Smart Band 5 (classic Huami protocol).

Implements the reverse-engineered protocol in PROTOCOL.md. Verified parts are
live-tested; config/notification commands are from Gadgetbridge.

    from miband5 import MiBand5
    async with await MiBand5.open() as band:     # scans, connects, authenticates
        print(await band.battery())
        await band.vibrate(1.5)
        async for bpm in band.heart_rate():
            print(bpm)
"""
from __future__ import annotations
import asyncio
import struct
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from bleak import BleakClient
from Crypto.Cipher import AES
from band import (resolve, UUID_AUTH, UUID_HR_MEASURE, UUID_HR_CONTROL,
                  UUID_STEPS, UUID_BATTERY, huami)

UUID_ALERT_LEVEL = "00002a06-0000-1000-8000-00805f9b34fb"
UUID_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
UUID_CONFIG = huami("0003")
UUID_FETCH_CTRL = huami("0004")
UUID_FETCH_DATA = huami("0005")
UUID_DEVICE_EVENT = huami("0010")

DEVICE_EVENTS = {
    0x01: "fell_asleep", 0x02: "woke_up", 0x03: "step_goal", 0x04: "button",
    0x06: "nonwear_start", 0x07: "call_reject", 0x08: "find_phone_start",
    0x09: "call_ignore", 0x0a: "alarm_toggled", 0x0b: "button_long",
    0x0e: "tick_30min", 0x0f: "find_phone_stop", 0x10: "silent_mode",
    0x14: "workout_start", 0x1a: "alarm_changed",
}


@dataclass
class Battery:
    level: int
    charging: bool
    raw: bytes


@dataclass
class ActivitySample:
    ts: datetime
    kind: int
    intensity: int
    steps: int
    heart_rate: int | None


def _ble_ts(dt: datetime) -> bytes:
    return struct.pack("<H", dt.year) + bytes([dt.month, dt.day, dt.hour, dt.minute, dt.second, 0])


class MiBand5:
    def __init__(self, client: BleakClient, key: bytes):
        self.c = client
        self.key = key

    # ---- lifecycle ----
    @classmethod
    async def open(cls, key_path: str = "auth_key.txt", tries: int = 10) -> "MiBand5":
        key = bytes.fromhex(open(key_path).read().strip())
        dev = await resolve(tries=tries)
        client = BleakClient(dev, timeout=20.0)
        await client.connect()
        self = cls(client, key)
        await self._authenticate()
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.c.disconnect()

    async def _authenticate(self):
        ev = asyncio.Event(); ok = {"v": False}

        def cb(_h, d):
            if len(d) >= 3 and d[0] == 0x10:
                if d[1] == 0x02 and d[2] in (1, 0x81) and len(d) >= 19:
                    enc = AES.new(self.key, AES.MODE_ECB).encrypt(bytes(d[3:19]))
                    asyncio.create_task(self.c.write_gatt_char(UUID_AUTH, b"\x03\x00" + enc, response=False))
                elif d[1] == 0x03:
                    ok["v"] = d[2] == 1; ev.set()

        await self.c.start_notify(UUID_AUTH, cb)
        await self.c.write_gatt_char(UUID_AUTH, b"\x02\x00", response=False)
        await asyncio.wait_for(ev.wait(), 15)
        if not ok["v"]:
            raise RuntimeError("auth failed")

    # ---- simple reads ----
    async def battery(self) -> Battery:
        d = await self.c.read_gatt_char(UUID_BATTERY)
        return Battery(level=d[1], charging=(len(d) > 2 and d[2] == 1), raw=bytes(d))

    async def device_time(self) -> bytes:
        return bytes(await self.c.read_gatt_char(UUID_CURRENT_TIME))

    # ---- haptics ----
    async def vibrate(self, seconds: float = 1.0):
        """Find-device buzz (Alert Level 0x2a06 = 0x03), stop after `seconds`."""
        await self.c.write_gatt_char(UUID_ALERT_LEVEL, b"\x03", response=False)
        await asyncio.sleep(seconds)
        await self.c.write_gatt_char(UUID_ALERT_LEVEL, b"\x00", response=False)

    # ---- heart rate (async generator of bpm) ----
    async def heart_rate(self):
        q: asyncio.Queue[int] = asyncio.Queue()
        def cb(_h, d):
            if len(d) == 2 and d[0] == 0:
                q.put_nowait(d[1])
        await self.c.start_notify(UUID_HR_MEASURE, cb)
        await self.c.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x02, 0x00]), response=True)
        await self.c.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x01, 0x01]), response=True)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=12)
                except asyncio.TimeoutError:
                    await self.c.write_gatt_char(UUID_HR_CONTROL, b"\x16", response=True)  # keep-alive
        finally:
            await self.c.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x01, 0x00]), response=True)
            await self.c.stop_notify(UUID_HR_MEASURE)

    # ---- realtime steps (yields dict: steps / distance_m / calories_kcal) ----
    async def realtime_steps(self):
        q: asyncio.Queue[dict] = asyncio.Queue()
        def parse(d: bytes) -> dict:
            return {
                "steps": int.from_bytes(d[1:5], "little"),
                "distance_m": int.from_bytes(d[5:9], "little") if len(d) >= 9 else None,
                "calories_kcal": int.from_bytes(d[9:13], "little") if len(d) >= 13 else None,
            }
        def cb(_h, d):
            if len(d) >= 5:
                q.put_nowait(parse(bytes(d)))
        # prime with a read, then stream changes
        try:
            d = bytes(await self.c.read_gatt_char(UUID_STEPS))
            if len(d) >= 5:
                q.put_nowait(parse(d))
        except Exception:
            pass
        await self.c.start_notify(UUID_STEPS, cb)
        try:
            while True:
                yield await q.get()
        finally:
            await self.c.stop_notify(UUID_STEPS)

    # ---- device events ----
    async def events(self):
        q: asyncio.Queue[str] = asyncio.Queue()
        def cb(_h, d):
            if d:
                q.put_nowait(DEVICE_EVENTS.get(d[0], f"unknown_{d[0]:#04x}") + " " + bytes(d).hex(" "))
        await self.c.start_notify(UUID_DEVICE_EVENT, cb)
        try:
            while True:
                yield await q.get()
        finally:
            await self.c.stop_notify(UUID_DEVICE_EVENT)

    # ---- config (write a raw config command, e.g. set 24h time) ----
    async def set_24h(self, on: bool = True):
        await self.c.write_gatt_char(UUID_CONFIG, bytes([0x06, 0x02, 0x00, 0x01 if on else 0x00]), response=False)

    # ---- activity history fetch ----
    async def fetch_history(self, since: datetime) -> list[ActivitySample]:
        since = since.replace(second=0, microsecond=0)
        buf = bytearray(); meta = {"start": None}
        done = asyncio.Event(); status = {"v": None}

        def on_ctrl(_h, d):
            if len(d) >= 3 and d[0] == 0x10:
                if d[1] == 0x01 and d[2] == 0x01:
                    try:
                        meta["start"] = datetime(int.from_bytes(d[7:9], "little"), d[9], d[10], d[11], d[12])
                    except Exception:
                        pass
                    asyncio.create_task(self.c.write_gatt_char(UUID_FETCH_CTRL, b"\x02", response=False))
                elif d[1] == 0x02:
                    status["v"] = d[2]; done.set()

        def on_data(_h, d):
            buf.extend(d[1:])

        await self.c.start_notify(UUID_FETCH_CTRL, on_ctrl)
        await self.c.start_notify(UUID_FETCH_DATA, on_data)
        await self.c.write_gatt_char(UUID_FETCH_CTRL, b"\x01\x01" + _ble_ts(since), response=False)
        try:
            await asyncio.wait_for(done.wait(), 120)
        except asyncio.TimeoutError:
            pass
        base = meta["start"] or since
        out = []
        for i in range(len(buf) // 4):
            k, inten, steps, hr = buf[i*4:i*4+4]
            out.append(ActivitySample(base + timedelta(minutes=i), k, inten, steps, None if hr == 0xff else hr))
        return out


# quick demo
if __name__ == "__main__":
    async def demo():
        async with await MiBand5.open() as band:
            b = await band.battery()
            print(f"Battery: {b.level}% charging={b.charging}")
            print("Buzzing 1.5s...")
            await band.vibrate(1.5)
            print("HR (10 samples):")
            n = 0
            async for bpm in band.heart_rate():
                print(" ", bpm, "bpm"); n += 1
                if n >= 10:
                    break
    asyncio.run(demo())
