#!/usr/bin/env python3
"""Isolate the transport layer: does the local HTTP proxy break TLS to this host?

Compares, against the same URL and key:
  - urllib with the Windows/system proxy (registry)
  - urllib with proxies explicitly disabled (direct / Clash TUN)
  - httpx with trust_env (picks up proxy env)
  - httpx with trust_env=False (direct)
"""
import json
import os
import urllib.request

URL = "https://maas-api.unisound.com/v1/models"
KEY = os.environ["ACI_BENCH_API_KEY"]

print("system proxies seen by urllib:", urllib.request.getproxies())
print("proxy env vars:", {k: v for k, v in os.environ.items()
                          if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")})
print()

# ── urllib, system proxy ──────────────────────────────────────────────
def urllib_try(label, opener):
    req = urllib.request.Request(URL)
    req.add_header("Authorization", f"Bearer {KEY}")
    try:
        with opener.open(req, timeout=30) as r:
            print(f"  [OK {r.status}]   urllib/{label}")
    except Exception as e:
        print(f"  [FAIL]      urllib/{label}: {type(e).__name__}: {e}")

print("urllib:")
urllib_try("system-proxy", urllib.request.build_opener())
urllib_try("no-proxy    ", urllib.request.build_opener(urllib.request.ProxyHandler({})))
print()

# ── httpx ─────────────────────────────────────────────────────────────
try:
    import httpx
    print(f"httpx {httpx.__version__}:")
    for label, kwargs in (("trust_env=True ", {}),
                          ("trust_env=False", {"trust_env": False})):
        try:
            with httpx.Client(timeout=30, **kwargs) as c:
                r = c.get(URL, headers={"Authorization": f"Bearer {KEY}"})
                print(f"  [OK {r.status_code}]   httpx/{label}")
        except Exception as e:
            print(f"  [FAIL]      httpx/{label}: {type(e).__name__}: {e}")
    try:
        with httpx.Client(timeout=30, trust_env=False) as c:
            r = c.get(URL, headers={"Authorization": f"Bearer {KEY}"})
            data = json.loads(r.text)
            print(f"\n  httpx direct catalog size: {len(data['data'])} models")
    except Exception as e:
        print(f"\n  httpx direct catalog FAILED: {type(e).__name__}: {e}")
except ImportError:
    print("httpx not installed")
