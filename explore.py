#!/usr/bin/env python3
"""Phase 0 band capability discovery — one session, minimal battery:
  1. AUTH
  2. subscribe every notify channel, log raw packets (labeled)
  3. VIBRATE test via Immediate Alert (0x1802 / 0x2a06)
  4. RAW SENSOR probe: try to enable raw PPG + accelerometer streaming
  5. continuous HR start, log bpm
Run, watch the band (should buzz), and read what streams.
"""
import asyncio
import time
from bleak import BleakClient
from band import resolve, UUID_AUTH, UUID_HR_MEASURE, UUID_HR_CONTROL, huami

ALERT_LEVEL = "00002a06-0000-1000-8000-00805f9b34fb"  # Immediate Alert service 0x1802
C0001 = huami("0001")   # candidate raw-sensor command channel
C0002 = huami("0002")   # candidate raw-sensor data channel
C0007 = huami("0007")   # realtime steps
C0010 = huami("0010")   # device events

LOG = []


def log(tag, data: bytearray):
    line = f"{time.strftime('%H:%M:%S')}  [{tag}] len={len(data):<3} {bytes(data).hex(' ')}"
    print(line)
    LOG.append(line)


async def do_auth(client):
    from Crypto.Cipher import AES
    key = bytes.fromhex(open("auth_key.txt").read().strip())
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
    print("AUTH OK ✅\n")


async def safe_sub(client, uuid, tag):
    try:
        await client.start_notify(uuid, lambda _h, d: log(tag, d))
        print(f"subscribed {tag} ({uuid})")
    except Exception as e:
        print(f"sub {tag} failed: {e}")


async def main():
    dev = await resolve(tries=10)
    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    print(f"Connected: {client.is_connected}")
    try:
        await do_auth(client)

        # subscribe everything interesting
        await safe_sub(client, UUID_HR_MEASURE, "HR")
        await safe_sub(client, C0001, "c0001")
        await safe_sub(client, C0002, "c0002")
        await safe_sub(client, C0007, "steps")
        await safe_sub(client, C0010, "event")

        # --- VIBRATE test ---
        print("\n>>> VIBRATE: high alert for 2s (watch the band)")
        try:
            await client.write_gatt_char(ALERT_LEVEL, b"\x02", response=False)
            await asyncio.sleep(2)
            await client.write_gatt_char(ALERT_LEVEL, b"\x00", response=False)
            print("    vibrate command sent (did it buzz?)")
        except Exception as e:
            print(f"    vibrate failed: {e}")

        # --- continuous HR ---
        print("\n>>> HR continuous start")
        try:
            await client.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x02, 0x00]), response=True)
            await client.write_gatt_char(UUID_HR_CONTROL, bytes([0x15, 0x01, 0x01]), response=True)
        except Exception as e:
            print(f"    HR start failed: {e}")

        # --- RAW SENSOR probe (experimental) ---
        print("\n>>> RAW SENSOR probe: trying enable commands on c0001")
        for cmd in (bytes([0x01, 0x03, 0x19]), bytes([0x02]), bytes([0x01, 0x03, 0x00])):
            try:
                await client.write_gatt_char(C0001, cmd, response=False)
                print(f"    wrote c0001 <- {cmd.hex(' ')}")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"    c0001 {cmd.hex(' ')} failed: {e}")

        print("\n>>> Logging 15s more (move / sit still to see HR + any raw stream)\n")
        await asyncio.sleep(15)

        # stop raw + HR
        try:
            await client.write_gatt_char(C0001, bytes([0x03]), response=False)
        except Exception:
            pass

        # summary
        from collections import Counter
        tags = Counter(l.split("[")[1].split("]")[0] for l in LOG)
        print(f"\n=== packets per channel ===\n{dict(tags)}")
        open("explore_log.txt", "w").write("\n".join(LOG))
        print(f"saved {len(LOG)} packets -> explore_log.txt")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
