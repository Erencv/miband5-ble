#!/usr/bin/env python3
"""Fetch stored activity history from the Mi Band 5 (Huami protocol).

The band logs one 4-byte sample PER MINUTE: [kind, intensity, steps, heartRate].
We ask for everything since a start date, the band replays it on the data
characteristic, we parse and write activity_history.csv.

Fetch protocol:
  control char 0x0004 (FETCH):
     write 01 01 + <8-byte BLE timestamp>   -> request data from that time
     band replies 10 01 01 + <actual start ts(7)> + <count u32?>  (metadata)
     write 02                                -> begin transfer
     ... data streams on 0x0005 ...
     band replies 10 02 01 on 0x0004         -> transfer complete (04 = no data)
  data char 0x0005 (ACTIVITY_DATA):
     each packet: byte0 = sequence index, bytes[1:] = sample bytes (4 per minute)
"""
import asyncio
import csv
import struct
import sys
import time
from datetime import datetime, timedelta
from bleak import BleakClient
from band import resolve, UUID_AUTH, huami

UUID_FETCH = huami("0004")   # control
UUID_DATA = huami("0005")    # activity data
OUT = "activity_history.csv"


def ble_timestamp(dt: datetime) -> bytes:
    # year(2 LE), month, day, hour, minute, second, tz(quarter-hours)
    tz = 0  # quarter-hours offset; 0 = keep simple, band already has its own tz
    return struct.pack("<H", dt.year) + bytes([dt.month, dt.day, dt.hour, dt.minute, dt.second, tz])


async def do_auth(client, key_hex: str):
    from Crypto.Cipher import AES
    key = bytes.fromhex(key_hex)
    ev = asyncio.Event(); ok = {"v": False}

    def cb(_h, d):
        if len(d) >= 3 and d[0] == 0x10:
            if d[1] == 0x02 and d[2] in (1, 0x81) and len(d) >= 19:
                enc = AES.new(key, AES.MODE_ECB).encrypt(bytes(d[3:19]))
                asyncio.create_task(client.write_gatt_char(UUID_AUTH, b"\x03\x00" + enc, response=False))
            elif d[1] == 0x03:
                ok["v"] = d[2] == 1; ev.set()

    await client.start_notify(UUID_AUTH, cb)
    await client.write_gatt_char(UUID_AUTH, b"\x02\x00", response=False)
    await asyncio.wait_for(ev.wait(), 15)
    if not ok["v"]:
        raise SystemExit("Auth failed.")
    print("AUTH OK ✅")


async def main(days: int):
    key_hex = open("auth_key.txt").read().strip()
    dev = await resolve(tries=10)
    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    print(f"Connected: {client.is_connected}")
    try:
        await do_auth(client, key_hex)

        start_dt = datetime.now() - timedelta(days=days)
        start_dt = start_dt.replace(second=0, microsecond=0)
        print(f"Requesting history since {start_dt}")

        buf = bytearray()
        meta = {"start": None, "pkt_first": None}
        done = asyncio.Event()
        result = {"status": None}

        def on_control(_h, d):
            print(f"  [ctrl] {d.hex(' ')}")
            if len(d) >= 3 and d[0] == 0x10:
                if d[1] == 0x01 and d[2] == 0x01:
                    # metadata: actual start timestamp begins at d[7:]
                    try:
                        yr = int.from_bytes(d[7:9], "little")
                        meta["start"] = datetime(yr, d[9], d[10], d[11], d[12])
                        print(f"  band will send from: {meta['start']}")
                    except Exception as e:
                        print(f"  (couldn't parse meta start: {e})")
                    # begin transfer
                    asyncio.create_task(client.write_gatt_char(UUID_FETCH, b"\x02", response=False))
                elif d[1] == 0x02:
                    result["status"] = d[2]
                    done.set()

        def on_data(_h, d):
            # byte0 = sequence index; rest = samples
            if meta["pkt_first"] is None:
                meta["pkt_first"] = d[0]
            buf.extend(d[1:])

        await client.start_notify(UUID_FETCH, on_control)
        await client.start_notify(UUID_DATA, on_data)

        trigger = b"\x01\x01" + ble_timestamp(start_dt)
        print(f"  trigger -> {trigger.hex(' ')}")
        await client.write_gatt_char(UUID_FETCH, trigger, response=False)

        try:
            await asyncio.wait_for(done.wait(), timeout=120)
        except asyncio.TimeoutError:
            print("  (timeout waiting for transfer-complete; parsing what we got)")

        print(f"\nTransfer status: {result['status']}  raw bytes: {len(buf)}  samples: {len(buf)//4}")

        # parse 4-byte samples, timestamp = meta start + i minutes
        base = meta["start"] or start_dt
        rows = []
        for i in range(len(buf) // 4):
            kind, intensity, steps, hr = buf[i*4:i*4+4]
            ts = base + timedelta(minutes=i)
            rows.append([ts.isoformat(), kind, intensity, steps, hr if hr != 0xff else ""])

        with open(OUT, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "kind", "intensity", "steps", "heart_rate"])
            w.writerows(rows)
        print(f"Wrote {len(rows)} rows -> {OUT}")

        # quick summary
        hrs = [int(r[4]) for r in rows if r[4] != ""]
        total_steps = sum(int(r[3]) for r in rows)
        if rows:
            print(f"Span: {rows[0][0]} .. {rows[-1][0]}")
        if hrs:
            print(f"HR samples: {len(hrs)}  min/avg/max = {min(hrs)}/{sum(hrs)//len(hrs)}/{max(hrs)}")
        print(f"Total steps in window: {total_steps}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    asyncio.run(main(days))
