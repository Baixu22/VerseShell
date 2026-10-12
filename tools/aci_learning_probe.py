#!/usr/bin/env python3
"""aci_learning_probe: give claim C5 (learning cost) a real, reproducible metric.

C5 currently says: "a coding agent that only reads the quickstart can correctly use
the main contract (typed op + observation envelope) without extra human coaching."
That claim had **no** metric at all, so it could only be registered as 未证实.

This probe measures it with real model calls and the real ACI server:

  1. The model is given ONLY `docs/quickstart/aci-mcp.md` as its system prompt —
     no tool schemas, no function-calling definitions, no examples beyond what the
     document itself contains.
  2. It is asked, in one shot per task, to emit the JSON-RPC op lines that perform
     that task.
  3. Every emitted line is executed through the **real** server
     (`ae --serve --agent`), i.e. the same path a live agent would use.
  4. The resulting workspace state is checked against the task's own predicate.

Two metrics come out of it:
  - `first_attempt_op_acceptance` — share of tasks whose every emitted op was
    accepted by the server (`ok: true`, no `E_*` error) on the FIRST attempt.
    This is the contract-usage half of C5: did the doc teach the call shape?
  - `task_success` — share of tasks whose end state satisfies the predicate.
    This is the outcome half.

The `hash_handoff` sub-check is the sharpest part of the "observation envelope"
half: the doc says edits need the `expected_hash` from a read, so a model that
learned the envelope well enough will read first and hand the digest back instead
of guessing an edit.

Credentials come from .env.local via tools/live_bench.py's loader convention;
they never enter the repo.

Usage:
    python tools/aci_learning_probe.py --out eval/aci_learning_probe.json
    python tools/aci_learning_probe.py --repeat 3 --out eval/aci_learning_probe.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))

from live_agent_loop import (  # noqa: E402
    ACI_CAPABILITIES,
    chat_completion,
    estimate_tokens,
    execute_aci_op,
    format_aci_result,
)

ENV_LOCAL = ROOT / ".env.local"
QUICKSTART = ROOT / "docs" / "quickstart" / "aci-mcp.md"

# Fingerprint surface: the doc whose sufficiency C5 asserts, plus this probe.
EVIDENCE_GLOBS = ["docs/quickstart/**/*", "tools/aci_learning_probe.py"]


def evidence_fingerprint(globs: list[str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


# ── probe tasks ────────────────────────────────────────────────────────────────
# Each fixture is materialised from a tiny inline template so the probe is
# self-contained (no dependency on the ACI-Bench fixtures, whose task set is
# versioned separately). `check` inspects the resulting workspace.

PROBE_TASKS = [
    {
        "id": "write_file",
        "fixture": {"src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"},
        "ask": "Create the file out/hello.txt whose exact contents are the single word world.",
        "check": lambda ws: (ws / "out" / "hello.txt").exists()
        and (ws / "out" / "hello.txt").read_text(encoding="utf-8", errors="replace").strip() == "world",
    },
    {
        "id": "read_window",
        "fixture": {"src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"},
        "ask": "Read the first 2 lines of src/lib.rs. Then write the total number of lines "
               "the file has into a file out/lines.txt.",
        "check": lambda ws: (ws / "out" / "lines.txt").exists()
        and (ws / "out" / "lines.txt").read_text(encoding="utf-8", errors="replace").strip() == "3",
    },
    {
        "id": "exact_edit",
        "fixture": {"src/lib.rs": "pub fn mul(a: i32, b: i32) -> i32 {\n    return a * b;\n}\n"},
        "ask": "Change the body of the `mul` function in src/lib.rs so it multiplies by "
               "adding instead: the function must return a + b.",
        "check": lambda ws: "return a + b;" in (ws / "src" / "lib.rs").read_text(encoding="utf-8", errors="replace"),
        "hash_handoff": True,
    },
    {
        "id": "search_then_report",
        "fixture": {
            "src/lib.rs": "pub fn f() -> i32 { 1 }\n",
            "src/broken.rs": "// TODO(fix-me): implement this\npub fn g() -> i32 { 0 }\n",
        },
        "ask": "Find which file contains the marker TODO(fix-me), and write that file's path "
               "into out/found.txt.",
        "check": lambda ws: (ws / "out" / "found.txt").exists()
        and "broken.rs" in (ws / "out" / "found.txt").read_text(encoding="utf-8", errors="replace"),
    },
    {
        "id": "exec_and_report",
        "fixture": {"notes.txt": "hello\n"},
        "ask": "Run a shell command that prints the current working directory, then write the "
               "directory path into out/pwd.txt.",
        "check": lambda ws: (ws / "out" / "pwd.txt").exists()
        and len((ws / "out" / "pwd.txt").read_text(encoding="utf-8", errors="replace").strip()) > 3,
    },
]

OUTPUT_CONTRACT = """

