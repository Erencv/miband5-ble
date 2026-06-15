#!/usr/bin/env python3
"""Scan for BLE devices. macOS hides MAC, so match by name and grab the
Core Bluetooth UUID we need for connecting later."""
import asyncio
from bleak import BleakScanner

NAME_HINTS = ("xiaomi", "mi band", "redmi", "smart band", "xmsh")


async def main():
    print("Scanning 10s... wake the band (tap screen) so it advertises.\n")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    rows = []
    for addr, (dev, adv) in devices.items():
        name = (dev.name or adv.local_name or "").strip()
        rows.append((adv.rssi, addr, name, list(adv.service_uuids)))

    rows.sort(reverse=True)  # strongest signal first
    print(f"{'RSSI':>5}  {'ADDRESS (CB UUID on macOS)':<40} NAME")
    print("-" * 80)
    for rssi, addr, name, svcs in rows:
        hit = any(h in name.lower() for h in NAME_HINTS)
        mark = " <== LIKELY BAND" if hit else ""
        print(f"{rssi:>5}  {addr:<40} {name!r}{mark}")
        if hit and svcs:
            print(f"       services: {svcs}")

    print("\nCopy the ADDRESS of your band, pass to: python gatt.py <ADDRESS>")


if __name__ == "__main__":
    asyncio.run(main())
