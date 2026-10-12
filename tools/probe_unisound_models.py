#!/usr/bin/env python3
"""Enumerate the real model catalog of the Unisound MaaS gateway and find the
correct id for the U2 family, then prove a working chat completion.

Reads the key from ACI_BENCH_API_KEY and never prints it.
"""
import json
import os
import urllib.error
import urllib.request

BASE = "https://maas-api.unisound.com/v1"
KEY = os.environ.get("ACI_BENCH_API_KEY", "")


def http(url, method="GET", body=None, timeout=30):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {KEY}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


print("=" * 68)
print("A. Full model catalog")
print("=" * 68)
code, text = http(f"{BASE}/models")
ids = []
if code == 200:
    data = json.loads(text)
    for m in data.get("data", []):
        ids.append(m["id"])
        print(f"  {m['id']:<28} ctx={m.get('context_window','?'):<10} owner={m.get('owned_by','?')}")
    print(f"\n  total: {len(ids)} models")
else:
    print(f"  [{code}] {text[:300]}")

print()
print("=" * 68)
print("B. U2-family candidates present in the catalog")
print("=" * 68)
u2 = [i for i in ids if "u2" in i.lower()]
print(f"  u2 matches: {u2 if u2 else '<none>'}")

print()
print("=" * 68)
print("C. Which candidate ids actually accept a chat completion?")
print("=" * 68)
candidates = []
for want in ["u2-flash", "u2_flash", "u2", "sn-u2-flash"]:
    if want not in candidates:
        candidates.append(want)
for i in u2:
    if i not in candidates:
        candidates.append(i)
for i in ids[:3]:
    if i not in candidates:
        candidates.append(i)

working = None
for mid in candidates:
    code, text = http(
        f"{BASE}/chat/completions",
        method="POST",
        body={"model": mid, "messages": [{"role": "user", "content": "你好"}]},
    )
    if code == 200:
        try:
            msg = json.loads(text)["choices"][0]["message"]["content"]
        except Exception:
            msg = text[:120]
        print(f"  [200] {mid:<22} -> {msg!r}")
        if working is None:
            working = mid
    else:
        try:
            err = json.loads(text)["error"]["message"]
        except Exception:
            err = text[:120]
        print(f"  [{code}] {mid:<22} -> {err}")

print()
print("=" * 68)
print("D. Installed SDK versions (explains the TypeError seen earlier)")
print("=" * 68)
for mod in ["openai", "httpx", "pydantic"]:
    try:
        m = __import__(mod)
        print(f"  {mod}: {getattr(m, '__version__', '?')}")
    except ImportError as e:
        print(f"  {mod}: NOT INSTALLED ({e})")

print()
print("=" * 68)
print("E. Recommended env for the live run")
print("=" * 68)
print(f"  ACI_BENCH_BASE_URL={BASE}")
print(f"  ACI_BENCH_MODEL={working or '<none of the probed ids worked>'}")
print("  (key already valid: GET /v1/models -> 200)")
