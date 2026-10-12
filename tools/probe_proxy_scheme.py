#!/usr/bin/env python3
"""Prove the Windows-registry proxy-scheme bug and the env-var fix.

Root cause (CPython 3.10 `urllib/request.py:2685-2692`): when
`ProxyServer` holds a bare `host:port`, `getproxies_registry()` maps every
scheme to `<scheme>://<host:port>`. Clash Verge writes `127.0.0.1:7897`, so the
**https** proxy becomes `https://127.0.0.1:7897` - httpx then opens a TLS
connection *to Clash's plaintext mixed port* and dies with
`ConnectError: EOF occurred in violation of protocol`.

`getproxies()` prefers the environment over the registry, so
`HTTPS_PROXY=http://127.0.0.1:7897` restores the correct mapping and every
stock client (openai SDK, httpx, requests) works with no code change.

Run it twice:  once bare, once with HTTP_PROXY/HTTPS_PROXY exported.
"""
import os
import urllib.request

import httpx
from openai import OpenAI

BASE = "https://maas-api.unisound.com/v1"
KEY = os.environ["ACI_BENCH_API_KEY"]

print("getproxies() :", urllib.request.getproxies())

try:
    with httpx.Client(timeout=60) as c:  # trust_env defaults to True
        r = c.get(f"{BASE}/models")
        print(f"httpx (stock) : OK {r.status_code}")
except Exception as e:
    print(f"httpx (stock) : FAIL {type(e).__name__}: {e}")

try:
    client = OpenAI(api_key=KEY, base_url=BASE)  # stock client, no overrides
    r = client.chat.completions.create(
        model="u2", messages=[{"role": "user", "content": "你好"}]
    )
    print(f"OpenAI (stock): OK model={r.model!r} {r.choices[0].message.content[:36]!r}")
except Exception as e:
    print(f"OpenAI (stock): FAIL {type(e).__name__}: {e}")
