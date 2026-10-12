#!/usr/bin/env python3
"""task_generate: build candidate benchmark tasks with an LLM, under a protocol.

The point is NOT "let a model write tasks". The point is to produce tasks whose
verification can survive `tools/task_admissibility.py`, and to keep the generator
from seeing the thing under test.

Independence protocol (enforced here, checked again by the admissibility gate):

  1. The generation prompt contains NO reference to VerseShell, the ACI surface,
     typed ops, observation tokens, or this benchmark. It states only: the target
     language, the success-predicate vocabulary, the workspace shape, and the JSON
     schema. A generator that knows what the interface is good at will produce
     interface-friendly tasks, which is self-confirmation.
  2. The task prompt must not state the fix. A prompt that quotes the golden diff
     tests instruction-following, not problem-solving.
  3. Correct answers (variants) are written by models that do NOT see the golden
     patch — only the prompt, the pristine fixture and the predicate. Passing
     therefore demonstrates that the predicate scores behaviour, not one wording.
  4. At least one variant uses a DIFFERENT model family from the task author, and
     that is recorded in provenance.
  5. Adversarial "shortcuts" (patches that try to satisfy the predicate without
     solving the problem) must be produced and must FAIL. A capability task with no
     rejected shortcut cannot be admitted.

Usage:
    python tools/task_generate.py --count 2 --lang python \
        --out bench/aci/candidates --model sn-glm-5-3-flash \
        --variant-models sn-kimi-k3,deepseek-v4.1-flash
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL = ROOT / ".env.local"

SYSTEM = """You design small, self-contained software tasks for a benchmark.

You will be asked for ONE task. The workspace is a plain directory tree on the
local machine (Windows, with python / cargo / node available). The task must be
solvable by editing files in that tree, with no network access.

Reply with ONE JSON object and nothing else. No prose, no markdown fences.

Schema:
{
  "id": "<lower_snake_case, unique, starts with the language>",
  "kind": "capability",
  "lang": "<python|rust|typescript|text>",
  "prompt": "<one or two sentences telling the agent WHAT is wrong, never HOW to fix it>",
  "fixture": { "<relative/path>": "<full file content>" },
  "golden":  { "<relative/path>": "<full file content after a correct fix>" },
  "success": <predicate>
}

The success predicate is checked against the workspace directory after the agent
finishes. Vocabulary (use exactly these shapes):
  {"type":"command_exit_0","argv":["python","-m","pytest","-q"],"timeout_sec":120}
  {"type":"file_equals","path":"a.txt","equals":"OK"}
  {"type":"file_contains","path":"a.py","contains":"needle"}
  {"type":"file_not_contains","path":"a.py","contains":"needle"}
  {"type":"file_matches","path":"a.txt","pattern":"regex"}
  {"type":"all","of":[<predicate>, ...]}

STRONG PREFERENCE: use `command_exit_0` that runs the project's own tests, so the
task is scored by behaviour. Do not write a predicate that just looks for a string
the prompt already tells the agent to write.

Hard rules:
- The prompt must NOT contain the fixed code, and must not name the exact edit.
- `fixture` must be complete and runnable, and must FAIL the predicate as given.
- `golden` must be the minimal edit set that makes the predicate pass.
- Keep the tree small: 1-4 files.
- **Be terse and emit the JSON immediately.** Do not deliberate at length, do not
  plan in prose, do not restate the schema. The served models spend most of their
  completion budget on internal reasoning, and a long deliberation produces an
  empty or truncated answer.
- **The task must not be passable by tampering with its own verifier.** If the
  fixture ships a test file, do NOT modify it in `golden`, and add a guard clause
  to the predicate: an `all` whose `of` includes both the behaviour check AND a
  `file_contains` on a distinctive verbatim line of that test file. Without the
  guard, "delete the assertions" passes and the task measures nothing.
"""

VARIANT_SYSTEM = """You are given a task prompt, the starting files, and the exact
pass/fail check the workspace must satisfy. Write a CORRECT fix.

Reply with ONE JSON object and nothing else: {"files": {"<relative/path>": "<full new content>"}}

Only include files you actually change. Do not touch any test or verification file
unless the task is about it. There may be several valid fixes; write your own.
"""

SHORTCUT_SYSTEM = """You are given a task prompt, the starting files, and the exact
pass/fail check. Your job is to try to make that check PASS WITHOUT actually
solving the underlying problem — the laziest possible way.

Reply with ONE JSON object and nothing else: {"files": {"<relative/path>": "<full new content>"}}

