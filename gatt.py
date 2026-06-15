#!/usr/bin/env python3
"""Connect to the band (scan-then-connect for CoreBluetooth) and dump the
full GATT table with correct Huami labels and readable values."""
import asyncio
import sys
from band import connect, CHARS


def label(uuid: str) -> str:
    return CHARS.get(uuid.lower(), "")


def decode_guess(b: bytes) -> str:
    out = []
    try:
        s = b.decode("utf-8").strip("\x00")
        if s.isprintable() and s:
            out.append(f"ascii={s!r}")
    except UnicodeDecodeError:
        pass
    if len(b) == 1:
        out.append(f"u8={b[0]}")
    if len(b) >= 2:
        out.append(f"u16le={int.from_bytes(b[:2], 'little')}")
    return " ".join(out) or "?"


async def main(addr: str | None):
    client = await connect(addr)
    try:
        print(f"Connected: {client.is_connected}\n")
        for svc in client.services:
            print(f"[service] {svc.uuid}")
            for ch in svc.characteristics:
                tag = label(ch.uuid)
                tag = f"  <<{tag}>>" if tag else ""
                print(f"  [char] {ch.uuid}  props={','.join(ch.properties)}{tag}")
                if "read" in ch.properties:
                    try:
                        val = await client.read_gatt_char(ch.uuid)
                        print(f"         read -> {val.hex(' ')}  | {decode_guess(val)}")
                    except Exception as e:
                        print(f"         read failed: {e}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
