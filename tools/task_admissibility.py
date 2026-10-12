#!/usr/bin/env python3
"""task_admissibility: the gate a generated task must pass to enter the benchmark.

Generating tasks with an LLM is easy; the hard part is refusing the ones that
cannot support a claim. A task is only admissible when its predicate has been
*shown* to resist the cheap ways of passing it.

Candidate layout (kept out of `bench/aci/tasks/` until it passes):

    bench/aci/candidates/<task_id>/
        task.json          # prompt + success predicate + kind + provenance
        fixture/           # pristine workspace (a plain directory tree)
        GOLDEN/            # overlay that solves it
        variants/<name>/   # overlays that are ALSO correct, written independently
        shortcuts/<name>/  # overlays produced by an adversarial LLM prompt

Checks:

  A1 pristine_fails            the task is genuinely unsolved at the start
  A2 golden_passes             the task is solvable
  A3 variants_pass             >=2 independently written correct answers pass, each
                               on EVERY repeat. A variant whose predicate only
                               sometimes answers "pass" is a flaky verifier, not a
                               usable capability task, so it fails closed.
  A4a verifier_tamper_rejected MECHANICAL: replace every test/verifier artifact in
                               the fixture with a trivially-passing stub and re-run
                               the predicate. It must still FAIL. This is the check
                               that catches "the prompt says don't edit the tests,
                               but nothing enforces it".
  A5 determinism               A1/A2 verdicts stable across repeats
  A6 no_prompt_leak            the prompt does not quote the golden diff
  A7 provenance                generator + independence declaration present

The LLM-produced `shortcuts/` are recorded as INFORMATIONAL, not as a pass/fail
gate, because the signal is ambiguous: a "shortcut" that passes may be a gameable
predicate OR a model that declined to game and wrote a correct fix instead. Only
the mechanical tamper check can tell those apart, so it is the one that gates.
`llm_shortcut_passed` sets `needs_review`.

`kind`:
  capability   solving a real problem. Requires A1-A5, A4a, and anti-gaming
               evidence. ONLY these may feed the capability / token-saving claims.
  mechanics    API or IO mechanics (e.g. "create a file with content X") where the
               predicate is satisfied by the deliverable itself. Legitimate, but
               excluded from capability claims.
  regression   the existing hand-built set, kept as a regression suite.

Usage:
    python tools/task_admissibility.py --out eval/task_admissibility.json
    python tools/task_admissibility.py --candidate bench/aci/candidates/<id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench" / "aci"
CANDIDATES = BENCH / "candidates"
sys.path.insert(0, str(BENCH / "runners"))
from live_agent_loop import check_success, run_bounded
from grading_contract import grading_environment  # noqa: E402

EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/runners/grading_contract.py",
    "tools/task_admissibility.py",
]
REPEATS = 2
MIN_VARIANTS = 2
LEAK_MIN_CHARS = 12
# Admission confirmation window. A flaky verifier is only caught by A2/A5/A3 when one
# of their samples happens to land on the bad verdict, so the rejection is itself
# probabilistic: measured 2026-09-29, `mjs_async_order_525bd589`'s own suite fails on
# ~14% of executions (57 of 402 should-pass executions over 27 audit runs,
# audit-r12-scratch/repair-c14-c16-2026-09-29/flaky-tool-runs*.txt), so with
# REPEATS=2 alone the gate caught it in only 5 of 8 audit runs. A candidate that would
# otherwise be ADMITTED is therefore re-measured `ADMIT_CONFIRM_REPEATS` more times on
# its golden and on every variant; the admission window is then 2 + 16 = 18 samples per
# overlay, 54 in total, and detection is 1-(1-0.142)**54 ~= 99.97% (measured: 11 of 11
# audit runs rejected at this window). This only ever REJECTS (every sample must still
# pass), so it tightens the gate; the extra cost is paid only by candidates that would
# have entered the set, and every sample is recorded.
ADMIT_CONFIRM_REPEATS = 16
# A `tier=large` task must actually produce a large observation. Measured, not
# requested: the first generated large candidate that skipped the "-q" instruction
# produced only 231 tokens of failure output, so "large" has to be a gate, not a
# hope. The target is the raw-shell observation of one run.
LARGE_OBS_MIN_TOKENS = 1000

# Files that act as the VERIFIER rather than the subject of the task. A task that
# can be passed by neutering one of these is not measuring problem-solving.
from grading_contract import VERIFIER_PATTERNS, predicate_executed_paths, freeze_fixture_verifiers, guarded_success
from fixture_deps import materialize_deps

TAMPER_STUB = {
    ".py": "def test_trivially_passes():\n    assert True\n",
    ".rs": "#[test]\nfn trivially_passes() {}\n",
    ".ts": "it('trivially passes', () => {});\n",
    ".js": "process.exit(0);\n",
    ".mjs": "process.exit(0);\n",
    ".cjs": "process.exit(0);\n",
    ".sh": "exit 0\n",
}


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def materialise(candidate: Path, overlays: list[Path] | None = None,
                tamper: bool = False) -> Path:
    """Copy fixture/ to a temp dir, then lay overlays on top (files replace).

    With `tamper=True`, every verifier artifact is additionally replaced by a
    trivially-passing stub.
    """
    ws = Path(tempfile.mkdtemp(prefix=f"adm-{candidate.name}-"))
    src = candidate / "fixture"
    if src.exists():
        for item in src.iterdir():
            dest = ws / item.name
            if item.is_dir():
                shutil.copytree(item, dest,
                                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            else:
                shutil.copy2(item, dest)
    materialize_deps(src,ws)
    for overlay in (overlays or []):
        if overlay is None or not overlay.exists():
            continue
        for path in overlay.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                dest = ws / path.relative_to(overlay)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
    if tamper:
        for pattern in VERIFIER_PATTERNS:
            for path in ws.glob(pattern):
                if path.is_file():
                    stub = TAMPER_STUB.get(path.suffix, "")
                    path.write_text(stub, encoding="utf-8", newline="\n")
    return ws


def verdict(predicate: dict, ws: Path) -> tuple[bool | None, str]:
    try:
        ok, reason = check_success(predicate, ws)
        return (bool(ok) if ok is not None else None), reason
    except Exception as exc:  # a predicate that cannot run is not a pass
        return None, f"predicate_error: {exc}"


def overlays(candidate: Path, kind: str) -> list[Path]:
    d = candidate / kind
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def golden_overlay(candidate: Path) -> Path | None:
    for name in ("GOLDEN", "golden"):
        if (candidate / name).is_dir():
            return candidate / name
    return None


def verifier_artifacts(candidate: Path, predicate: dict) -> list[str]:
    fixture = candidate / "fixture"
    found: set[str] = set()
    for pattern in VERIFIER_PATTERNS:
        for path in fixture.glob(pattern):
            if path.is_file():
                found.add(path.relative_to(fixture).as_posix())
    found.update(predicate_executed_paths(predicate, fixture))
    return sorted(found)


def argv_of(predicate: dict) -> list[str] | None:
    """The first command_exit_0 argv in the predicate tree, if any."""
    if not isinstance(predicate, dict):
        return None
    if predicate.get("type") == "command_exit_0":
        return predicate.get("argv")
    for child in predicate.get("of") or []:
        got = argv_of(child)
        if got:
            return got
    return None


# ── Volatile text in an observation dump ────────────────────────────────────────
#
# A8 gates on the size of the pristine failure dump, and this artifact is evidence:
# two runs of the tool over the same tree must report the same number, or nothing
# built on top of it is reproducible. The RAW dump is not stable run to run. Measured
# 2026-09-29 by running every candidate's predicate twice on a fresh pristine
# workspace and diffing the two decodes
# (audit-r12-scratch/repair-c14-c16-2026-09-29/volatile-diff.txt): 48 of 52
# candidates differed, and every difference belonged to one of these classes:
#
#   audit workspace   ...\Temp\adm-<task>-<8 random chars>   materialise()'s mkdtemp
#   pytest temp root  ...\Temp\pytest-of-<user>\pytest-<N>
#   tempfile dirs     ...\Temp\tmp<8 random chars>
#   elapsed times     "in 0.13s", "(1.6539ms)", "duration_ms 12.38"
#   rust panic ids    "thread 'x' (38056) panicked"
#   CPython reprs     "object at 0x00000191F81404F0"
#   cargo progress    "... 3/9" and "." (cargo test --quiet)
#
# The substitutions below replace each with a fixed placeholder and drop cargo's
# progress meter, whose LINE COUNT itself varies with test interleaving (so a
# placeholder per line would still leave the count unstable) and which carries no
# failure payload. Nothing else is rewritten: a normalisation that touched more than
# the measured volatility would change what the dump represents, and A8 exists to
# measure exactly that. The raw count is recorded alongside so nothing is hidden.
_VOLATILE_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"adm-([A-Za-z0-9_]+)-[A-Za-z0-9_]{8}(?![A-Za-z0-9_])"), r"adm-\1-<rnd>"),
    (re.compile(r"pytest-of-[A-Za-z0-9_.\-]+"), "pytest-of-<user>"),
    (re.compile(r"(?<=[\\/])pytest-\d+(?=[\\/])"), "pytest-<N>"),
    (re.compile(r"\btmp[A-Za-z0-9_]{8}\b"), "tmp<rnd>"),
    (re.compile(r"(?m)in \d+(?:\.\d+)?s(?=[ \t]*=*[ \t]*$)"), "in <t>s"),
    (re.compile(r"\(\d+(?:\.\d+)?ms\)"), "(<t>ms)"),
    (re.compile(r"\bduration_ms \d+(?:\.\d+)?"), "duration_ms <t>"),
    (re.compile(r"(thread '[^']*') \(\d+\)"), r"\1 (<tid>)"),
    (re.compile(r"\bat 0x[0-9a-fA-F]+\b"), "at 0x<addr>"),
)
_VOLATILE_PROGRESS_LINES = re.compile(r"(?m)^[.]{1,}(?:[ \t]+\d+/\d+)?\r?\n")
_VOLATILE_PROGRESS_TAIL = re.compile(r"(?m)^[.]{1,}(?:[ \t]+\d+/\d+)?$")


def normalise_observation(text: str) -> str:
    """Strip the measured-volatile substrings of a predicate dump.

    Idempotent: every placeholder it writes is outside the pattern that produced it,
    so `normalise_observation(normalise_observation(t)) == normalise_observation(t)`.
    Pure string -> string, so it can be tested offline without a workspace.
    """
    for pattern, replacement in _VOLATILE_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    text = _VOLATILE_PROGRESS_LINES.sub("", text)
    return _VOLATILE_PROGRESS_TAIL.sub("", text)


def observation_counts(candidate: Path, predicate: dict,
                       timeout: int = 300) -> dict | None:
    """Run the predicate's own command on the pristine state and count its dump.

    Runs it with full stdout+stderr, unreduced — exactly what condition A sees.
    `tokens` is the same `len(text)//4` proxy over the NORMALISED dump (what A8
    consumes); `raw_tokens`/`raw_chars` keep the un-normalised measurement visible.
    """
    argv = argv_of(predicate)
    if not argv:
        return None
    ws = materialise(candidate)
    try:
        rc, stdout, stderr, timed_out = run_bounded(argv, cwd=ws, timeout=timeout, env=grading_environment(ws))
        if timed_out:
            return None
        raw = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
    except Exception:
        return None
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    clean = normalise_observation(raw)
    return {
        "exit_code": rc,
        "tokens": max(1, len(clean) // 4),
        "raw_tokens": max(1, len(raw) // 4),
        "raw_chars": len(raw),
        "normalised_chars": len(clean),
        "volatile_chars_removed": len(raw) - len(clean),
    }


def pristine_observation_tokens(candidate: Path, predicate: dict,
                                timeout: int = 300) -> int | None:
    """How many observation tokens the raw shell would see on the pristine state.

    Scalar form of `observation_counts(...)["tokens"]`, kept because callers and
    tests use it directly. `None` means the dump could not be measured at all.
    """
    counts = observation_counts(candidate, predicate, timeout=timeout)
    return counts["tokens"] if counts else None


def prompt_leaks(prompt: str, golden: Path | None) -> list[str]:
    if golden is None or not prompt:
        return []
    norm = prompt.replace("\r\n", "\n")
    leaks = []
    for path in sorted(golden.rglob("*")):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if len(line) >= LEAK_MIN_CHARS and line in norm:
                leaks.append(line[:120])
    return sorted(set(leaks))


def run_predicate_on(candidate: Path, overlays_list: list[Path], *, tamper: bool) -> dict:
    predicate = json.loads((candidate / "task.json").read_text(encoding="utf-8-sig"))["success"]
    frozen = freeze_fixture_verifiers(predicate, candidate/'fixture')
    ws = materialise(candidate, overlays_list, tamper=tamper)
    ok, why = guarded_success(predicate, ws, frozen, verdict)
    shutil.rmtree(ws, ignore_errors=True)
    return {"verdict": ok, "detail": why}


def confirm_admission(candidate: Path, golden: Path | None, result: dict) -> None:
    """Re-measure golden + variants more times before letting a candidate enter.

    Called only when every check already passed. A flaky verifier is caught by
    A2/A5/A3 only if one of their samples lands on the bad verdict, so the whole
    admission decision inherits the verifier's flake probability; widening the window
    on the candidates that would actually enter the set is what makes the artifact
    stop changing between identical runs. Mutates `result` in place: every sample is
    appended to the recorded verdict lists, and any instability flips the relevant
    check to False (this can only reject, never admit).
    """
    extra_golden = [run_predicate_on(candidate, [golden], tamper=False)["verdict"]
                    for _ in range(ADMIT_CONFIRM_REPEATS)]
    golden_verdicts = result["golden_verdicts"] + extra_golden
    result["golden_verdicts"] = golden_verdicts
    confirmations = {"golden": extra_golden, "variants": {}}

    if len(set(golden_verdicts)) > 1 or not all(v is True for v in golden_verdicts):
        result["checks"]["A2_golden_passes"] = all(v is True for v in golden_verdicts)
        result["checks"]["A5_determinism"] = False
        result["reasons"]["A2_golden_passes"] = (
            f"GOLDEN verdicts={golden_verdicts}; needs True on all "
            f"{len(golden_verdicts)} samples (A2 + {ADMIT_CONFIRM_REPEATS} admission "
            f"confirmation samples; a flaky verifier is not a usable capability task)")
        result["reasons"]["A5_determinism"] = (
            f"golden flipped inside the admission window: {golden_verdicts}")
    else:
        result["reasons"]["A2_golden_passes"] = (
            f"GOLDEN accepted on all {len(golden_verdicts)} samples")
        result["reasons"]["A5_determinism"] = (
            f"stable over {len(golden_verdicts)} samples "
            f"(A5 window + {ADMIT_CONFIRM_REPEATS} admission confirmation samples)")

    for row in result["variants"]:
        overlay = candidate / "variants" / row["name"]
        extra = [run_predicate_on(candidate, [overlay], tamper=False)["verdict"]
                 for _ in range(ADMIT_CONFIRM_REPEATS)]
        confirmations["variants"][row["name"]] = extra
        verdicts = row["verdicts"] + extra
        row["verdicts"] = verdicts
        row["stable"] = len(set(verdicts)) <= 1
        row["pass"] = all(v is True for v in verdicts)

    a3 = (len(result["variants"]) >= MIN_VARIANTS
          and all(v["pass"] and v["stable"] for v in result["variants"]))
    result["checks"]["A3_variants_pass"] = a3
    result["reasons"]["A3_variants_pass"] = (
        f"{len(result['variants'])} variant(s) all accepted, stable over "
        f"{len(result['variants'][0]['verdicts'])} samples" if a3 else
        f"needs >={MIN_VARIANTS} independently written variants, each accepted on all "
        f"samples; got {[(v['name'], v['verdicts']) for v in result['variants']]}")
    result["admission_confirmation_samples"] = confirmations


def verifier_instability(result: dict) -> str | None:
    """Why A1/A2/A3/A5 saw conflicting verdicts, or None if they were unanimous.

    `None` and `False` are real verdicts, so "unanimous" is about the SET of verdicts
    across the samples, not about all of them being True: a variant that fails every
    time is a wrong variant (A3 rejects it deterministically), while a variant that
    answers both ways is a flaky verifier.
    """
    pristine = result.get("pristine_verdicts") or []
    if len(set(pristine)) > 1:
        return f"pristine verdicts={pristine}"
    golden = result.get("golden_verdicts") or []
    if len(set(golden)) > 1:
        return f"golden verdicts={golden}"
    for row in result.get("variants") or []:
        if not row.get("stable", True):
            return f"variant {row['name']} verdicts={row['verdicts']}"
    return None


def budget_sensitivity_labels(path: Path | None = None) -> dict:
    """Read persisted per-task budget labels; never changes admission verdicts."""
    path = Path(path) if path is not None else ROOT / "eval" / "budget_sensitivity.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels: dict[str, dict] = {}
    for arm in payload.get("arms") or []:
        if not isinstance(arm, dict):
            continue
        for group in arm.get("groups") or []:
            if not isinstance(group, dict):
                continue
            task = group.get("task_id")
            if not isinstance(task, str) or not task:
                continue
            completion = bool(group.get("budget_sensitive_completion",
                                         group.get("budget_sensitive")))
            turn = bool(group.get("budget_sensitive_turn"))
            label = labels.setdefault(task, {
                "status": "measured", "sensitive": False, "axes": set(),
                "source": "eval/budget_sensitivity.json",
                "rule": "docs/acceptance-criteria.md §0.5.2",
            })
            if completion:
                label["sensitive"] = True
                label["axes"].add("completion")
            if turn:
                label["sensitive"] = True
                label["axes"].add("turn")
    return {task: {**label, "axes": sorted(label["axes"])} for task, label in labels.items()}


def audit_candidate(candidate: Path, task: dict) -> dict:
    result: dict = {"candidate": candidate.name, "checks": {}, "reasons": {}}
    predicate = task.get("success")
    kind = task.get("kind", "capability")
    result.update({"task_id": task.get("id"), "kind": kind,
                   "predicate_type": (predicate or {}).get("type"),
                   "lang": task.get("lang")})
    result["checks"]["task_json_present"] = True

    if not predicate:
        result["checks"]["A1_pristine_fails"] = False
        result["reasons"]["A1_pristine_fails"] = "task.json has no success predicate"
        result["admissible"] = False
        return result

    golden = golden_overlay(candidate)
    pristine_verdicts, golden_verdicts = [], []
    for _ in range(REPEATS):
        pristine_verdicts.append(run_predicate_on(candidate, [], tamper=False)["verdict"])
        golden_verdicts.append(run_predicate_on(candidate, [golden], tamper=False)["verdict"])

    a1 = all(v is False for v in pristine_verdicts)
    result["checks"]["A1_pristine_fails"] = a1
    result["reasons"]["A1_pristine_fails"] = (
        "pristine rejected as required" if a1 else
        f"pristine verdicts={pristine_verdicts}; needs False on every repeat "
        f"(None = predicate could not run, fail-closed)")
    result["pristine_verdicts"] = pristine_verdicts

    a2 = all(v is True for v in golden_verdicts)
    result["checks"]["A2_golden_passes"] = a2
    result["reasons"]["A2_golden_passes"] = (
        "GOLDEN accepted" if a2 else f"GOLDEN verdicts={golden_verdicts}; needs True")
    result["golden_verdicts"] = golden_verdicts

    a5 = len(set(pristine_verdicts)) <= 1 and len(set(golden_verdicts)) <= 1
    result["checks"]["A5_determinism"] = a5
    result["reasons"]["A5_determinism"] = (
        f"stable over {REPEATS} repeats" if a5 else
        f"flipped: pristine={pristine_verdicts} golden={golden_verdicts}")

    # A3: every variant is measured REPEATS times, exactly like the pristine and
    # golden overlays above. One sample cannot tell "this variant is a correct
    # answer" from "this variant's predicate is flaky": measured 2026-09-29,
    # `mjs_async_order_525bd589`'s own `node check.mjs` fails ~2-4% of executions
    # (`test_all_tasks_start_concurrently_before_any_settles` asserts the completion
    # ORDER of 9 ms and 10 ms timers), and that single-sample gate flipped between
    # two otherwise identical audit runs. A verifier that cannot answer the same
    # question twice is not a usable capability verifier, so an unstable verdict list
    # fails closed; the list is recorded so the reason is auditable.
    variant_rows = []
    for ov in overlays(candidate, "variants"):
        runs = [run_predicate_on(candidate, [ov], tamper=False) for _ in range(REPEATS)]
        verdicts = [r["verdict"] for r in runs]
        variant_rows.append({
            "name": ov.name,
            "pass": all(v is True for v in verdicts),
            "stable": len(set(verdicts)) <= 1,
            "verdicts": verdicts,
            "detail": runs[-1]["detail"],
        })
    a3 = (len(variant_rows) >= MIN_VARIANTS
          and all(v["pass"] and v["stable"] for v in variant_rows))
    result["checks"]["A3_variants_pass"] = a3
    result["reasons"]["A3_variants_pass"] = (
        f"{len(variant_rows)} variant(s) all accepted, stable over {REPEATS} repeats" if a3 else
        f"needs >={MIN_VARIANTS} independently written variants, each accepted on all "
        f"{REPEATS} repeats; got {[(v['name'], v['verdicts']) for v in variant_rows]}")
    result["variants"] = variant_rows

    # A4a: MECHANICAL tamper resistance. Neutering the verifier must not pass.
    verifiers = verifier_artifacts(candidate, predicate)
    result["verifier_artifacts"] = verifiers
    if verifiers:
        tampered = run_predicate_on(candidate, [], tamper=True)
        a4a = tampered["verdict"] is False
        result["checks"]["A4a_verifier_tamper_rejected"] = a4a
        result["reasons"]["A4a_verifier_tamper_rejected"] = (
            f"neutering {verifiers} still fails the predicate" if a4a else
            f"predicate PASSES after replacing {verifiers} with trivial stubs "
            f"(verdict={tampered['verdict']}) — the task can be passed by tampering "
            f"with its own verifier")
        result["tamper_attempt"] = {"verifiers": verifiers, **tampered}
    else:
        # No verifier artifact to tamper with. Then the anti-gaming evidence has to
        # come from a declared shortcut actually being rejected.
        result["checks"]["A4a_verifier_tamper_rejected"] = True
        result["reasons"]["A4a_verifier_tamper_rejected"] = (
            "not applicable: the fixture ships no test/verifier artifact, so a "
            "declared rejected shortcut is required instead")

    # LLM shortcuts: informational only (a pass is ambiguous — gameable predicate or
    # a model that declined to game). Recorded, and flags review.
    shortcut_rows = []
    for ov in overlays(candidate, "shortcuts"):
        s = run_predicate_on(candidate, [ov], tamper=False)
        shortcut_rows.append({"name": ov.name, "pass": s["verdict"] is True, "detail": s["detail"]})
    rejected = [s for s in shortcut_rows if not s["pass"]]
    passed = [s for s in shortcut_rows if s["pass"]]
    result["shortcuts"] = shortcut_rows
    result["llm_shortcuts_rejected"] = len(rejected)
    result["llm_shortcuts_passed"] = len(passed)
    result["needs_review"] = bool(passed)

    # For a capability task with no verifier artifact, a rejected shortcut is the
    # only anti-gaming evidence available.
    if kind == "capability" and not verifiers:
        ok = len(rejected) >= 1
        result["checks"]["capability_has_rejected_shortcut"] = ok
        result["reasons"]["capability_has_rejected_shortcut"] = (
            "declared shortcut rejected, which is the only anti-gaming evidence "
            "available without a verifier artifact" if ok else
            "no verifier artifact AND no rejected shortcut: nothing demonstrates the "
            "predicate resists gaming")

    leaks = prompt_leaks(task.get("prompt", ""), golden)
    a6 = not leaks
    result["checks"]["A6_no_prompt_leak"] = a6
    result["reasons"]["A6_no_prompt_leak"] = (
        "prompt does not quote the golden diff" if a6 else
        f"prompt quotes {len(leaks)} golden line(s): {leaks[:3]}")
    result["prompt_leaks"] = leaks

    prov = task.get("provenance") or {}
    a7 = bool(prov.get("generator")) and bool(prov.get("independent_of"))
    result["checks"]["A7_provenance"] = a7
    result["reasons"]["A7_provenance"] = (
        "generator + independence declared" if a7 else
        "provenance.generator and provenance.independent_of are both required")
    result["provenance"] = prov

    # A8: a `tier=large` task must ACTUALLY produce a large observation. This is
    # measured on the pristine state with the predicate's own command, unreduced,
    # which is what condition A sees. Without this gate "large" is a hope: the
    # first large candidate that skipped the "-q" instruction yielded 231 tokens.
    obs = observation_counts(candidate, predicate)
    obs_tokens = obs["tokens"] if obs else None
    tier = (task.get("provenance") or {}).get("tier")
    result["tier"] = tier
    result["pristine_observation_tokens"] = obs_tokens
    # The measurement behind A8, un-hidden: the count A8 gates on is the normalised
    # one, and the raw count keeps the size of the actual dump visible.
    result["pristine_observation_raw_tokens"] = obs["raw_tokens"] if obs else None
    result["pristine_observation_raw_chars"] = obs["raw_chars"] if obs else None
    result["pristine_observation_normalised_chars"] = obs["normalised_chars"] if obs else None
    result["pristine_observation_volatile_chars"] = obs["volatile_chars_removed"] if obs else None
    if tier == "large":
        a8 = obs_tokens is not None and obs_tokens >= LARGE_OBS_MIN_TOKENS
        result["checks"]["A8_large_tier_observation_size"] = a8
        result["reasons"]["A8_large_tier_observation_size"] = (
            f"pristine failure dump = {obs_tokens} tokens (target >= {LARGE_OBS_MIN_TOKENS})"
            if a8 else
            f"tier=large but the pristine failure dump is only {obs_tokens} tokens; "
            f"needs >= {LARGE_OBS_MIN_TOKENS}; run every test target/case and compare full "
            f"meaningful payloads, without output padding or `-q`")

    result["admissible"] = all(result["checks"].values())
    if result["admissible"]:
        # Only a candidate that would actually enter the set pays for the wider
        # determinism window; a rejected candidate cannot be destabilised by it.
        confirm_admission(candidate, golden, result)
        result["admissible"] = all(result["checks"].values())

    # A8's number is only a measurement if the predicate is deterministic. If A1/A2/
    # A3/A5 saw conflicting verdicts anywhere, the predicate's own output is not
    # reproducible -- measured 2026-09-29 on `mjs_async_order_525bd589`, whose
    # pristine dump takes 7 different sizes between 6544 and 7343 chars -- so
    # publishing a token count that changes every run would be false evidence. The
    # tool records the sample it took (raw_chars/raw_tokens/detail) and marks the
    # count not measurable instead. This can only reject, and the samples stay in the
    # artifact, so nothing is hidden.
    instability = verifier_instability(result)
    result["verifier_deterministic"] = instability is None
    result["pristine_observation_measurable"] = obs is not None and instability is None
    if instability is not None:
        result["pristine_observation_tokens"] = None
        result["pristine_observation_reason"] = (
            f"not measurable: the predicate is not deterministic ({instability}), so "
            f"its pristine output differs run to run; this run's sample is recorded "
            f"in pristine_observation_raw_chars/pristine_observation_raw_tokens")
        if tier == "large":
            result["checks"]["A8_large_tier_observation_size"] = False
            result["reasons"]["A8_large_tier_observation_size"] = (
                f"pristine failure dump is not measurable: the predicate is not "
                f"deterministic ({instability}); A8 fails closed rather than gate on "
                f"a number that changes every run")
        result["admissible"] = False

    result["failed_checks"] = [k for k, v in result["checks"].items() if not v]
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "task_admissibility.json")
    ap.add_argument("--candidates", type=Path, default=CANDIDATES)
    ap.add_argument("--candidate", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.candidate is not None:
        dirs = [args.candidate]
    elif args.candidates.is_dir():
        dirs = sorted(p for p in args.candidates.iterdir() if p.is_dir())
    else:
        dirs = []
    if not dirs:
        print('ERROR: no candidate inputs; empty audit cannot establish admission',file=sys.stderr)
        return 2
    if any(args.out.resolve().is_relative_to(d.resolve()) for d in dirs):
        ap.error('admission report must be outside candidate inputs')
    def input_hashes():
        return {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()
                for d in dirs for p in sorted(d.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    actual_inputs=input_hashes()

    budget_labels = budget_sensitivity_labels()
    rows = []
    for d in dirs:
        tp = d / "task.json"
        if not tp.exists():
            rows.append({"candidate": d.name, "checks": {"task_json_present": False},
                         "reasons": {"task_json_present": f"missing {tp}"},
                         "admissible": False, "failed_checks": ["task_json_present"],
                         "budget_sensitivity": budget_labels.get(d.name) or {
                             "status": "not_measured", "sensitive": None, "axes": [],
                             "source": "eval/budget_sensitivity.json",
                             "rule": "docs/acceptance-criteria.md §0.5.2"}})
            continue
        row = audit_candidate(d, json.loads(tp.read_text(encoding="utf-8-sig")))
        row["budget_sensitivity"] = budget_labels.get(row.get("task_id") or d.name) or {
            "status": "not_measured", "sensitive": None, "axes": [],
            "source": "eval/budget_sensitivity.json",
            "rule": "docs/acceptance-criteria.md §0.5.2"}
        rows.append(row)

    admissible = [r for r in rows if r.get("admissible")]
    capability = [r for r in admissible if r.get("kind") == "capability"]
    payload = {
        "schema": "verseshell.task_admissibility/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/task_admissibility.py",
        "protocol": {
            "repeats": REPEATS, "min_variants": MIN_VARIANTS,
            "large_obs_min_tokens": LARGE_OBS_MIN_TOKENS,
            "admit_confirm_repeats": ADMIT_CONFIRM_REPEATS,
            "verifier_patterns": list(VERIFIER_PATTERNS),
            "note": "A1-A5, A4a and A8 run live_agent_loop.check_success or the "
                    "predicate's own command, the same evaluator the live runner uses. "
                    "A4a is the mechanical anti-gaming check; the LLM shortcuts are "
                    "informational because a passing one is ambiguous. A8 measures the "
                    "raw-shell observation of the pristine state so `tier=large` is "
                    "enforced rather than hoped for, counting the dump after the "
                    "measured-volatile substrings (temp paths, elapsed times, thread "
                    "ids, object addresses, cargo progress lines) are normalised away "
                    "and recording the raw count alongside. A3 measures every variant "
                    f"{REPEATS} times like A1/A2 and fails closed on an unstable "
                    "verdict list, so a flaky verifier cannot admit a task; a candidate "
                    f"that would still be admitted is re-measured "
                    f"{ADMIT_CONFIRM_REPEATS} more times per overlay before it enters "
                    "the set. When A1/A2/A3/A5 do see conflicting verdicts the "
                    "predicate is not deterministic, so its pristine dump is not a "
                    "reproducible measurement either: A8 records "
                    "pristine_observation_tokens=null with the sample it took and "
                    "fails closed rather than publishing a number that changes every "
                    "run",
        },
        "summary": {
            "candidates": len(rows), "admissible": len(admissible),
            "rejected": len(rows) - len(admissible),
            "admissible_capability": len(capability),
            "admissible_mechanics": len([r for r in admissible if r.get("kind") == "mechanics"]),
            "needs_review": len([r for r in rows if r.get("needs_review")]),
        },
        "budget_sensitivity": {
            "source": "eval/budget_sensitivity.json",
            "labels": len(budget_labels),
            "role": "informational diagnostic attached to candidate records; not an admission gate",
            "rule": "docs/acceptance-criteria.md §0.5.2",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
                     "input_sha256": actual_inputs},
        "candidates": rows,
    }
    if actual_inputs!=input_hashes():
        print('ERROR: candidate inputs changed during admission',file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    print(f"candidates={len(rows)} admissible={len(admissible)} "
          f"(capability={len(capability)}) rejected={len(rows) - len(admissible)} "
          f"needs_review={payload['summary']['needs_review']}")
    for r in rows:
        print(f"  [{'ADMIT' if r.get('admissible') else 'REJECT'}] {r.get('candidate')} "
              f"kind={r.get('kind')} verifiers={r.get('verifier_artifacts')} "
              f"llm_shortcuts(rejected={r.get('llm_shortcuts_rejected')}, "
              f"passed={r.get('llm_shortcuts_passed')})")
        for k in (r.get("failed_checks") or []):
            print(f"          {k}: {r['reasons'].get(k)}")
    return 0 if not rows or len(admissible) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
