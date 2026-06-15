#!/usr/bin/env python3
"""Shared helpers: resolve the band (CoreBluetooth needs a fresh scan before
connect) and the Huami/Mi Band UUID + protocol constants."""
import os
import asyncio
from bleak import BleakScanner, BleakClient

# Your band's address (a MAC on Linux/Windows, a CoreBluetooth UUID on macOS).
# Find it with scan.py, then either set the env var BAND_ADDRESS or write it to
# a file named `.band_address`. If unset, we fall back to matching by name.
def _load_addr() -> str:
    if os.environ.get("BAND_ADDRESS"):
        return os.environ["BAND_ADDRESS"].strip()
    try:
        return open(os.path.join(os.path.dirname(__file__), ".band_address")).read().strip()
    except OSError:
        return ""

DEFAULT_ADDR = _load_addr()
NAME_HINTS = ("mi smart band", "mi band")  # strict: avoid matching neighbors' Redmi Watch etc.

# Huami proprietary base: 0000XXXX-0000-3512-2118-0009af100700
def huami(x: str) -> str:
    return f"0000{x}-0000-3512-2118-0009af100700"

# Real meaning of the fee0/fee1 chars (Gadgetbridge Huami map) — bleak's
# built-in names are wrong (it decodes the 16-bit slice as SDP protocols).
CHARS = {
    huami("0009"): "AUTH (fee1)",
    huami("0006"): "BATTERY",
    huami("0007"): "REALTIME_STEPS",
    huami("0004"): "FETCH/control",
    huami("0005"): "ACTIVITY_DATA",
    huami("0003"): "CONFIGURATION",
    huami("0010"): "DEVICE_EVENT",
    huami("0008"): "USER_SETTINGS",
    "00002a37-0000-1000-8000-00805f9b34fb": "HEART_RATE_MEASUREMENT",
    "00002a39-0000-1000-8000-00805f9b34fb": "HEART_RATE_CONTROL",
    "00002a2b-0000-1000-8000-00805f9b34fb": "CURRENT_TIME",
}

UUID_AUTH = huami("0009")
UUID_HR_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_HR_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"
UUID_STEPS = huami("0007")
UUID_BATTERY = huami("0006")


async def resolve(addr: str | None = None, timeout: float = 8.0, tries: int = 8):
    """Scan and return a BLEDevice (CoreBluetooth needs to have seen it).
    Retries because the band only advertises in brief windows."""
    want = (addr or DEFAULT_ADDR).upper()
    for i in range(tries):
        print(f"Scanning (try {i+1}/{tries})... keep swiping the band screen")
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for a, (dev, adv) in found.items():
            if a.upper() == want:
                print(f"  matched by address: {a}")
                return dev
        for a, (dev, adv) in found.items():
            nm = (dev.name or adv.local_name or "").lower()
            if any(h in nm for h in NAME_HINTS):
                print(f"  matched by name: {dev.name} ({a})")
                return dev
    raise SystemExit("Band not found after retries. Ensure it's awake / not bonded elsewhere.")


async def connect(addr: str | None = None) -> BleakClient:
    dev = await resolve(addr)
    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    return client
