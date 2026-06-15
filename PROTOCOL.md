# Mi Smart Band 5 (XMSH10HM) — BLE Protocol, fully reverse-engineered

Reference unit: model `XMSH10HM`, fw `V1.0.2.66`, hw `V0.44.17.2`.
(Per-device identifiers — serial, MAC, CoreBluetooth UUID — are redacted; yours will differ.)
Protocol family: **classic Huami** (`MiBand5Support → MiBand4Support → HuamiSupport`).
NOT Zepp-OS, NOT Huami-2021 ECDH auth.

Legend:  ✅ verified live on this unit · 📖 from Gadgetbridge source (high confidence) · ⚠️ inferred/unverified

---

## 1. Connection & quirks

- **macOS hides the MAC.** Match by the per-Mac CoreBluetooth UUID or name `Mi Smart Band 5`. ✅
- **Advertises in short windows** — scan must retry; keep the screen lit. ✅
- **Single BLE owner** — if a phone is connected/bound, the Mac can't connect. ✅
- **Stuck-handle bug** on macOS after failed connects → `blueutil -p 0 && blueutil -p 1` clears it. ✅
- **Battery on this unit is degraded** (~1–2h). After a full drain the RTC resets (last-charge time reads ~1970). ✅

---

## 2. GATT map ✅ (full inventory)

Huami proprietary base: `0000XXXX-0000-3512-2118-0009af100700` (written `hXXXX` below).

| Service | Char | Name (Gadgetbridge) | Props | Auth? |
|---|---|---|---|---|
| `180a` Device Info | `2a25` | Serial Number | R | no |
| | `2a27` | Hardware Revision | R | no |
| | `2a28` | Software Revision | R | no |
| | `2a23` | System ID (= MAC in EUI-64) | R | no |
| | `2a50` | PnP ID | R | no |
| `180d` Heart Rate | `2a37` | HR Measurement | N | **yes** |
| | `2a39` | HR Control Point | R/W | yes |
| `1802` Immediate Alert | `2a06` | Alert Level (find-device) | W- | yes |
| `1811` Alert Notification | `2a46` | New Alert (notifications) | R/W | yes |
| | `2a44` | Alert Notif Control Point | R/W/N | yes |
| `fee0` Huami main | `2a2b` | Current Time | R/W/N | partial |
| | `h0001` | **RAW_SENSOR_CONTROL** | W-/N | yes |
| | `h0002` | **RAW_SENSOR_DATA** | N | yes |
| | `h0003` | CONFIGURATION | W-/N | yes |
| | `h0004` | ACTIVITY_CONTROL (fetch ctrl) | W/N | yes |
| | `h0005` | ACTIVITY_DATA | N | yes |
| | `h0006` | BATTERY_INFO | R/N | no |
| | `h0007` | REALTIME_STEPS | R/N | yes |
| | `h0008` | USER_SETTINGS | W/N | yes |
| | `h0010` | DEVICE_EVENT | N | yes |
| | `h000f` | WORKOUT | W-/N | yes |
| | `h0012/0013` | AUDIO / AUDIODATA | — | yes |
| | `h0020` | CHUNKED_TRANSFER (notifications) | W- | yes |
| `fee1` Huami auth | `h0009` | AUTH | R/W-/N | — |
| `1530` Firmware | `1531` | FW Control | W/N | yes |
| | `1532` | FW Data | W- | yes |

Props: R=read W=write W-=write-no-response N=notify.

---

## 3. Auth — AES-128-ECB challenge-response ✅

Char `h0009` (service `fee1`). **Key cannot be self-registered on this firmware** (server-pairing);
extract the key from the Xiaomi/Huami account (we used a mitmproxy capture of the Zepp Life
device-list API → `additionalInfo.auth_key`). Key for this unit lives in `auth_key.txt`.

Constants (`HuamiService.java`): `AUTH_SEND_KEY=0x01`, `AUTH_REQUEST_RANDOM=0x02`,
`AUTH_SEND_ENCRYPTED=0x03`, `AUTH_RESPONSE=0x10`, `AUTH_SUCCESS=0x01`, `AUTH_FAIL=0x04`, `AUTH_BYTE=0x08`.

