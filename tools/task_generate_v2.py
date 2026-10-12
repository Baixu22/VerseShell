#!/usr/bin/env python3
"""task_generate_v2: generate a candidate task, verified locally before it is written.

Two measured problems drove this design.

1. **One-shot generation is impossible on this endpoint.** Asking for the whole
   task (prompt + fixture + golden + predicate) in one completion made the model
   spend 16381 of 16384 completion tokens on `reasoning_content` and emit **0
   characters**; a larger cap is unavailable because a request past ~300s returns
   502. So the job is split into low-reasoning steps that ask for *code*, not for
   design.

2. **Writing the tests against the BUGGY module produces unusable tasks.** In the
   first v2 pass the gate rejected 16 of 21 candidates, and the failures were
   concentrated in `A2 golden_passes` (16/31) and `A3 variants_pass` (15/31).
   Those denominators belong to that round's 32-candidate cohort; the current
   cohort (35 candidates, 33 of them evaluated by A2/A3) recomputes to
   `A2 17/33`, `A3 15/33` — quote the cohort, because
   `eval/task_admissibility.json` only ever records the current one.
   Tests authored from the buggy behaviour encode wrong expectations, so no
   correct implementation satisfies them — not the generated golden and not the
   independently written variants. The order is therefore reversed to TDD:

       spec -> CORRECT module -> tests that PASS on it -> BUGGY module that FAILS them

   and each candidate is **verified locally before being written**: the tests must
   pass against the correct module and fail against the buggy one. A candidate that
   cannot be made self-consistent is skipped rather than written, which keeps the
   expensive gate from being the first place the inconsistency shows up.

The predicate is assembled by this program from the declared command plus a guard
line lifted from the generated test file, so the verifier guard (A4a) cannot be
forgotten.

Requires a pre-registered generation_policy in the plan (protocol §2.1).

Usage:
    python tools/task_generate_v2.py --plan <new-plan.json> \
        --out bench/aci/candidates --model <pre-registered-author-model> \
        --variant-models sn-kimi-k3,deepseek-v4.1-flash
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from task_generate import chat, load_env  # noqa: E402
sys.path.insert(0, str(ROOT / "bench/aci/runners"))
from live_agent_loop import run_bounded
from grading_contract import grading_environment  # noqa: E402

SPEC_SYSTEM = """You invent small buggy-code exercises for a benchmark.
Answer with ONE line of compact JSON and nothing else. Do not explain.
JSON keys: id, module, func, correct_behaviour (one short sentence saying what the
function SHOULD do), wrong (one short sentence saying how the buggy version misbehaves).
Example: {"id":"python_wordwrap_abc12345","module":"wordwrap","func":"wrap_text","correct_behaviour":"wraps text so no line exceeds the width, splitting words that are too long","wrong":"ignores the width when a single word is longer than it"}"""

CORRECT_SYSTEM = """You write small, correct, self-contained modules.
Reply with a single fenced code block containing the COMPLETE file. No prose."""

TESTS_SYSTEM = """You write test suites. The tests you write MUST PASS against the
correct module you are shown. Reply with a single fenced code block containing the
COMPLETE test file. No prose.
EVERY test function MUST be named `test_<something>` (or `#[test]` for Rust, or an
`it(...)`/`assert` call for Node) so the runner actually collects it — a file whose
functions are not named that way collects zero tests and is useless.
For tier=large, follow the language-specific requirements in the user message.
Use distinct, meaningful long expected values and report complete actual and
expected payloads. Do not print padding, duplicate dumps or unrelated text."""

BUG_SYSTEM = """You introduce exactly ONE subtle bug into a correct module.
Reply with a single fenced code block containing the COMPLETE buggy file. No prose.
Change as little as possible: the bug must be small and localised."""

VARIANT_SYSTEM = """You are given a specification and a test suite that a correct
implementation must pass. Write your OWN correct implementation.
Reply with a single fenced code block containing the COMPLETE file. No prose."""

EXT = {"python": ".py", "rust": ".rs", "typescript": ".mjs"}


def code_block(text: str | None) -> str | None:
    if not text:
        return None
    fence = re.search(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)```", text, re.S)
    if fence:
        return fence.group(1).rstrip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped and not stripped.startswith("{") else None


def with_retry(fn, *, label: str, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            got = fn()
        except Exception as exc:
            print(f"      {label} attempt {attempt}/{attempts} raised "
                  f"{type(exc).__name__}: {str(exc)[:80]}", flush=True)
            got = None
        if got:
            return got
        print(f"      {label} attempt {attempt}/{attempts} returned nothing", flush=True)
        if attempt < attempts:
            time.sleep(5 * attempt)
    return None


def size_instruction(lang: str, tier: str) -> str:
    if tier == "small":
        return " Keep it under 45 lines with a single localised bug."
    if tier != "large":
        return ""
    common = (" Write 12-18 independent test cases exercising the same exported function with "
              "different inputs. Compare meaningful long literal collections or strings in the "
              "assertions, not just lengths or counts. Failures must expose complete actual and "
              "expected values once, without filler, repeated diagnostic copies or logging on success.")
    if lang == "typescript":
        return common + (" Import test from 'node:test' and assert from 'node:assert/strict'. "
                         "Register each case with test('descriptive name', () => { ... }); "
                         "put every assertion inside its own case, never invoke failing cases "
                         "sequentially at module scope. The command uses node --test --test-reporter=tap.")
    if lang == "rust":
        return common + (" Put the cases in the integration test file. Use assert_eq! on the full "
                         "long collections, not assert!(...len()...). Cargo runs --no-fail-fast "
                         "so a failing library test cannot hide the integration test binary.")
    return common


def layout(lang: str, module: str, tier: str) -> dict:
    """Where each piece lives, and the command that runs the suite."""
    ext = EXT.get(lang, ".txt")
    if lang == "rust":
        return {
            "module_file": f"src/lib.rs",
            "test_file": f"tests/{module}_test.rs",
            "extra": {"Cargo.toml": f'[package]\nname = "{module}"\nversion = "0.1.0"\nedition = "2021"\n\n[lib]\npath = "src/lib.rs"\n'},
            "argv": ["cargo", "test", "--no-fail-fast"] if tier == "large" else ["cargo", "test"],
        }
    if lang == "typescript":
        return {"module_file": f"{module}.mjs", "test_file": "check.mjs",
                "extra": {}, "argv": (["node", "--test", "--test-reporter=tap", "check.mjs"]
                                       if tier == "large" else ["node", "check.mjs"])}
    return {"module_file": f"{module}{ext}", "test_file": f"test_{module}.py",
            "extra": {}, "argv": (["python", "-m", "pytest"] if tier == "large"
                                  else ["python", "-m", "pytest", "-q"])}


def smoke_suite(lang: str, lay: dict, module: str, func: str,
                module_body: str) -> dict[str, str]:
    """A minimal file set that COMPILES/IMPORTS the module and asserts nothing.

    The generator used to discover "the correct module does not compile" only through
    the test suite, three attempts later, as `tests attempt N did not pass on the correct
    module` — and then skipped the whole slot. Two rust slots in a row died that way on a
    dangling doc comment at the end of the generated file (`error: expected item after
    doc comment`), with the model never told that its MODULE was broken: it was asked to
    fix the TESTS. Checking the module first turns a wasted slot into a cheap retry of
    the thing that is actually wrong.
    """
    if lang == "rust":
        return {lay["module_file"]: module_body,
                lay["test_file"]: "#[test]\nfn smoke() {}\n", **lay["extra"]}
    if lang == "typescript":
        return {lay["module_file"]: module_body,
                lay["test_file"]: f"import {{ {func} }} from './{module}.mjs';\n"
                                  f"if (typeof {func} !== 'function') {{ process.exit(3); }}\n"}
    return {lay["module_file"]: module_body,
            lay["test_file"]: f"from {module} import {func}\n\n\ndef test_smoke():\n    assert True\n"}


def run_suite(files: dict[str, str], argv: list[str], timeout: int = 300) -> tuple[bool | None, str]:
    ws = Path(tempfile.mkdtemp(prefix="tgen-"))
    try:
        for rel, body in files.items():
            dest = ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8", newline="\n")
        rc, stdout, stderr, timed_out = run_bounded(argv, cwd=ws, timeout=timeout, env=grading_environment(ws))
        if timed_out:
            return None, "suite timed out"
        return rc == 0, stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def generation_policy(plan: dict, task_model: str, variant_models: list[str]) -> dict:
    """Validate declared model families before credentials, generation or resume."""
    policy = plan.get("generation_policy")
    if not isinstance(policy, dict):
        raise ValueError("plan requires generation_policy; see docs/task-generation-protocol.md §2.1")
    cohort = policy.get("cohort")
    if cohort not in {"same_family", "cross_family"}:
        raise ValueError("generation_policy.cohort must be same_family or cross_family")
    evaluated = policy.get("evaluated_model")
    evidence = policy.get("family_evidence")
    if not isinstance(evaluated, str) or not evaluated.strip():
        raise ValueError("generation_policy.evaluated_model is required")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("generation_policy.family_evidence must name the reviewed family source")
    if not task_model or task_model != task_model.strip():
        raise ValueError("--model must name an explicit task author")
    if len(variant_models) < 2 or len(set(variant_models)) != len(variant_models):
        raise ValueError("at least two distinct variant models are required")
    if task_model in variant_models:
        raise ValueError("the task author cannot also author an independent variant")
    families = policy.get("model_families")
    used = sorted(set([evaluated, task_model, *variant_models]))
    if not isinstance(families, dict) or any(
        not isinstance(families.get(model), str) or not families[model].strip() for model in used
    ):
        raise ValueError("model_families must declare the evaluated model, author and every variant")
    families = {model: families[model].strip().casefold() for model in used}
    if any(value in {'unknown','pending','unverified','unspecified','n/a','?'} for value in families.values()):
        raise ValueError('unknown model family cannot establish generation independence')
    same_family = families[task_model] == families[evaluated]
    if same_family != (cohort == "same_family"):
        raise ValueError("declared cohort disagrees with the author/evaluated model families")
    if cohort == "cross_family" and any(
        families[model] == families[evaluated] for model in variant_models
    ):
        raise ValueError("cross_family variants must also be outside the evaluated model family")
    if all(families[model] == families[task_model] for model in variant_models):
        raise ValueError("I4 requires a variant from a different family than the task author")
    return {"cohort": cohort, "evaluated_model": evaluated, "author_model": task_model,
            "variant_models": variant_models, "model_families": families,
            "family_evidence": evidence,
            "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()}


def step(messages: list[dict], model: str, *, key: str, base: str,
         max_tokens: int, label: str) -> str | None:
    """Retry the selected author in chat(); never silently substitute another model."""
    try:
        reply = chat(messages, model=model, key=key, base=base,
                     max_tokens=max_tokens, attempts=2)
    except Exception as exc:
        print(f"      {label}: {model} raised {type(exc).__name__}: {str(exc)[:70]}", flush=True)
        return None
    return reply if reply and reply.strip() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "aci" / "candidates")
    ap.add_argument("--model", required=True, help="explicit task author; never defaults to the evaluated model")
    ap.add_argument("--variant-models", default="sn-kimi-k3,deepseek-v4.1-flash")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    task_model = args.model
    variant_models = [m.strip() for m in args.variant_models.split(",") if m.strip()]
    try:
        policy = generation_policy(plan, task_model, variant_models)
    except ValueError as exc:
        ap.error(str(exc))
    env = load_env()
    base, key = env["ACI_BENCH_BASE_URL"], env["ACI_BENCH_API_KEY"]
    print(f"task author: {task_model}; variant authors: {variant_models}; cohort: {policy['cohort']}")
    jobs = [(e["lang"], e.get("topic", ""), e.get("tier", ""), e.get("index")) for e in plan["plan"]]
    args.out.mkdir(parents=True, exist_ok=True)

    # Resume: a gate-rejected candidate does NOT count as done, so its slot is
    # regenerated instead of being permanently occupied by a bad candidate.
    rejected: set[str] = set()
    adm_path = ROOT / "eval" / "task_admissibility.json"
    if adm_path.exists():
        try:
            adm = json.loads(adm_path.read_text(encoding="utf-8"))
            rejected = {c.get("candidate") for c in adm.get("candidates", [])
                        if not c.get("admissible")}
        except json.JSONDecodeError:
            pass
    done: set[int] = set()
    for d in sorted(p for p in args.out.iterdir() if p.is_dir()):
        tp = d / "task.json"
        if not tp.exists():
            continue
        try:
            prov = json.loads(tp.read_text(encoding="utf-8-sig")).get("provenance") or {}
        except json.JSONDecodeError:
            continue
        if prov.get("generation_policy") != policy:
            continue
        if prov.get("plan_index") is None or d.name in rejected:
            continue
        done.add(int(prov["plan_index"]))
    if done:
        print(f"resume: {len(done)} plan index(es) already admitted")

    made = 0
    for i, (lang, topic, tier, plan_index) in enumerate(jobs, start=1):
        if plan_index in done:
            continue
        seed = uuid.uuid4().hex[:8]
        size_note = size_instruction(lang, tier)
        print(f"\n[{i}/{len(jobs)}] plan#{plan_index} {lang} {tier}", flush=True)

        def do_spec():
            reply = step([{"role": "system", "content": SPEC_SYSTEM},
                          {"role": "user", "content":
                           f"Invent ONE {lang} exercise. Topic: {topic}.{size_note} "
                           f"End the id with _{seed}."}],
                         model=task_model, key=key, base=base, max_tokens=1024, label="spec")
            if not reply:
                return None
            m = re.search(r"\{.*\}", reply, re.S)
            if not m:
                return None
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None

        spec = with_retry(do_spec, label="spec")
        if not spec or not spec.get("module") or not spec.get("correct_behaviour"):
            print("   SKIP: spec step failed", flush=True)
            continue
        tid = re.sub(r"[^a-z0-9_]", "_", str(spec.get("id") or f"gen_{seed}").lower())
        # The spec step occasionally answers with a PATH or a filename instead of a module
        # name: a rust slot came back as `src/lib.rs`, which was then pasted into
        # `Cargo.toml` as `name = "src/lib.rs"` and made all three test attempts fail with
        # "invalid character `/` in package name" — the whole slot was skipped after
        # burning three suites. Normalise whatever arrives into a bare identifier: take
        # the path stem, replace every character that is not valid in an identifier, and
        # make sure it cannot start with a digit (an identifier that starts with a digit
        # is not importable in python and not a legal rust crate name either).
        raw_module = str(spec["module"]).strip()
        module = re.sub(r"[^0-9A-Za-z_]", "_", Path(raw_module).stem) or f"mod_{seed}"
        if not re.match(r"^[A-Za-z_]", module):
            module = "m_" + module
        if module != raw_module:
            print(f"   module name normalised: {raw_module!r} -> {module!r}", flush=True)
        lay = layout(lang, module, tier)
        print(f"   spec: {tid} module={module}", flush=True)

        # 1) CORRECT implementation. Retried until it actually COMPILES/IMPORTS: a
        # truncated or malformed module used to slip through here and only surface as
        # three failed test attempts (see smoke_suite).
        correct = None
        for attempt in range(3):
            candidate_correct = code_block(step(
                [{"role": "system", "content": CORRECT_SYSTEM},
                 {"role": "user", "content":
                  f"Write the complete {lang} file `{lay['module_file']}` implementing this "
                  f"behaviour: {spec['correct_behaviour']}. Export `{spec.get('func')}`. "
                  f"Reply with one fenced code block only."}],
                model=task_model, key=key, base=base, max_tokens=4096, label=f"correct{attempt+1}"))
            if not candidate_correct:
                continue
            smoke_ok, smoke_out = run_suite(
                smoke_suite(lang, lay, module, str(spec.get("func") or module),
                            candidate_correct),
                lay["argv"], timeout=180)
            if smoke_ok is True:
                correct = candidate_correct
                break
            print(f"   correct attempt {attempt+1} does not compile/import (rc={smoke_ok}); "
                  f"regenerating the module", flush=True)
            for line in (smoke_out or "").splitlines()[:10]:
                print(f"      {line[:160]}", flush=True)
        if not correct:
            print("   SKIP: could not produce a correct module that compiles/imports", flush=True)
            continue

        # 2) TESTS that must PASS on the correct module (this is the reversed order)
        test_hint = {
            "rust": f"The test file is `{lay['test_file']}` and must `use {module}::{spec.get('func')};`.",
            "python": f"The test file is `{lay['test_file']}` and must `from {module} import {spec.get('func')}`.",
            "typescript": f"The test file is `{lay['test_file']}` and must `import {{ {spec.get('func')} }} from './{module}.mjs';`",
        }.get(lang, "")
        tests = None
        for attempt in range(3):
            candidate_tests = code_block(step(
                [{"role": "system", "content": TESTS_SYSTEM},
                 {"role": "user", "content":
                  f"Module `{lay['module_file']}`:\n\n{correct}\n\n{test_hint}\n"
                  f"Write the test file that PASSES against this module.{size_note}"}],
                model=task_model, key=key, base=base, max_tokens=4096, label=f"tests{attempt+1}"))
            if not candidate_tests:
                continue
            ok, out = run_suite({lay["module_file"]: correct, lay["test_file"]: candidate_tests,
                                 **lay["extra"]}, lay["argv"])
            if ok is True:
                tests = candidate_tests
                break
            print(f"   tests attempt {attempt+1} did not pass on the correct module "
                  f"(rc={ok}); regenerating", flush=True)
            print("      ---- suite output (first 500 chars) ----", flush=True)
            for line in (out or "").splitlines()[:14]:
                print(f"      {line[:160]}", flush=True)

        if not tests:
            print("   SKIP: could not produce tests that pass on a correct module", flush=True)
            continue

        # 3) BUGGY module that must FAIL those tests. Retried, because a model often
        # introduces a change that the tests do not actually catch.
        buggy = None
        for attempt in range(3):
            candidate_buggy = code_block(step(
                [{"role": "system", "content": BUG_SYSTEM},
                 {"role": "user", "content":
                  f"Correct module `{lay['module_file']}`:\n\n{correct}\n\n"
                  f"Introduce this bug: {spec.get('wrong')}. It MUST make the test suite "
                  f"fail. Reply with one fenced code block only."}],
                model=task_model, key=key, base=base, max_tokens=4096, label=f"buggy{attempt+1}"))
            if not candidate_buggy:
                continue
            fails, _ = run_suite({lay["module_file"]: candidate_buggy, lay["test_file"]: tests,
                                  **lay["extra"]}, lay["argv"])
            if fails is False:
                buggy = candidate_buggy
                break
            print(f"   buggy attempt {attempt+1} did not fail the tests (rc={fails}); retrying",
                  flush=True)
        if not buggy:
            print("   SKIP: could not produce a buggy version that fails the tests", flush=True)
            continue

        # 4) independent correct variants, judged against the same tests
        #
        # The candidate directory is chosen BEFORE anything is written into it. It used
        # to be chosen at the very end, after the variants: the variant writer created
        # `args.out/tid`, which then made the final `if cdir.exists()` branch fire and
        # move `task.json` to `args.out/tid_<seed>` — so the variants ended up in one
        # directory and the task in another. A3 then found zero variants and rejected an
        # otherwise-passing candidate (`python_spiral_order_*`, `python_cronfield_*`).
        cdir = args.out / tid
        if cdir.exists():
            # A rejected candidate may already occupy this id; keep this run's artifacts
            # self-contained under a fresh directory instead of merging into it.
            cdir = args.out / f"{tid}_{seed}"
        cdir.mkdir(parents=True, exist_ok=True)

        prov_variants = []
        for idx, vm in enumerate(variant_models, start=1):
            # Each variant keeps its declared author; failure never changes attribution.
            body = code_block(step(
                [{"role": "system", "content": VARIANT_SYSTEM},
                 {"role": "user", "content":
                  f"Specification: {spec['correct_behaviour']}\n\nTest file ({lay['test_file']}):\n\n"
                  f"{tests}\n\nWrite your own complete `{lay['module_file']}` that passes it. "
                  f"Reply with one fenced code block only."}],
                model=vm, key=key, base=base, max_tokens=4096, label=f"variant{idx}"))
            if not body:
                print(f"   variant {idx} ({vm}) failed to generate", flush=True)
                continue
            vok, _ = run_suite({lay["module_file"]: body, lay["test_file"]: tests, **lay["extra"]},
                               lay["argv"])
            if vok is not True:
                print(f"   variant {idx} ({vm}) does not pass the tests; discarded", flush=True)
                continue
            out_dir = cdir / "variants" / f"v{idx}_{vm}"
            out_dir.mkdir(parents=True, exist_ok=True)
            # `lay["module_file"]` can itself contain a directory for rust ("src/lib.rs"),
            # which is why the parent has to be created rather than assumed: the first
            # rust variant to get this far crashed the whole generator run with
            # FileNotFoundError on `.../v1_sn-kimi-k3/src/lib.rs`.
            v_dest = out_dir / lay["module_file"]
            v_dest.parent.mkdir(parents=True, exist_ok=True)
            v_dest.write_text(body, encoding="utf-8", newline="\n")
            prov_variants.append({"model": vm, "role": "independent_correct_variant",
                                  "saw_golden": False, "verified_passes_tests": True})
            print(f"   variant {idx} ({vm}) ok (verified)", flush=True)

        # 5) predicate assembled here: command + guard line from the real test file
        guard = None
        for line in tests.splitlines():
            s = line.strip()
            if len(s) >= 20 and (s.startswith("assert") or s.startswith("def test")
                                 or s.startswith("#[test]") or "expect(" in s
                                 or "assert." in s):
                guard = s
                break
        of = [{"type": "command_exit_0", "argv": lay["argv"], "timeout_sec": 300}]
        if guard:
            of.append({"type": "file_contains", "path": lay["test_file"], "contains": guard})
        success = of[0] if len(of) == 1 else {"type": "all", "of": of}

        # `cdir` was already chosen and created before the variants were written, so the
        # task, its fixture, its GOLDEN and its variants all land in the same directory.
        (cdir / "fixture").mkdir(parents=True, exist_ok=True)
        (cdir / "GOLDEN").mkdir(parents=True, exist_ok=True)
        fixture = {lay["module_file"]: buggy, lay["test_file"]: tests, **lay["extra"]}
        for rel, body in fixture.items():
            dest = cdir / "fixture" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8", newline="\n")
        dest = cdir / "GOLDEN" / lay["module_file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(correct, encoding="utf-8", newline="\n")

        task = {
            "id": tid, "kind": "capability", "lang": lang,
            "prompt": (f"The test suite for `{lay['module_file']}` fails. "
                       f"{spec['wrong'].capitalize()}. Fix the module so the suite passes, "
                       f"without changing {lay['test_file']}."),
            "fixture": fixture, "golden": {lay["module_file"]: correct}, "success": success,
            "provenance": {
                "generator": task_model,
                "generation_policy": policy,
                "generator_role": "task author (TDD-ordered, locally self-verified)",
                "independent_of": "no VerseShell/ACI/benchmark context was provided to any "
                                  "generator; variants were written from the spec and tests, "
                                  "never from the golden patch",
                "variants": prov_variants, "plan_index": plan_index, "tier": tier or None,
                "self_verified": {"tests_pass_on_correct": True, "tests_fail_on_buggy": True,
                                  "variants_verified": len(prov_variants)},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        (cdir / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8", newline="\n")
        print(f"   wrote {cdir.name}: variants={len(prov_variants)} guard={bool(guard)}", flush=True)
        made += 1

    print(f"\nwrote {made} candidate(s) under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
