#!/usr/bin/env python3
"""Sweep every model advertised by the gateway and report which ones this key
is actually entitled to call. Tiny max_tokens keeps the sweep cheap.
"""
import json
import os
import urllib.error
import urllib.request

BASE = "https://maas-api.unisound.com/v1"
KEY = os.environ.get("ACI_BENCH_API_KEY", "")


def post(model):
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
    ).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {KEY}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return None, {"err": f"{type(e).__name__}: {e}"}


req = urllib.request.Request(f"{BASE}/models")
req.add_header("Authorization", f"Bearer {KEY}")
with urllib.request.urlopen(req, timeout=30) as r:
    catalog = [m["id"] for m in json.loads(r.read().decode())["data"]]

entitled, denied = [], []
for mid in catalog:
    code, data = post(mid)
    if code == 200:
        entitled.append(mid)
        print(f"  OK    {mid}")
    else:
        msg = data.get("error", {}).get("message", str(data))[:80]
        denied.append(mid)
        print(f"  DENY  {mid:<24} [{code}] {msg}")

print()
print(f"ENTITLED ({len(entitled)}): {entitled}")
print(f"DENIED   ({len(denied)}): {denied}")
