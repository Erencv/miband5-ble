"""mitmproxy addon: capture the Mi Band auth key from Zepp Life traffic.

Run:  .venv/bin/mitmdump -s mitm_capture.py
Then point the iPhone's Wi-Fi HTTP proxy at this Mac and open Zepp Life.

It scans Huami/Zepp/Xiaomi API responses for device entries containing
`additionalInfo.auth_key` and prints + saves the key for our band.
"""
import os
import json
from mitmproxy import http

# Set your band's MAC so the addon can auto-write auth_key.txt for the right
# device (find it via scan.py, or just read it off the captured device list).
TARGET_MAC = os.environ.get("BAND_MAC", "").upper()
HOST_HINTS = ("huami.com", "zepp.com", "xiaomi", "mi.com", "amazfit")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "mitm_hits.json")


def _walk(obj, hits):
    """Recursively find dicts that look like a device entry with an auth_key."""
    if isinstance(obj, dict):
        # additionalInfo is often a JSON-encoded string
        ai = obj.get("additionalInfo")
        if isinstance(ai, str):
            try:
                ai = json.loads(ai)
            except Exception:
                ai = {}
        mac = (obj.get("macAddress") or obj.get("mac") or "").upper()
        key = None
        if isinstance(ai, dict):
            key = ai.get("auth_key") or ai.get("authKey")
        key = key or obj.get("auth_key") or obj.get("authKey")
        if key:
            hits.append({"mac": mac, "auth_key": key})
        for v in obj.values():
            _walk(v, hits)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, hits)


DBG = os.path.join(HERE, "mitm_devices_debug.jsonl")
TOK = os.path.join(HERE, "mitm_token.json")


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if not any(h in host for h in HOST_HINTS):
        return
    hdrs = {k.lower(): v for k, v in flow.request.headers.items()}
    tok = hdrs.get("apptoken") or hdrs.get("app_token")
    if tok:
        # capture host + token + any user id in the path
        import re
        m = re.search(r"/users/(\d+)", flow.request.path)
        uid = m.group(1) if m else None
        open(TOK, "w").write(json.dumps({"host": host, "apptoken": tok, "user_id": uid}))


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if not any(h in host for h in HOST_HINTS):
        return
    body = flow.response.get_text() or ""
    # Dump any device/user related response so we can inspect field names.
    path = flow.request.path
    if ("/devices" in path or "/users/" in path or "/device/" in path) and body.strip().startswith(("{", "[")):
        open(DBG, "a").write(json.dumps({"path": path, "body": body[:8000]}) + "\n")
        print(f"[mitm] dumped device/user response: {host}{path.split('?')[0]}")
    if "auth_key" not in body and "authKey" not in body and "additionalInfo" not in body:
        return
    try:
        data = json.loads(body)
    except Exception:
        # not JSON but mentions auth_key — dump raw for manual inspection
        print(f"\n[mitm] {host}{flow.request.path} mentions auth_key but isn't JSON; raw saved.")
        open(OUT, "a").write(json.dumps({"host": host, "path": flow.request.path, "raw": body[:4000]}) + "\n")
        return

    hits = []
    _walk(data, hits)
    if not hits:
        return
    open(OUT, "a").write(json.dumps({"host": host, "path": flow.request.path, "hits": hits}) + "\n")
    print(f"\n[mitm] {host}{flow.request.path}")
    for h in hits:
        mark = "  <== TARGET BAND" if TARGET_MAC and h["mac"] == TARGET_MAC else ""
        print(f"   mac={h['mac']}  auth_key={h['auth_key']}{mark}")
        # auto-write auth_key.txt only if BAND_MAC was set and matches
        if TARGET_MAC and h["mac"] == TARGET_MAC:
            key = h["auth_key"].lower().removeprefix("0x")
            with open(os.path.join(HERE, "auth_key.txt"), "w") as f:
                f.write(key)
            print(f"   >>> wrote auth_key.txt")
