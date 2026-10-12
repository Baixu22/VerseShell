#!/usr/bin/env python3
"""Connectivity + credential probe for the Unisound MaaS endpoint.

Answers three separable questions:
  1. Is the base_url path correct (does /v1/models answer at all)?
  2. Is the API key accepted (401/403 vs 200)?
  3. Is the model id valid (400 vs 200)?

The key is read from the ACI_BENCH_API_KEY env var and is never printed.
"""
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request

HOST = "maas-api.unisound.com"
KEY = os.environ.get("ACI_BENCH_API_KEY", "")
MODEL = os.environ.get("ACI_BENCH_MODEL", "u2-flash")

CANDIDATE_BASES = [
    "https://maas-api.unisound.com/v1",
    "https://maas.unisound.com/v1",
    "https://maas-api.unisound.com/api/v1",
    "https://maas-api.unisound.com/v1/",
    "https://api.unisound.com/v1",
]


def banner(t):
    print("\n" + "=" * 68 + "\n" + t + "\n" + "=" * 68)


def show_key():
    if not KEY:
        print("  ACI_BENCH_API_KEY: <unset>")
    else:
        print(f"  ACI_BENCH_API_KEY: len={len(KEY)} prefix={KEY[:6]}... suffix=...{KEY[-4:]}")


def resolve():
    banner("1. DNS resolution")
    try:
        infos = socket.getaddrinfo(HOST, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({i[4][0] for i in infos})
        print(f"  {HOST} -> {ips}")
        for ip in ips:
            print(f"    {'FAKE-IP (Clash/benchmark range)' if ip.startswith('198.18.') or ip.startswith('198.19.') else 'public'}: {ip}")
    except Exception as e:
        print(f"  DNS FAILED: {type(e).__name__}: {e}")


def raw_tls():
    banner("2. Raw TLS handshake (OpenSSL, bypasses Schannel)")
    for ip in ["1.1.1.1", "223.5.5.5"]:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((ip, 443), timeout=8) as s:
                with ctx.wrap_socket(s, server_hostname=None) as ss:
                    print(f"  {ip}:443 TLS OK via {ss.version()}")
        except Exception as e:
            print(f"  {ip}:443 TLS FAIL: {type(e).__name__}: {e}")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((HOST, 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname=HOST) as ss:
                cert = ss.getpeercert()
                print(f"  {HOST}:443 TLS OK via {ss.version()}")
                print(f"    cert subject: {cert.get('subject')}")
                print(f"    cert issuer : {cert.get('issuer')}")
                print(f"    notAfter    : {cert.get('notAfter')}")
    except Exception as e:
        print(f"  {HOST}:443 TLS FAIL: {type(e).__name__}: {e}")


def http(url, method="GET", body=None, key=None, timeout=25):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "ACI-Bench-Connectivity-Probe/1.0")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def probe_bases():
    banner("3. Base-URL path discovery (GET <base>/models, no key)")
    for base in CANDIDATE_BASES:
        url = base.rstrip("/") + "/models"
        code, text = http(url, key=None)
        snippet = " ".join(text.split())[:160]
        print(f"  [{str(code):>4}] {url}\n         {snippet}")


def probe_auth(base):
    banner("4. Auth check (GET <base>/models with bearer key)")
    url = base.rstrip("/") + "/models"
    code, text = http(url, key=KEY)
    print(f"  [{code}] {url}")
    print(f"  body: {' '.join(text.split())[:400]}")


def probe_chat(base):
    banner("5. Chat completion (the exact call from the reference script)")
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "你好"}]}
    code, text = http(url, method="POST", body=payload, key=KEY)
    print(f"  [{code}] POST {url}")
    print(f"  model: {MODEL}")
    print(f"  body: {' '.join(text.split())[:800]}")


def probe_sdk(base):
    banner("6. OpenAI SDK round-trip")
    try:
        import openai
        print(f"  openai version: {openai.__version__}")
    except ImportError:
        print("  openai SDK not installed - skipped")
        return
    try:
        from openai import OpenAI
        client = OpenAI(api_key=KEY, base_url=base)
        c = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": "你好"}]
        )
        print(f"  OK: {c.choices[0].message.content!r}")
    except Exception as e:
        print(f"  SDK ERROR: {type(e).__name__}: {e}")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else CANDIDATE_BASES[0]
    banner("0. Context")
    print(f"  python: {sys.version.split()[0]}")
    show_key()
    print(f"  model : {MODEL}")
    print(f"  base  : {base}")
    resolve()
    raw_tls()
    probe_bases()
    probe_auth(base)
    probe_chat(base)
    probe_sdk(base)


if __name__ == "__main__":
    main()