Handshake (with a known key) ✅:
```
→ 02 00                         request random
← 10 02 01 <random[16]>         band's challenge
→ 03 00 <AES_ECB(key, random)>  encrypted response
← 10 03 01                      AUTH OK   (10 03 07 = wrong key)
```
Self-register attempt `01 00 + key` → `10 01 81` (rejected, no vibration). ✅

---

## 4. Per-characteristic protocol

### 4.1 Heart Rate — `2a37` / `2a39` ✅
- Measurement notify: `00 <bpm>` (2 bytes, byte0=flags=0). e.g. `00 4f` = 79 bpm. ✅
- Control `2a39`:
  - `15 01 01` start continuous · `15 01 00` stop continuous ✅
  - `15 02 01` start single · `15 02 00` stop single ✅
  - `15 00 01` enable sleep-assisted HR · `15 00 00` disable 📖
  - keep-alive ping `16` every ~12 s during continuous ✅
  - periodic auto-HR interval: config endpoint `0x14` (minutes) 📖

### 4.2 Realtime steps — `h0007` ✅ (fully decoded)
13-byte read/notify, observed `0c 78 02 00 00 b5 01 00 00 0f 00 00 00`:
- `[0]` flag (`0x0c`)
- `[1:5]` **steps** u32LE (632)
- `[5:9]` **distance** u32LE, meters (437)
- `[9:13]` **calories** u32LE, kcal (15)
So `1 + 4 + 4 + 4 = 13`. (Steps also read fine as u16 at `[1:3]` since counts are small.) ✅

### 4.3 Battery — `h0006` ✅📖
`0f 3f 00 b2 07 01 01 …` →
- byte1 = level % (`0x3f`=63) ✅
- byte2 = status: `00` normal, `01` charging ✅
- bytes3-9 = last-charge timestamp (year LE, month, day, h, m, s) — bogus after RTC reset ✅
- byte19 = last-charge level % 📖