You cannot call tools. Instead, reply with ONE JSON object per line, and nothing else.
Each line is a JSON-RPC request in exactly the form the document above describes, e.g.:
{"id":"1","agent":"coder","op":"file.view","args":{"path":"src/lib.rs","cursor":1}}
Emit the requests in the order they should run. Do not wrap them in an array or add prose."""


def run_probe_task(task: dict, *, doc: str, model: str, api_key: str, base_url: str,
                   caps: str, seed: int | None) -> dict:
    workspace = Path(tempfile.mkdtemp(prefix=f"aci-learn-{task['id']}-"))
    for rel, body in task["fixture"].items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8", newline="\n")

    system = doc + OUTPUT_CONTRACT
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task["ask"]},
    ]

    ops_emitted: list[dict] = []
    accepted: list[bool] = []
    obs_tokens = 0
    error = None
    raw_reply = ""

    try:
        resp = chat_completion(messages, [], model=model, api_key=api_key,
                               base_url=base_url, temperature=0.0, seed=seed)
        raw_reply = (resp.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
    except Exception as exc:  # API failure must not look like a capability failure
        error = f"api_error: {exc}"

    if not error:
        for line in raw_reply.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            op = req.get("op")
            if not op:
                continue
            args = req.get("args") or {}
            aci_response = execute_aci_op(op, args, str(workspace), caps)
            text = format_aci_result(aci_response)
            obs_tokens += estimate_tokens(text)
            ops_emitted.append({"op": op, "args": args, "ok": bool(aci_response.get("ok")),
                                "error": (aci_response.get("error") or {}).get("code")
                                if isinstance(aci_response.get("error"), dict) else aci_response.get("error")})
            accepted.append(bool(aci_response.get("ok")))

    try:
        task_ok = bool(task["check"](workspace))
    except Exception as exc:
        task_ok = False
        error = error or f"check_error: {exc}"

    # The observation-envelope half of C5: a model that understood the contract
    # reads before editing and hands the digest back, so its first op is a read
    # and the edit carries a non-empty expected_hash.
    hash_handoff = None
    if task.get("hash_handoff"):
        reads_first = bool(ops_emitted) and ops_emitted[0]["op"] in ("file.view", "file.read_range",
                                                                    "file.read_many")
        edit = next((o for o in ops_emitted if o["op"] in ("file.replace_exact", "file.edit_range")), None)
        carries_hash = bool(edit and any(k in (edit["args"] or {}) and (edit["args"] or {}).get(k)
                                          for k in ("expected_hash", "hash")))
        hash_handoff = bool(reads_first and carries_hash)

    shutil.rmtree(workspace, ignore_errors=True)

    return {
        "task_id": task["id"],
        "api_error": bool(error and error.startswith("api_error")),
        "error": error,
        "ops_emitted": ops_emitted,
        "n_ops": len(ops_emitted),
        # A reply with no parseable JSON-RPC line is a *formatting* failure, not
        # a rejected op. Keeping it separate matters: the contract half of C5 is
        # "when the agent emits the documented shape, does the server accept it",
        # and folding "emitted nothing" into that number would blame the docs for
        # a model that answered in prose.
        "no_ops_emitted": len(ops_emitted) == 0,
        "all_ops_accepted": bool(ops_emitted) and all(accepted),
        "task_success": task_ok,
        "hash_handoff_ok": hash_handoff,
        "observation_tokens": obs_tokens,
        "reply_text": raw_reply,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "aci_learning_probe.json")
    ap.add_argument("--repeat", type=int, default=1, help="repeat the whole probe N times")
    ap.add_argument("--seeds", default="42,43,44",
                    help="seeds cycled across repeats (the endpoint may ignore them)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--caps", default=ACI_CAPABILITIES)
    args = ap.parse_args(argv)

    env = load_env()
    model = args.model or env["ACI_BENCH_MODEL"]
    base_url = env["ACI_BENCH_BASE_URL"]
    api_key = env["ACI_BENCH_API_KEY"]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    doc = QUICKSTART.read_text(encoding="utf-8")

    rows: list[dict] = []
    for rep in range(args.repeat):
        seed = seeds[rep % len(seeds)] if seeds else None
        for task in PROBE_TASKS:
            print(f"[{rep + 1}/{args.repeat}] {task['id']} seed={seed} ...", flush=True)
            row = run_probe_task(task, doc=doc, model=model, api_key=api_key,
                                 base_url=base_url, caps=args.caps, seed=seed)
            row["repeat_index"] = rep
            row["seed"] = seed
            rows.append(row)
            print(f"    ops={row['n_ops']} accepted={row['all_ops_accepted']} "
                  f"success={row['task_success']} hash_handoff={row['hash_handoff_ok']} "
                  f"obs_tok={row['observation_tokens']}"
                  + (f"  ERR={row['error']}" if row["error"] else ""), flush=True)

    scored = [r for r in rows if not r["api_error"]]
    n = len(scored) or 1
    acceptance = sum(1 for r in scored if r["all_ops_accepted"]) / n
    success = sum(1 for r in scored if r["task_success"]) / n
    # Acceptance conditional on the agent actually emitting the documented shape.
    emitted = [r for r in scored if not r["no_ops_emitted"]]
    acceptance_given_emitted = (sum(1 for r in emitted if r["all_ops_accepted"]) / len(emitted)
                                if emitted else None)
    handoff_rows = [r for r in scored if r["hash_handoff_ok"] is not None]
    handoff = (sum(1 for r in handoff_rows if r["hash_handoff_ok"]) / len(handoff_rows)) if handoff_rows else None

    payload = {
        "schema": "verseshell.aci_learning_probe/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "api_base": base_url,
        "caps": args.caps,
        "repeat": args.repeat,
        "seeds": seeds,
        "doc_under_test": "docs/quickstart/aci-mcp.md",
        "protocol": "quickstart doc only as system prompt; no tool schemas; one shot; "
                    "every emitted op executed through the real ae --serve --agent",
        "summary": {
            "rows": len(rows),
            "api_error_rows": sum(1 for r in rows if r["api_error"]),
            "scored_rows": len(scored),
            "rows_with_no_ops_emitted": sum(1 for r in scored if r["no_ops_emitted"]),
            "first_attempt_op_acceptance": round(acceptance, 4),
            "op_acceptance_given_ops_emitted": None if acceptance_given_emitted is None
            else round(acceptance_given_emitted, 4),
            "task_success": round(success, 4),
            "hash_handoff_rate": None if handoff is None else round(handoff, 4),
            "hash_handoff_rows": len(handoff_rows),
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "rows": rows,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    s = payload["summary"]
    print(f"\nwrote {args.out}")
    print(f"  first_attempt_op_acceptance = {s['first_attempt_op_acceptance']} "
          f"({s['scored_rows']} scored rows, {s['api_error_rows']} api_error, "
          f"{s['rows_with_no_ops_emitted']} emitted no ops)")
    print(f"  op_acceptance_given_ops_emitted = {s['op_acceptance_given_ops_emitted']}")
    print(f"  task_success                = {s['task_success']}")
    print(f"  hash_handoff_rate           = {s['hash_handoff_rate']} "
          f"({s['hash_handoff_rows']} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
