#!/usr/bin/env python3
"""TF-0082: audit the ts fixture's two boundaries — toolchain acquisition and success.

The live task set promises the model `tsc --noEmit succeeds` but ships a fixture
without `node_modules`, and it decides success by matching the golden patch as a
*literal string*. Both arms pay the first boundary; condition D pays more of it
because typed ops cannot fold install-and-verify into one command. This tool
answers the three questions TF-0082 asks, deterministically and without any API
call, from the stored live trajectories:

  * **acquisition_chain** — which `exec.run` calls on the two ts tasks exist only
    because of the environment: a genuinely missing TypeScript (a failed `tsc`
    probe), the install that fixes it, and the one verification call the task
    actually needs. It also counts how often the model reaches for a bare
    `npm` / `npx` name, which PATH shadows with an extensionless shim — that was
    the launch defect C22 now fences (TF-0083), so it is reported as an
    observation and never charged as a cost here.
  * **counterfactual / sensitivity** — what the task would cost with the toolchain
    present, and whether that moves either headline D/A ratio (if a conclusion
    flips, the boundary is not merely a caveat);
  * **success_predicate** — re-score the v1.1.0 literal predicate and the v1.2.0
    behavioural one against the pristine file, the golden patch and the file each
    live run actually left behind. The behavioural verdict is a real
    `tsc --noEmit` run against the fixture's pinned TypeScript, so "this fix is
    equivalent" is measured rather than asserted.

The bare-name split is a *machine* fact (like C18's shim probe) and is reported as
one; the rest is a pure function of the stored artifacts.

Usage:
    python tools/ts_fixture_audit.py --out eval/ts_fixture_audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "aci"
RESULTS = BENCH / "results"
TASKS = BENCH / "tasks"
FIXTURES = BENCH / "fixtures"

sys.path.insert(0, str(BENCH / "runners"))
sys.path.insert(0, str(ROOT / "tools"))
from fixture_deps import materialize_deps  # noqa: E402
from trajectory_replay import reconstruct, step_text  # noqa: E402

# The v1.1.0 predicate this task shipped before TF-0084. Kept here so the audit can
# re-score the same stored runs under both and show exactly what the change did.
LEGACY_SUCCESS = {
    "type": "all",
    "of": [
        {"type": "file_contains", "path": "src/index.ts", "contains": "return a + b"},
        {"type": "file_not_contains", "path": "src/index.ts", "contains": "const x: string"},
    ],
}

ARMS = {
    "with_read_files": RESULTS / "latest_live.json",
    "without_read_files": RESULTS / "live_ab_without_read_files.json",
}
# The node's subject first; the second task shares the same machine boundary and
# needs no toolchain of its own, which is what makes the split legible.
TS_TASKS = ("ts_fix_type_error", "ts_package_script_fail")
# Names that npm-family installs ship twice on Windows: an extensionless shim
# (a POSIX shell script) and a `.cmd` launcher. `exec.run` takes argv directly.
SHIM_NAMES = ("npm", "npx", "yarn", "pnpm", "corepack")
INSTALL_HINTS = ("install", "i --", "add ")
EVIDENCE_GLOBS = [
    "src/process_command.rs",
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/tasks/ts_*.json",
    "bench/aci/fixtures/ts_fix_type_error/**/*",
    "bench/aci/fixtures/ts_package_script_fail/**/*",
    "bench/aci/results/latest_live.json",
    "tools/ts_fixture_audit.py",
    "tools/trajectory_replay.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for pat in globs for p in ROOT.glob(pat)
                       if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ── machine facts: which bare names are shadowed by an extensionless shim? ──

def path_shadow_facts() -> dict:
    """Does some PATH directory hold an extensionless `npm` next to `npm.cmd`?

    `resolve_candidate` returns the first *file* it finds and only tries PATHEXT
    when that file does not exist. On an nvm-for-Windows / nodejs install both
    exist, so the bare name resolves to a POSIX shell script that Win32 cannot
    launch. This is the fact that turns a `.cmd` retry into a wasted call.
    """
    entries: dict[str, dict] = {}
    for name in SHIM_NAMES:
        found: list[dict] = []
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            bare = Path(directory) / name
            if not bare.is_file():
                continue
            siblings = sorted(p.name for p in Path(directory).iterdir()
                              if p.is_file() and p.name.lower().startswith(name.lower())
                              and p.name.lower() != name.lower())
            found.append({
                "dir": directory,
                "bare_file": str(bare),
                "bare_is_symlink": bare.is_symlink(),
                "siblings": siblings,
                "shadowed": any(s.lower().endswith((".cmd", ".exe", ".bat")) for s in siblings),
            })
        entries[name] = {"found": bool(found), "shadowed": any(f["shadowed"] for f in found),
                         "hits": found}
    return {
        "shim_names": list(SHIM_NAMES),
        "bare_names": entries,
        "shadowed_names": sorted(n for n, e in entries.items() if e["shadowed"]),
        "resolution_order": "src/process_command.rs::resolve_candidate returns the bare "
                            "file when it exists and only then tries PATHEXT, so the "
                            "extensionless shim wins over the `.cmd` launcher",
    }


# ── step classification ──

def step_tokens(step: dict) -> int:
    return int(step.get("observation_tokens", 0) or 0)


def first_token(step: dict) -> str:
    args = step.get("args") or {}
    argv = args.get("argv")
    if isinstance(argv, list) and argv:
        return str(argv[0])
    return ""


def bare_shim_name(step: dict) -> str | None:
    """A first argv token that is a bare npm-family name (no path, no extension)."""
    token = first_token(step).strip().strip('"')
    if not token or "/" in token or "\\" in token:
        return None
    name = token.lower()
    if name in SHIM_NAMES:
        return name
    return None


def classify(step: dict, shadowed: set[str], condition: str) -> str | None:
    """Name the *observable* bucket a step belongs to, or None for ordinary work.

    It deliberately does **not** infer why a call failed. After the C22 fix a bare
    `npm` / `npx` call starts fine and can still fail as a command (no local
    TypeScript yet), so a failure is never attributed to the launcher here — C22's
    probe is what proves the launch itself works. Rules, in order:

      1. an install through npm / npm-cli.js -> `toolchain_install`;
      2. anything mentioning `tsc` or `node_modules` -> `toolchain_verify` when it
         succeeded, `toolchain_probe_failed` when it did not;
      3. a bare npm-family argv[0] that PATH shadows -> `shadowed_bare_name`, kept
         as an observation (how often the model reaches for a bare name) rather
         than a cost bucket.
    Raw shell folds read/run/write into one command, so its buckets are labelled
    as multiplexed rather than cleanly separable.
    """
    if step.get("op") not in ("exec.run", "run_command"):
        return None
    text = step_text(step).lower()
    ok = bool(step.get("aci_ok")) if condition == "verseshell_aci" else None
    if any(hint in text for hint in INSTALL_HINTS) and ("npm" in text or "npm-cli" in text):
        return "toolchain_install"
    if "tsc" in text or "node_modules" in text:
        if condition == "verseshell_aci":
            return "toolchain_verify" if ok else "toolchain_probe_failed"
        return "raw_shell_toolchain"
    name = bare_shim_name(step)
    if name and name in shadowed:
        return "shadowed_bare_name"
    return None


def chain_report(rows: list[dict], task_id: str, shadowed: set[str]) -> dict:
    """The with-`read_files` arm is the primary record; the paired control arm only
    sizes the effect of hiding one tool, so the chain table is computed on the primary."""
    out: dict = {"task_id": task_id, "arms": {}}
    for condition in ("verseshell_aci", "raw_shell"):
        runs = [r for r in rows if r["task_id"] == task_id and r["condition"] == condition]
        if not runs:
            continue
        per_run = []
        totals: Counter = Counter()
        token_totals: Counter = Counter()
        for row in runs:
            calls = []
            for index, step in enumerate(row.get("trajectory", [])):
                klass = classify(step, shadowed, condition)
                if klass is None:
                    continue
                calls.append({
                    "index": index,
                    "class": klass,
                    "tokens": step_tokens(step),
                    "ok": step.get("aci_ok") if condition == "verseshell_aci" else None,
                    "command": step_text(step)[:120],
                })
                totals[klass] += 1
                token_totals[klass] += step_tokens(step)
            per_run.append({
                "seed": row.get("seed"),
                "success": row.get("success"),
                "success_reason": row.get("success_reason"),
                "steps": row.get("tool_calls"),
                "tokens": row.get("observation_tokens"),
                "boundary_calls": calls,
            })
        n = len(runs)
        out["arms"][f"with_read_files:{condition}"] = {
            "runs": n,
            "per_run": per_run,
            "boundary_calls": sum(totals.values()),
            "boundary_calls_per_run": round(sum(totals.values()) / n, 3),
            "boundary_tokens": sum(token_totals.values()),
            "boundary_tokens_per_run": round(sum(token_totals.values()) / n, 2),
            "by_class": {k: {"calls": totals[k], "tokens": token_totals[k],
                             "calls_per_run": round(totals[k] / n, 3),
                             "tokens_per_run": round(token_totals[k] / n, 2)}
                         for k in sorted(totals)},
            "steps_per_run": round(sum(r.get("tool_calls", 0) for r in runs) / n, 3),
            "tokens_per_run": round(sum(r.get("observation_tokens", 0) for r in runs) / n, 2),
            "note": ("typed ops do one job each, so the classes are separable"
                     if condition == "verseshell_aci" else
                     "raw shell folds read/run/write into one command, so these buckets "
                     "overlap; treat them as an upper bound on A's toolchain share"),
        }
    return out


# ── counterfactual + headline sensitivity ──

def counterfactual(rows: list[dict], task_id: str, shadowed: set[str]) -> dict:
    """D's ts task if the fixture shipped the toolchain: keep the verification, drop
    the failed probe and the install that only exist because `node_modules` is absent."""
    runs = [r for r in rows if r["task_id"] == task_id and r["condition"] == "verseshell_aci"]
    dropped = ("toolchain_install", "toolchain_probe_failed")
    per_run = []
    for row in runs:
        artifact_calls = artifact_tokens = 0
        verify_tokens = 0
        for step in row.get("trajectory", []):
            klass = classify(step, shadowed, "verseshell_aci")
            if klass is None:
                continue
            if klass == "toolchain_verify":
                verify_tokens += step_tokens(step)
                continue
            if klass in dropped:
                artifact_calls += 1
                artifact_tokens += step_tokens(step)
        observed_steps = int(row.get("tool_calls", 0))
        observed_tokens = int(row.get("observation_tokens", 0))
        per_run.append({
            "seed": row.get("seed"),
            "observed_steps": observed_steps,
            "observed_tokens": observed_tokens,
            "boundary_calls": artifact_calls,
            "boundary_tokens": artifact_tokens,
            # the verification the task needs is already excluded from
            # `artifact_calls`, so keeping it is simply "do not drop it"
            "cf_steps": observed_steps - artifact_calls,
            "cf_tokens": observed_tokens - artifact_tokens,
            "verify_tokens": verify_tokens,
        })
    n = len(per_run)
    mean = lambda key: round(sum(r[key] for r in per_run) / n, 3) if n else None  # noqa: E731
    return {
        "task_id": task_id,
        "rule": "keep one verification call, drop every other boundary call",
        "per_run": per_run,
        "observed_steps_per_run": mean("observed_steps"),
        "observed_tokens_per_run": mean("observed_tokens"),
        "boundary_calls_per_run": mean("boundary_calls"),
        "boundary_tokens_per_run": mean("boundary_tokens"),
        "cf_steps_per_run": mean("cf_steps"),
        "cf_tokens_per_run": mean("cf_tokens"),
    }


def sensitivity(rows: list[dict], task_id: str, cf: dict) -> dict:
    """Recompute the headline D/A ratios with only D's ts task counterfactual.

    A pays the same acquisition boundary but folds it into its own commands, so
    this is the *lower* bound on the post-fix step ratio (A would drop too, which
    pushes the ratio back toward the observed value). Both bounds are reported.
    """
    def totals(condition: str) -> tuple[int, int, int]:
        rs = [r for r in rows if r["condition"] == condition]
        return (len(rs), sum(r.get("tool_calls", 0) for r in rs),
                sum(r.get("observation_tokens", 0) for r in rs))

    n_d, steps_d, tokens_d = totals("verseshell_aci")
    n_a, steps_a, tokens_a = totals("raw_shell")
    cf_steps = round(cf["cf_steps_per_run"] * 3)  # 3 seeds of this task
    cf_tokens = round(cf["cf_tokens_per_run"] * 3)
    ts_steps = sum(r.get("tool_calls", 0) for r in rows
                   if r["condition"] == "verseshell_aci" and r["task_id"] == task_id)
    ts_tokens = sum(r.get("observation_tokens", 0) for r in rows
                    if r["condition"] == "verseshell_aci" and r["task_id"] == task_id)
    d_steps = steps_d - ts_steps + cf_steps
    d_tokens = tokens_d - ts_tokens + cf_tokens
    observed = {
        "steps_per_run_D": round(steps_d / n_d, 3),
        "steps_per_run_A": round(steps_a / n_a, 3),
        "step_ratio": round((steps_d / n_d) / (steps_a / n_a), 4),
        "tokens_per_run_D": round(tokens_d / n_d, 2),
        "tokens_per_run_A": round(tokens_a / n_a, 2),
        "token_ratio": round((tokens_d / n_d) / (tokens_a / n_a), 4),
    }
    counterfactual_side = {
        "steps_per_run_D": round(d_steps / n_d, 3),
        "step_ratio": round((d_steps / n_d) / (steps_a / n_a), 4),
        "tokens_per_run_D": round(d_tokens / n_d, 2),
        "token_ratio": round((d_tokens / n_d) / (tokens_a / n_a), 4),
    }
    return {
        "observed": observed,
        "d_only_counterfactual": counterfactual_side,
        "step_ratio_band": [min(observed["step_ratio"], counterfactual_side["step_ratio"]),
                            max(observed["step_ratio"], counterfactual_side["step_ratio"])],
        "token_ratio_band": [min(observed["token_ratio"], counterfactual_side["token_ratio"]),
                             max(observed["token_ratio"], counterfactual_side["token_ratio"])],
        "conclusion_flips": (observed["step_ratio"] > 1) != (counterfactual_side["step_ratio"] > 1)
                            or (observed["token_ratio"] < 1) != (counterfactual_side["token_ratio"] < 1),
    }


# ── success predicate ──

def evaluate(pred: dict, body: str) -> tuple[bool, str]:
    """Mirror of `bench/aci/runners/live_agent_loop.py::check_success` for file predicates."""
    t = pred.get("type")
    if t == "all":
        for child in pred.get("of", []):
            ok, reason = evaluate(child, body)
            if not ok:
                return False, reason
        return True, "all ok"
    if t == "file_contains":
        needle = pred.get("contains", "")
        return (needle in body, f"file_contains {pred.get('path')}")
    if t == "file_not_contains":
        needle = pred.get("contains", "")
        return (needle not in body, f"file_not_contains {pred.get('path')}")
    if t == "file_equals":
        return (body.strip() == str(pred.get("equals", "")).strip(), "file_equals")
    return False, f"unknown predicate {t}"


def tsc_verdict(fixture: Path, body: str, workdir: Path) -> dict:
    """Run the fixture's own `tsc --noEmit` on a reconstructed file.

    The fixture ships a pinned TypeScript under `deps/`, so this is an offline, real
    type check — the same command the task prompt names and the v1.2.0 success
    predicate runs — rather than a string judgement.
    """
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    for item in fixture.iterdir():
        if item.name in ("GOLDEN", "deps"):
            continue
        dest = workdir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    materialize_deps(fixture, workdir)
    (workdir / "src" / "index.ts").write_text(body, encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run(
            ["node", "node_modules/typescript/bin/tsc", "--noEmit"],
            cwd=str(workdir), capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return {"ran": False, "reason": "node is not on PATH"}
    except subprocess.TimeoutExpired:
        return {"ran": False, "reason": "tsc timed out"}
    output = (proc.stdout + proc.stderr).strip()
    return {
        "ran": True,
        "exit_code": proc.returncode,
        "pass": proc.returncode == 0,
        "output_head": output[:200],
    }


def success_report() -> dict:
    task = json.loads((TASKS / "ts_fix_type_error.json").read_text(encoding="utf-8"))
    fixture = FIXTURES / task["workspace_fixture"]
    pristine = (fixture / "src" / "index.ts").read_text(encoding="utf-8")
    golden = (fixture / "GOLDEN" / "src" / "index.ts").read_text(encoding="utf-8")
    pred = task["success"]
    work = Path(tempfile.mkdtemp(prefix="ts-audit-"))

    try:
        # A third, deliberately different fix: same behaviour, different text. The
        # v1.1.0 literal predicate would reject it; the behavioural one must not.
        renamed = ("export function add(a: number, b: number): number {\n"
                   "  const total: number = a + b;\n"
                   "  return total;\n}\n")
        baseline = {}
        for label, body in (("pristine", pristine), ("golden", golden),
                            ("equivalent_rename", renamed)):
            legacy_ok, legacy_reason = evaluate(LEGACY_SUCCESS, body)
            baseline[label] = {
                "body": body,
                "legacy_predicate_pass": legacy_ok,
                "legacy_reason": legacy_reason,
                "tsc": tsc_verdict(fixture, body, work / label),
            }

        runs = json.loads(ARMS["with_read_files"].read_text(encoding="utf-8-sig"))["rows"]
        per_run = []
        for row in runs:
            if row["task_id"] != "ts_fix_type_error":
                continue
            path = "src/index.ts"
            body, how = reconstruct(row["condition"], pristine, row.get("trajectory", []), path)
            entry = {
                "condition": row["condition"],
                "seed": row.get("seed"),
                "recorded_success": row.get("success"),
                "recorded_reason": row.get("success_reason"),
                "reconstructed": body is not None,
                "how": how,
            }
            if body is not None:
                legacy_ok, legacy_reason = evaluate(LEGACY_SUCCESS, body)
                entry.update({
                    "final_body": body,
                    "legacy_predicate_pass": legacy_ok,
                    "legacy_reason": legacy_reason,
                    "removes_type_error": "const x: string" not in body,
                    "keeps_intermediate_binding": "const x:" in body,
                    "tsc": tsc_verdict(fixture, body,
                                       work / f"{row['condition']}-{row.get('seed')}"),
                })
            per_run.append(entry)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    conditions = ("verseshell_aci", "raw_shell")

    def by_condition(predicate) -> dict:
        return {
            condition: {
                "runs": sum(1 for r in per_run if r["condition"] == condition),
                "pass": sum(1 for r in per_run
                            if r["condition"] == condition and predicate(r)),
            }
            for condition in conditions
        }

    legacy_rejected_but_tsc_ok = [
        r for r in per_run
        if r.get("tsc", {}).get("pass") and r.get("legacy_predicate_pass") is False
    ]
    runner_src = (BENCH / "runners" / "live_agent_loop.py").read_text(encoding="utf-8")
    return {
        "task": task["id"],
        "task_version": task.get("version"),
        "prompt": task["prompt"],
        "declared_success": pred,
        "legacy_predicate": LEGACY_SUCCESS,
        "optional_verify": task.get("optional_verify"),
        "baseline": baseline,
        "per_run": per_run,
        "legacy_predicate_pass_by_condition": by_condition(lambda r: r.get("legacy_predicate_pass")),
        "tsc_pass_by_condition": by_condition(lambda r: r.get("tsc", {}).get("pass")),
        "recorded_success_by_condition": by_condition(lambda r: r.get("recorded_success")),
        "runs_where_legacy_rejected_a_passing_fix": len(legacy_rejected_but_tsc_ok),
        "live_runner_optional_verify": {
            "silently_nulled": '"optional_verify": None' in runner_src,
            "records_not_run": '"ran": False' in runner_src,
        },
        "note": "the v1.2.0 predicate runs the command the prompt names (`tsc --noEmit`) "
                "through the fixture's pinned TypeScript, so an equivalent fix passes and a "
                "non-fix fails. The v1.1.0 predicate was a literal golden-patch match; this "
                "section re-scores the same stored runs under both, and the `tsc` verdict is a "
                "real run of the compiler rather than a language judgement.",
    }


# ── fixture facts ──

def fixture_facts() -> dict:
    out = {}
    for fixture in ("ts_fix_type_error", "ts_package_script_fail"):
        root = FIXTURES / fixture
        files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        out[fixture] = {
            "files": files,
            "has_node_modules": (root / "node_modules").exists(),
            "declared_dev_dependencies": package.get("devDependencies") or {},
            "declared_scripts": package.get("scripts") or {},
            "task_file_present": (root / "TASK.md").exists(),
        }
    task = json.loads((TASKS / "ts_fix_type_error.json").read_text(encoding="utf-8"))
    out["machine"] = {
        "tsc_on_path": bool(os.environ.get("PATH")) and any(
            (Path(d) / "tsc").is_file() or (Path(d) / "tsc.cmd").is_file()
            for d in os.environ.get("PATH", "").split(os.pathsep) if d
        ),
        "shipped_dependency_archives": sorted(
            p.name for p in (FIXTURES / "ts_fix_type_error" / "deps").glob("*.tgz")
        ) if (FIXTURES / "ts_fix_type_error" / "deps").is_dir() else [],
        "workspace_local_typescript": "materialised by fixture_deps.materialize_deps "
                                      "during workspace prep (not committed unpacked)",
    }
    out["promise"] = {
        "prompt": task["prompt"],
        "optional_verify": task.get("optional_verify"),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    missing = [str(p) for p in ARMS.values() if not p.exists()]
    if missing:
        print(f"ERROR: missing {missing}", file=sys.stderr)
        return 1

    rows = json.loads(ARMS["with_read_files"].read_text(encoding="utf-8-sig"))["rows"]
    shadow = path_shadow_facts()
    shadowed = set(shadow["shadowed_names"])

    chains = {task: chain_report(rows, task, shadowed) for task in TS_TASKS}
    cf = counterfactual(rows, "ts_fix_type_error", shadowed)
    report = {
        "schema": "verseshell.ts-fixture-audit/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [str(p.relative_to(ROOT)) for p in ARMS.values()],
            "arm": "the chain table is computed on the with_read_files arm, the primary "
                   "record; the paired control arm only sizes the effect of hiding a tool",
            "classify": "exec steps on the ts tasks, by what the command *is*: an npm/npm-cli "
                        "install -> toolchain_install; anything mentioning `tsc`/`node_modules` "
                        "-> toolchain_verify when it succeeded, toolchain_probe_failed when it "
                        "did not; a bare npm-family argv[0] that PATH shadows -> "
                        "shadowed_bare_name (an observation, not a cost bucket). A failure is "
                        "never attributed to the launcher here — C22's probe owns that claim",
            "counterfactual": "keep the verification the task needs, drop the failed probe and "
                              "the install that only exist because `node_modules` is absent",
            "sensitivity": "replace only D's ts task with the counterfactual; A pays the same "
                           "boundary inside its own commands, so the band is a lower bound on "
                           "the post-fix step ratio",
            "success": "mirror of check_success for the file predicates, replayed on the final "
                       "file each run left behind",
        },
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "fixture": fixture_facts(),
        "path_shadow": shadow,
        "acquisition_chain": chains,
        "counterfactual": cf,
        "sensitivity": sensitivity(rows, "ts_fix_type_error", cf),
        "success_predicate": success_report(),
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)

    print(f"shadowed bare names on PATH: {shadow['shadowed_names'] or 'none'}")
    for task in TS_TASKS:
        for arm, payload in chains[task]["arms"].items():
            print(f"[{task} / {arm}] steps/run {payload['steps_per_run']} "
                  f"tokens/run {payload['tokens_per_run']} | boundary calls/run "
                  f"{payload['boundary_calls_per_run']} tokens/run {payload['boundary_tokens_per_run']}")
            for klass, entry in payload["by_class"].items():
                print(f"    {klass:<20} calls={entry['calls']:<3} tokens={entry['tokens']:<5} "
                      f"({entry['calls_per_run']}/run, {entry['tokens_per_run']} tok/run)")
    print(f"counterfactual ts_fix_type_error: {cf['observed_steps_per_run']} steps / "
          f"{cf['observed_tokens_per_run']} tok -> {cf['cf_steps_per_run']} steps / "
          f"{cf['cf_tokens_per_run']} tok")
    s = report["sensitivity"]
    print(f"sensitivity: step ratio {s['observed']['step_ratio']} -> "
          f"{s['d_only_counterfactual']['step_ratio']} (band {s['step_ratio_band']}); "
          f"token ratio {s['observed']['token_ratio']} -> "
          f"{s['d_only_counterfactual']['token_ratio']} (band {s['token_ratio_band']}); "
          f"conclusion flips: {s['conclusion_flips']}")
    sp = report["success_predicate"]
    print(f"success predicate: the legacy literal match rejected a passing fix in "
          f"{sp['runs_where_legacy_rejected_a_passing_fix']} run(s); "
          f"legacy {json.dumps(sp['legacy_predicate_pass_by_condition'], ensure_ascii=False)} vs "
          f"tsc {json.dumps(sp['tsc_pass_by_condition'], ensure_ascii=False)}; "
          f"runner nulls optional_verify = "
          f"{sp['live_runner_optional_verify']['silently_nulled']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
