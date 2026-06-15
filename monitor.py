#!/usr/bin/env python3
"""Subscribe to notify/indicate characteristics and log every raw packet
with a timestamp. Watch the hex change as you move/measure HR — that's how
you decode the protocol. Logs to ble_log.csv too."""
import asyncio
import csv
import sys
import time
from bleak import BleakClient

LOG = "ble_log.csv"


async def main(addr: str, only: list[str]):
    fh = open(LOG, "a", newline="")
    w = csv.writer(fh)
    if fh.tell() == 0:
        w.writerow(["ts", "char_uuid", "len", "hex", "u8", "u16le"])

    def cb(char, data: bytearray):
        t = time.strftime("%H:%M:%S")
        u8 = data[0] if len(data) else ""
        u16 = int.from_bytes(data[:2], "little") if len(data) >= 2 else ""
        print(f"{t}  {char.uuid}  len={len(data):<3} {data.hex(' ')}  u8={u8} u16le={u16}")
        w.writerow([time.time(), char.uuid, len(data), data.hex(), u8, u16])
        fh.flush()

    async with BleakClient(addr, timeout=20.0) as client:
        print(f"Connected: {client.is_connected}. Subscribing...\n")
        subbed = 0
        for svc in client.services:
            for ch in svc.characteristics:
                if only and ch.uuid.lower() not in [o.lower() for o in only]:
                    continue
                if "notify" in ch.properties or "indicate" in ch.properties:
                    try:
                        await client.start_notify(ch.uuid, cb)
                        print(f"subscribed: {ch.uuid} ({','.join(ch.properties)})")
                        subbed += 1
                    except Exception as e:
                        print(f"sub failed {ch.uuid}: {e}")
        if not subbed:
            sys.exit("No notify chars subscribed. Check UUIDs / pairing.")
        print(f"\n{subbed} subscriptions. Logging to {LOG}. Ctrl-C to stop.\n")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python monitor.py <ADDRESS> [char_uuid ...]")
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
