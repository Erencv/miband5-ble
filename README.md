# miband5-ble

Reverse-engineering the **Xiaomi Mi Smart Band 5** (model `XMSH10HM`) BLE protocol — a clean,
documented, cloud-free Python toolkit to talk to the band directly from your own computer.

No Xiaomi/Zepp app required at runtime. Read heart rate, steps, battery and activity history,
make it vibrate, and change its settings — straight over Bluetooth LE.

> Hobby / educational reverse-engineering project. Works with **your own** band. Not affiliated
> with or endorsed by Xiaomi/Huami/Zepp.

---

## What works

| Capability | Status |
|---|---|
| Auth (AES-128-ECB challenge-response) | ✅ verified |
| Heart rate (live stream) | ✅ |
| Realtime steps + distance + calories | ✅ |
| Battery level / charge state | ✅ |
| Activity history (per-minute steps/HR/intensity) | ✅ |
| Vibration / find-device | ✅ |
| Settings/config (24h, units, lift-wrist, DND, …) | ✅ mechanism, 📖 full table |
| Raw PPG optical waveform | ❌ not exposed on this firmware |
| Unsolicited device events (button, etc.) | ❌ silent on app-less unit |

Full byte-level spec, including the negative results, is in **[PROTOCOL.md](PROTOCOL.md)**.

---

## Requirements

- Python 3.10+
- A Mi Smart Band 5 you own
- macOS / Linux / Windows with BLE (developed on macOS; `bleak` is cross-platform)
- The band's **auth key** (see [Getting the auth key](#getting-the-auth-key))

```bash
python3 -m venv .venv
.venv/bin/pip install bleak pycryptodome
```

---

## Quick start

```bash
# 1. Find your band and its address
.venv/bin/python scan.py

# 2. Tell the tools which device is yours (address from scan.py)
#    macOS shows a CoreBluetooth UUID; Linux/Windows show a MAC.
export BAND_ADDRESS="<address-from-scan>"        # or: echo "<addr>" > .band_address

# 3. Put your 32-hex-char auth key in auth_key.txt
echo "<your32hexkey>" > auth_key.txt

# 4. Go
.venv/bin/python live.py            # live HR + steps + battery
.venv/bin/python fetch_history.py 1 # pull stored activity -> CSV
```

Or use the library:

```python
import asyncio
from miband5 import MiBand5

async def main():
    async with await MiBand5.open() as band:      # scan + connect + auth
        print(await band.battery())
        await band.vibrate(1.5)
        n = 0
        async for bpm in band.heart_rate():
            print(bpm, "bpm")
            n += 1
            if n >= 10: break

asyncio.run(main())
```

---

## Getting the auth key

Mi Band 5 uses **server-based pairing** — unlike Band 2/3/4 you cannot register your own key
locally (the band returns `10 01 81` and never bonds). The key is negotiated with Xiaomi/Huami
servers during the first bind via the official app and stored on the band. You bind **once**, then
extract that key and reuse it forever (it stays valid until a factory reset).

Two routes (pick one):

### A. Sniff the app's API response (used here, reliable)
The official **Zepp Life** app fetches your device list from the server, and that response contains
`additionalInfo.auth_key`. Intercept it with [mitmproxy](https://mitmproxy.org/):

1. `pip install mitmproxy`, then `mitmdump -s mitm_capture.py` on your computer.
2. Set your phone's Wi-Fi HTTP proxy to your computer's IP, port 8080.
3. Install + trust the mitmproxy CA cert on the phone (visit `http://mitm.it`).
   - iOS: also enable it under Settings → General → About → Certificate Trust Settings.
4. Open Zepp Life, view your band. `mitm_capture.py` prints the `auth_key` for each device.
   Set `BAND_MAC=<your-mac>` first to auto-write `auth_key.txt`.
5. **Remove the proxy + cert from the phone afterwards.**

Zepp Life is not certificate-pinned, so this works without a jailbreak/root.

### B. huami-token (account API)
[`argrento/huami-token`](https://github.com/argrento/huami-token) logs into your Xiaomi/Zepp
account and downloads keys for bound devices. Note: it defaults to US servers — for EU/other
regions you must point it at the right host (e.g. `api-user-de.huami.com`, region `eu-central-1`)
or login 401s. Still requires one app bind first.

Either way: drop the 32 hex chars into `auth_key.txt`.

---

## Scripts

| File | What it does |
|---|---|
| `miband5.py` | **The library** — async client (auth, HR, steps, battery, vibrate, config, history) |
| `scan.py` | Find the band, print its address |
| `gatt.py` | Dump the full GATT table with Huami labels |
| `band.py` | Shared resolver (scan-retry) + UUID/protocol constants |
| `live.py` | Live HR + steps + battery monitor |
| `fetch_history.py` | Pull stored per-minute activity → `activity_history.csv` |
| `probe.py`, `events_probe.py`, `explore.py` | Verification / discovery harnesses |
| `mitm_capture.py` | mitmproxy addon to extract the auth key |
| `PROTOCOL.md` | The reverse-engineered protocol spec |

---

## Gotchas

- **The band advertises in short windows** — `band.resolve()` retries the scan; keep the screen lit.
- **One BLE owner at a time** — unbind/disconnect the band from any phone app first.
- **macOS stuck-handle bug** after failed connects: `blueutil -p 0 && blueutil -p 1` clears it.
- **bleak mislabels Huami 16-bit UUIDs** as SDP names ("RFCOMM" etc.) — ignore; use the `CHARS`
  map in `band.py`.
- **Activity history is incremental** — the band only stores data since the last sync, and a
  successful fetch advances the sync pointer (data won't repeat). With no app installed, this tool
  becomes the only sync client and accumulates everything going forward.

---

## Security & privacy

- **Never commit `auth_key.txt`** — it's your band's secret key (`.gitignore`d here).
- `.band_address`, captured tokens, logs and CSVs are also git-ignored.
- The auth key grants full BLE control of your band; treat it like a password.

---

## Credits

- [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) (GPLv3) — the authoritative
  Huami protocol reference used to label and verify commands. Not redistributed here; clone it
  separately if you want the source.
- [`argrento/huami-token`](https://github.com/argrento/huami-token) — auth-key retrieval.
- [bleak](https://github.com/hbldh/bleak) — cross-platform BLE.

## License

MIT — see [LICENSE](LICENSE).