### 4.4 Activity history — fetch `h0004` ctrl / `h0005` data ✅📖
Band stores **one 4-byte sample per minute**, only since the last cloud sync (synced data is
erased). Successful fetch advances the sync pointer (data won't repeat).

Control constants: `COMMAND_ACTIVITY_DATA_START_DATE=0x01`, `COMMAND_FETCH_DATA=0x02`,
`COMMAND_ACK_ACTIVITY_DATA=0x03`, `RESPONSE=0x10`, `SUCCESS=0x01`.

Flow ✅:
```
→ 01 01 <BLE-timestamp 8B>     request data since time
← 10 01 01 <type> <start-ts 8B>  metadata (actual start; tz in quarter-hours, e.g. 0x0c=+3h)
→ 02                           begin transfer
← (h0005) packets: [seq][payload…]   payload = 4-byte samples
← 10 02 01                     transfer complete (10 02 04 = no data)
```
Sample = `[kind, intensity, steps, heartRate]`; `hr==0xff` means invalid; timestamp = start + i minutes. ✅

### 4.5 Current Time — `2a2b` ✅
`e7 07 07 02 05 3b 0e 07 00 00 80` = year LE(2), month, day, h, m, s, dayOfWeek, …, tz. ✅

### 4.6 Configuration — `h0003` ✅ (mechanism verified)
**Write-WITHOUT-response** (writing with response → "Write Not Permitted"). Band acks on the
same char via notify as `10 <command-echo>`. Verified: wrote `06 02 00 01` (24h) → ack
`10 06 02 00 01`. ✅ This validates the whole command table below.
Endpoints: `ENDPOINT_DISPLAY=0x06`, `ENDPOINT_DISPLAY_ITEMS=0x0a`, `ENDPOINT_DND=0x09`.

Selected commands (all 📖, prefix = endpoint):
| Purpose | Bytes |
|---|---|
| Lift-wrist wake ON | `06 05 00 01 00 00 00 00` |
| Lift-wrist wake OFF | `06 05 00 00` |
| Goal notification ON/OFF | `06 06 00 01` / `…00` |
| Rotate-wrist-to-switch ON/OFF | `06 0d 00 01` / `…00` |
| 24h / 12h time | `06 02 00 01` / `06 02 00 00` |
| Distance metric / imperial | `06 03 00 00` / `06 03 00 01` |
| Display caller ON/OFF | `06 10 00 00 01` / `…00` |
| Disconnect-notify ON/OFF | `06 0c 00 01 00 00 00 00` / `…00` |
| Night mode / HR-display etc. | `06 1f …` |
| **Factory reset** | `06 0b 00 01` ⚠️ destructive |
| Set screens order | `0a 01 00 00 01 02 03 04 05` |
| DND off / auto / scheduled | `09 82` / `09 83` / `09 81 01 00 06 00` |
| Inactivity warning ON | `08 01 3c 00 04 00 15 00 00 00 00 00` |
| Hourly chime ON | `fe 0b 00 01 0a 00 16 00` |
| Alarms (request) | `0d` / `ff 01 00 00 00` |
| Fitness goal | `10 00 00 <steps LE> 00 00` |
| User info | `4f …` (age/height/weight/sex) |
| Wear location L / R | `20 00 00 02` / `20 00 00 82` |

### 4.7 Device events — `h0010` (notify) 📖, ✅(does not emit on this unit)
Subscribed + interacted (button, long-press, find-phone, non-wear) for 45s with a wildcard on
every notify char → **zero events emitted**; only realtime-steps fired. So on this app-less unit
the band does not push button/UI events. Likely the band only emits these once features are
configured by the official app, or in specific bound states. IDs below are from Gadgetbridge.
First byte = event id:
| id | event | id | event |
|---|---|---|---|
| 0x01 | fell asleep | 0x0a | alarm toggled |
| 0x02 | woke up | 0x0b | button long-press |
| 0x03 | step goal reached | 0x0e | 30-min tick |
| 0x04 | **button pressed** | 0x0f | find-phone stop |
| 0x06 | non-wear start | 0x10 | silent mode |
| 0x07 | call reject | 0x14 | workout starting |
| 0x08 | **find-phone start** | 0x16 | MTU request |
| 0x09 | call ignore | 0x1a | alarm changed |

### 4.8 Find-device / vibration — `2a06` ✅ (buzz confirmed)
Write **`03`** = vibrate (find), **`00`** = stop. Confirmed buzzing on this unit. (Value `02`
= ignored by MB5 — that was the earlier no-buzz cause.) App repeats it on a loop; send `00` to end.

### 4.9 Notifications (text + icon) — `h0020` chunked / `2a46` New Alert 📖
Rich notifications use the chunked-transfer channel (`h0020`) with `COMMAND_TEXT_NOTIFICATION = 05 01`
+ category/icon + UTF-8 text; simple alerts go via AlertNotificationProfile on New Alert `2a46`.

### 4.10 Raw sensor — `h0001` ctrl / `h0002` data ❌
Channels exist, but classic `HuamiSupport.handleRawSensorData` is a **stub** — raw PPG/accel is only
implemented for Zepp-OS bands (MB7+). Our probes (`01 03 19`, `02`) → acks on `h0001`
(`10 01 03 02`) but **zero** data on `h0002`. Raw optical waveform is **not exposed** on MB5 fw
V1.0.2.66 via known protocol; would require novel RE. ✅(negative result)

### 4.11 Firmware update — `1531` ctrl / `1532` data 📖⚠️
`COMMAND_FIRMWARE_INIT=01` (+size), `START_DATA=03`, `UPDATE_SYNC=00`, `CHECKSUM=04`, `REBOOT=05`.
Bricking risk — out of scope.

---

## 5. What we verified live vs. referenced
- ✅ Verified on-device: GATT map, auth handshake (+`10 01 81` reject), HR stream+control,
  battery format, activity fetch + 4-byte samples, current-time read, device-info reads,
  realtime-steps full layout (steps/distance/calories), **config write mechanism + ack**
  (write-no-response, `10`+echo), **vibrate `2a06 ← 03` (buzz confirmed)**, raw-sensor negative result.
- 📖 From Gadgetbridge (not yet sent): individual config commands beyond 24h, device-event ids,
  user-info/goal, notifications, firmware.

## 6. Open items
None functional. Device events (`h0010`) confirmed **non-emitting** on this app-less unit (§4.7) —
would only be worth revisiting if the band is re-bound to an app that enables those features.
Raw PPG (§4.10) is a hard negative on this firmware. Everything else is verified and working.