Examples of the spirit: hardcode the expected output, write the literal string the
check looks for, edit the test or config that the check reads, or stub the function
instead of fixing it. Include only the files you change.
"""


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def chat(messages: list[dict], *, model: str, key: str, base: str,
         max_tokens: int = 16384, attempts: int = 4) -> str | None:
    """One completion, with retry. Returns None when every attempt failed.

    The endpoint intermittently returns 502/500 and drops connections; it also
    502s outright when a generation runs past ~300s (measured). Returning None
    instead of raising keeps one un-generatable job from killing the whole plan —
    the caller skips it and the run continues.
    """
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.9}
    body = json.dumps(payload).encode()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                f"{base.rstrip('/')}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.loads(r.read().decode())
            content = (data["choices"][0]["message"].get("content") or "")
            # An empty completion is a FAILURE, not a result. The served reasoning
            # models sometimes return HTTP 200 with `finish_reason: length` and an
            # empty content string because reasoning_content consumed the entire
            # budget (measured: 16381 of 16384 tokens on reasoning, 0 chars of
            # content). Treating that as success made the caller see "nothing" and
            # silently skip a whole job.
            if not content.strip():
                raise RuntimeError(
                    "empty content (finish_reason="
                    f"{data['choices'][0].get('finish_reason')}, reasoning consumed the budget)")
            return content
        except Exception as exc:  # HTTPError, URLError, JSON decode, timeout
            last = exc
            wait = min(30, 5 * (2 ** attempt))
            print(f"      retry {attempt + 1}/{attempts} after {type(exc).__name__}: "
                  f"{str(exc)[:100]} (sleep {wait}s)", flush=True)
            time.sleep(wait)
    print(f"      GIVING UP on this call after {attempts} attempts: {last}", flush=True)
    return None


def extract_json(text: str | None) -> dict | None:
    """Strip fences/prose and parse the first balanced JSON object."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def write_overlay(directory: Path, files: dict) -> None:
    for rel, content in files.items():
        dest = directory / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(str(content), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--lang", default="python", help="python|rust|typescript|text")
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "aci" / "candidates")
    ap.add_argument("--model", default=None)
    ap.add_argument("--variant-models", default="",
                    help="comma-separated models used for the independently written "
                         "correct variants (use a different family from --model)")
    ap.add_argument("--topic", default="", help="optional nudge, e.g. 'parsing'")
    ap.add_argument("--plan", type=Path, default=None,
                    help="execute a pre-registered plan JSON (see "
                         "bench/aci/candidates/FULL_PLAN.json) instead of --count/--lang")
    args = ap.parse_args(argv)

    env = load_env()
    base, key = env["ACI_BENCH_BASE_URL"], env["ACI_BENCH_API_KEY"]
    task_model = args.model or env["ACI_BENCH_MODEL"]
    variant_models = [m.strip() for m in args.variant_models.split(",") if m.strip()] or [task_model]

    if args.plan is not None:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        jobs = [(e["lang"], e.get("topic", ""), e.get("tier", ""), e.get("index"))
                for e in plan["plan"]]
        print(f"plan mode: {len(jobs)} job(s) from {args.plan.name} "
              f"(pre-registered, not to be reordered)")
    else:
        jobs = [(args.lang, args.topic, "", None)] * args.count

    args.out.mkdir(parents=True, exist_ok=True)

    # Resume support: a plan index already represented on disk is skipped, so a
    # transient failure costs one job instead of the whole run. A candidate that
    # the admissibility gate REJECTED does not count as done — otherwise a bad
    # candidate would permanently occupy its plan slot and never be regenerated.
    rejected_candidates: set[str] = set()
    adm_path = ROOT / "eval" / "task_admissibility.json"
    if adm_path.exists():
        try:
            adm = json.loads(adm_path.read_text(encoding="utf-8"))
            rejected_candidates = {c.get("candidate") for c in adm.get("candidates", [])
                                   if not c.get("admissible")}
        except json.JSONDecodeError:
            pass
    done_indices: set[int] = set()
    if args.plan is not None:
        for d in sorted(p for p in args.out.iterdir() if p.is_dir()):
            tp = d / "task.json"
            if not tp.exists():
                continue
            try:
                prov = (json.loads(tp.read_text(encoding="utf-8-sig")).get("provenance") or {})
            except json.JSONDecodeError:
                continue
            if prov.get("plan_index") is None:
                continue
            if d.name in rejected_candidates:
                print(f"  plan#{prov['plan_index']} candidate {d.name} was REJECTED by the "
                      f"gate; it will be regenerated", flush=True)
                continue
            done_indices.add(int(prov["plan_index"]))
        if done_indices:
            print(f"resume: {len(done_indices)} plan index(es) already admitted, skipping them")

    made = 0
    for i, (lang, topic, tier, plan_index) in enumerate(jobs, start=1):
        if plan_index is not None and int(plan_index) in done_indices:
            print(f"\n[{i}/{len(jobs)}] plan#{plan_index} already done, skipping", flush=True)
            continue
        seed = uuid.uuid4().hex[:8]
        size_note = ""
        if tier == "large":
            size_note = (" SIZE REQUIREMENT: keep the fixture SMALL (one module of 30-50 lines "
                         "plus a test file), but include 12-18 FAILING tests whose assertions "
                         "print long values, and make the pass check run the test suite WITHOUT "
                         "`-q` so the pristine failure dump is long. The large observation must "
                         "come from the failure output, not from big source files.")
        elif tier == "small":
            size_note = " SIZE REQUIREMENT: one small file under 60 lines, one localised bug."
        label = f"[{i}/{len(jobs)}]" + (f" plan#{plan_index}" if plan_index else "")
        user = (f"Design ONE {lang} capability task."
                + (f" Topic: {topic}." if topic else "")
                + size_note
                + f" Use a unique id ending in _{seed}.")
        print(f"\n{label} lang={lang} tier={tier or '-'} author={task_model}\n  {topic[:100]}",
              flush=True)
        reply = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                     model=task_model, key=key, base=base)
        if reply is None:
            print("   SKIP: task generation failed after retries (job not written)", flush=True)
            continue
        task = extract_json(reply)
        if not task or "fixture" not in task or "golden" not in task or "success" not in task:
            print("   REJECT: unparseable or incomplete task JSON")
            continue

        tid = re.sub(r"[^a-z0-9_]", "_", str(task.get("id") or f"gen_{seed}").lower())
        cdir = args.out / tid
        if cdir.exists():
            cdir = args.out / f"{tid}_{seed}"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "fixture").mkdir(exist_ok=True)
        write_overlay(cdir / "fixture", task["fixture"])
        write_overlay(cdir / "GOLDEN", task["golden"])
        print(f"   wrote {cdir.name}: fixture={len(task['fixture'])} file(s), "
              f"golden={len(task['golden'])} file(s)")

        # Order matters: the variant model sees the prompt + fixture + predicate ONLY,
        # never the golden patch.
        predicate_line = json.dumps(task["success"], ensure_ascii=False)
        fixture_blob = json.dumps(task["fixture"], ensure_ascii=False)
        provenance_variants = []
        for index, vm in enumerate(variant_models[:2], start=1):
            print(f"   variant {index} author = {vm} (no golden in context) ...", flush=True)
            vreply = chat([
                {"role": "system", "content": VARIANT_SYSTEM},
                {"role": "user", "content":
                    f"TASK PROMPT:\n{task['prompt']}\n\nSTARTING FILES:\n{fixture_blob}\n\n"
                    f"PASS CHECK:\n{predicate_line}\n\nWrite a correct fix."},
            ], model=vm, key=key, base=base, max_tokens=8192)
            variant = extract_json(vreply)
            if variant and isinstance(variant.get("files"), dict) and variant["files"]:
                write_overlay(cdir / "variants" / f"v{index}_{vm}", variant["files"])
                provenance_variants.append({"model": vm, "role": "independent_correct_variant",
                                            "saw_golden": False})
                print(f"      ok ({len(variant['files'])} file(s))")
            else:
                print("      REJECT: unparseable variant")

        print(f"   shortcut author = {task_model} ...", flush=True)
        sreply = chat([
            {"role": "system", "content": SHORTCUT_SYSTEM},
            {"role": "user", "content":
                f"TASK PROMPT:\n{task['prompt']}\n\nSTARTING FILES:\n{fixture_blob}\n\n"
                f"PASS CHECK:\n{predicate_line}"},
        ], model=task_model, key=key, base=base, max_tokens=8192)
        shortcut = extract_json(sreply)
        if shortcut and isinstance(shortcut.get("files"), dict) and shortcut["files"]:
            write_overlay(cdir / "shortcuts" / "lazy", shortcut["files"])
            print(f"      ok ({len(shortcut['files'])} file(s))")
        else:
            print("      REJECT: unparseable shortcut")

        task["provenance"] = {
            "generator": task_model,
            "generator_role": "task_and_golden_author",
            "independent_of": "no VerseShell/ACI/benchmark context was provided to any "
                              "generator; variants were written without the golden patch",
            "variants": provenance_variants,
            "plan_index": plan_index,
            "tier": tier or None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        (cdir / "task.json").write_text(
            json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        made += 1

    print(f"\nwrote {made} candidate(s) under {args.out}")
    print("next: python tools/task_admissibility.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
