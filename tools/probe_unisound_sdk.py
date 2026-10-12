#!/usr/bin/env python3
"""Reference script, corrected and runnable.

Three independent defects made "the API key looks unusable":

  1. MODEL     `u2-flash` is advertised by /v1/models but this key is not
               entitled to it -> 404 model_not_found. The id `u2` works and the
               gateway routes it to `u2-flash`.
  2. TRANSPORT httpx (and therefore the openai SDK) inherits the Windows
               registry proxy as `https://127.0.0.1:7897` and attempts a TLS
               handshake *to Clash's plaintext mixed port* -> ConnectError.
               Fixed here with an explicit trust_env=False httpx client.
  3. SDK       openai 1.12.0 + httpx 0.28.1 raises
               "Client.__init__() got an unexpected keyword argument 'proxies'".
               Fixed by upgrading:  pip install -U openai

Usage:
    set HTTPS_PROXY=            (not required; trust_env is off below)
    python tools/probe_unisound_sdk.py
"""
import os

import httpx
from openai import AuthenticationError, NotFoundError, OpenAI

BASE_URL = "https://maas-api.unisound.com/v1"
MODEL = os.environ.get("U2_MODEL", "u2")
KEY = os.environ["ACI_BENCH_API_KEY"]

# Defect 2: do not let httpx read the Windows registry proxy, which points at a
# plaintext Clash mixed port through an https:// URL scheme.
http_client = httpx.Client(trust_env=False, timeout=120.0)
client = OpenAI(api_key=KEY, base_url=BASE_URL, http_client=http_client)

print(f"openai {__import__('openai').__version__} | httpx {httpx.__version__}")
print(f"base_url={BASE_URL}  model={MODEL}\n")

try:
    ids = [m.id for m in client.models.list().data]
    print(f"[AUTH OK] {len(ids)} models advertised by this key\n")
except AuthenticationError as e:
    raise SystemExit(f"[AUTH FAIL] {e}")

for model in ("u2-flash", MODEL):
    try:
        c = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "你好"}]
        )
        print(f"[OK]   model={model!r:<10} returned={c.model!r}")
        print(f"       -> {c.choices[0].message.content!r}")
    except NotFoundError as e:
        print(f"[404]  model={model!r:<10} {e.message}")
