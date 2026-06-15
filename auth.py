#!/usr/bin/env python3
"""Mi Band 5 auth handshake (Huami AES-128-ECB challenge-response).

First run on a factory-reset band REGISTERS our own 16-byte key (band buzzes
-> tap it to confirm pairing). Key saved to auth_key.txt and reused after.

Protocol on auth char 0x0009 (service fee1):
  send key      -> write  01 00 + key[16]      ; resp 10 01 01 = ok
  request rand  -> write  02 00                ; resp 10 02 01 + random[16]
  send encrypted-> write  03 00 + AES_ECB(key, random)
                                               ; resp 10 03 01 = AUTH OK
"""
import asyncio
import os
import sys
from Crypto.Cipher import AES
from band import connect, UUID_AUTH

KEY_FILE = "auth_key.txt"
# Late Mi Band 5 firmware (V1.0.2.x) needs auth flag 0x08 ("new key crypto").
# Older firmware used 0x00. Override via AUTH_FLAG env if needed.
FLAG = bytes([int(os.environ.get("AUTH_FLAG", "0x08"), 16)])
SEND_KEY = b"\x01" + FLAG
REQ_RANDOM = b"\x02" + FLAG
SEND_ENC = b"\x03" + FLAG


def load_or_make_key() -> tuple[bytes, bool]:
    if os.path.exists(KEY_FILE):
        return bytes.fromhex(open(KEY_FILE).read().strip()), False
    key = os.urandom(16)
    open(KEY_FILE, "w").write(key.hex())
    print(f"Generated new auth key -> {KEY_FILE}: {key.hex()}")
    return key, True


async def authenticate(client) -> bytes:
    key, first = load_or_make_key()
    state = {"random": None, "ok": False, "fail": False}
    done = asyncio.Event()

    def cb(_ch, data: bytearray):
        print(f"  auth notif: {data.hex(' ')}")
        if not (len(data) >= 3 and data[0] == 0x10):
            return
        cmd, status = data[1], data[2]
        ok = status in (0x01, 0x81)  # 0x81 = high-bit variant seen on late fw
        if cmd == 0x01:  # key send response -> request random regardless, learn
            if not ok:
                print(f"  (key resp status {status:#04x}; trying request-random anyway)")
            asyncio.create_task(client.write_gatt_char(UUID_AUTH, REQ_RANDOM, response=False))
        elif cmd == 0x02:  # random delivered
            if not ok or len(data) < 19:
                state["fail"] = True
                done.set()
                return
            state["random"] = bytes(data[3:19])
            enc = AES.new(key, AES.MODE_ECB).encrypt(state["random"])
            asyncio.create_task(client.write_gatt_char(UUID_AUTH, SEND_ENC + enc, response=False))
        elif cmd == 0x03:  # auth result
            state["ok"] = ok
            state["fail"] = not ok
            done.set()

    await client.start_notify(UUID_AUTH, cb)

    if first:
        print("First pairing: sending key. WATCH THE BAND — tap to confirm when it buzzes.")
        await client.write_gatt_char(UUID_AUTH, SEND_KEY + key, response=False)
    else:
        print("Reusing stored key: requesting random...")
        await client.write_gatt_char(UUID_AUTH, REQ_RANDOM, response=False)

    try:
        await asyncio.wait_for(done.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        raise SystemExit("Auth timed out. If first pairing, you must tap the band in time.")

    if state["fail"] or not state["ok"]:
        raise SystemExit("Auth FAILED. Try: delete auth_key.txt, re-factory-reset band, retry.")
    print("AUTH OK ✅")
    return key


async def main():
    client = await connect()
    try:
        await authenticate(client)
        print("Authenticated session ready.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
