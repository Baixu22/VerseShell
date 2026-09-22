#!/usr/bin/env python3
"""End-to-end functional effect evaluation for VerseShell ACI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path.cwd()
RESULTS = ROOT / "bench" / "aci" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
OUT = RESULTS / "e2e_effect_eval.json"

AE = None
for c in [
    ROOT / "target" / "debug" / "ae.exe",
    ROOT / "target" / "release" / "ae.exe",
    ROOT / "target" / "debug" / "ae",
    ROOT / "target" / "release" / "ae",
    shutil.which("ae"),
]:
    if c and Path(c).exists():
        AE = str(c)
        break


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def run_ae_ops(ops, workspace: Path, timeout: float = 60.0):
    if not AE:
        raise RuntimeError("ae binary not found")
    env = os.environ.copy()
    env["AETHER_APPROVE_ALL"] = "1"
    env["AETHER_MODE"] = "agent"
    env["AETHER_WORKSPACE"] = str(workspace)
    payload = ("\n".join(json.dumps(op, ensure_ascii=False) for op in ops) + "\n").encode("utf-8")
    p = subprocess.run(
        [AE, "--serve", "--agent"],
        input=payload,
        capture_output=True,
        timeout=timeout,
        env=env,
        cwd=str(workspace),
    )
    text = p.stdout.decode("utf-8", errors="replace")
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("{"):
            continue
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return out


def test_automated_gates():
    section("1) Automated cargo gates")
    tests = [
        "semantic_reducer_tests",
        "operation_protocol_tests",
        "aci_1_0_ops_tests",
        "aci_1_0_closed_loop_acceptance",
        "aci_bench_mock_acceptance",
    ]
    results = {}
    env = os.environ.copy()
    env["AETHER_APPROVE_ALL"] = "1"
    all_ok = True
    for tname in tests:
        p = subprocess.run(
            ["cargo", "test", "--test", tname],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        ok = p.returncode == 0
        results[tname] = {"ok": ok, "returncode": p.returncode}
        if not ok:
            all_ok = False
            results[tname]["tail"] = (p.stdout + p.stderr)[-800:]
        print(tname, "OK" if ok else "FAIL")
    results["effect_pass"] = all_ok
    return results


def test_real_cargo_semantic():
    section("2) Real cargo check via exec.run")
    if not AE:
        return {"skipped": True, "reason": "no ae"}
    if not shutil.which("cargo"):
        return {"skipped": True, "reason": "no cargo"}
    td = Path(tempfile.mkdtemp(prefix="vs-e2e-cargo-"))
    try:
        (td / "src").mkdir()
        (td / "Cargo.toml").write_text(
            '[package]\nname="e2e_broken"\nversion="0.1.0"\nedition="2021"\n',
            encoding="utf-8",
        )
        (td / "src" / "lib.rs").write_text(
            "pub fn add(a: i32, b: i32) -> String {\n    a + b\n}\n",
            encoding="utf-8",
        )
        raw = subprocess.run(
            ["cargo", "check", "--message-format=human"],
            cwd=str(td),
            capture_output=True,
            text=True,
            timeout=180,
        )
        raw_log = (raw.stdout or "") + "\n" + (raw.stderr or "")
        raw_tokens = estimate_tokens(raw_log)
        ops = [
            {
                "id": "c1",
                "agent": "e2e",
                "op": "exec.run",
                "args": {
                    "argv": ["cargo", "check"],
                    "cwd": ".",
                    "profile": "auto",
                    "artifact": "auto",
                },
                "timeout_ms": 180000,
                "budget": {"max_tokens": 4000},
            }
        ]
        resps = run_ae_ops(ops, td, timeout=200)
        if not resps:
            return {"ok": False, "error": "no json response", "effect_pass": False}
        obs = resps[0]
        diags = obs.get("diagnostics") or []
        data = obs.get("data") or {}
        summary = data.get("summary") or (data.get("stdout") or {}).get("summary")
        # Agent-facing payload: summary + diagnostics + stream bodies (not protocol envelope).
        agent_payload = {
            "summary": summary,
            "diagnostics": diags,
            "stdout_text": (data.get("stdout") or {}).get("text"),
            "stderr_text": (data.get("stderr") or {}).get("text"),
            "stats": data.get("stats"),
        }
        agent_tokens = estimate_tokens(json.dumps(agent_payload, ensure_ascii=False))
        obs_tokens = estimate_tokens(json.dumps(obs, ensure_ascii=False))
        has_path = any(d.get("path") for d in diags)
        has_line = any(d.get("line") is not None for d in diags)
        has_code = any(d.get("code") for d in diags)
        has_expected_found = any(d.get("expected") and d.get("found") for d in diags)
        payload_compression = round(1.0 - (agent_tokens / max(raw_tokens, 1)), 4)
        envelope_compression = round(1.0 - (obs_tokens / max(raw_tokens, 1)), 4)
        suggested = obs.get("suggested_next") or []
        suggested_ops = [s.get("op") for s in suggested[:5]]
        stderr_collapsed = (data.get("stderr") or {}).get("text") is None
        stdout_status = (data.get("stdout") or {}).get("status")
        stderr_status = (data.get("stderr") or {}).get("status")
        result = {
            "cargo_failed_as_expected": obs.get("ok") is False,
            "profile": (obs.get("meta") or {}).get("profile"),
            "raw_log_bytes": len(raw_log),
            "raw_tokens_est": raw_tokens,
            "agent_payload_tokens_est": agent_tokens,
            "observation_tokens_est": obs_tokens,
            "token_compression": payload_compression,
            "envelope_compression": envelope_compression,
            "diagnostics_count": len(diags),
            "has_path": has_path,
            "has_line": has_line,
            "has_code": has_code,
            "has_expected_found": has_expected_found,
            "stderr_collapsed": stderr_collapsed,
            "stdout_status": stdout_status,
            "stderr_status": stderr_status,
            "summary": summary,
            "first_diagnostic": diags[0] if diags else None,
            "suggested_next_ops": suggested_ops,
            "meta_token_estimate": (obs.get("meta") or {}).get("token_estimate"),
        }
        # Real usefulness for cargo: structured fix loop signal + no raw body dump.
        result["effect_pass"] = bool(
            result["cargo_failed_as_expected"]
            and result["profile"] == "cargo"
            and len(diags) >= 1
            and has_path
            and has_line
            and has_code
            and "file.view" in suggested_ops
            and stderr_collapsed
            and agent_tokens < raw_tokens
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_git_and_npm_profiles():
    section("3) git status + npm_install reduction")
    if not AE:
        return {"skipped": True}
    td = Path(tempfile.mkdtemp(prefix="vs-e2e-misc-"))
    results = {}
    try:
        if shutil.which("git"):
            subprocess.run(["git", "init"], cwd=str(td), capture_output=True)
            (td / "a.txt").write_text("x\n", encoding="utf-8")
            ops = [
                {
                    "id": "g1",
                    "agent": "e2e",
                    "op": "exec.run",
                    "args": {"argv": ["git", "status"], "cwd": ".", "profile": "auto"},
                    "timeout_ms": 30000,
                    "budget": {"max_tokens": 2000},
                }
            ]
            r = run_ae_ops(ops, td, timeout=40)[0]
            data = r.get("data") or {}
            stdout = data.get("stdout") or {}
            summary = stdout.get("summary") or data.get("summary")
            results["git"] = {
                "profile": (r.get("meta") or {}).get("profile"),
                "ok": r.get("ok"),
                "status": stdout.get("status"),
                "summary": summary,
                "stats": data.get("stats"),
                "effect_pass": (r.get("meta") or {}).get("profile") == "git"
                and bool(summary),
            }
        else:
            results["git"] = {"skipped": True}

        if os.name == "nt":
            argv = [
                "cmd",
                "/C",
                "echo noise && echo added 12 packages && echo found 0 vulnerabilities",
            ]
        else:
            argv = [
                "sh",
                "-c",
                "printf 'noise\\nadded 12 packages\\nfound 0 vulnerabilities\\n'",
            ]
        ops = [
            {
                "id": "n1",
                "agent": "e2e",
                "op": "exec.run",
                "args": {
                    "argv": argv,
                    "cwd": ".",
                    "profile": "npm_install",
                    "artifact": "auto",
                },
                "timeout_ms": 15000,
                "budget": {"max_tokens": 4000},
            }
        ]
        r = run_ae_ops(ops, td, timeout=30)[0]
        data = r.get("data") or {}
        stdout = data.get("stdout") or {}
        summary = stdout.get("summary") or data.get("summary") or ""
        results["npm_install"] = {
            "ok": r.get("ok"),
            "status": stdout.get("status"),
            "summary": summary,
            "text_is_none": stdout.get("text") is None,
            "contains_added": "added" in summary.lower() or "12" in summary,
            "contains_noise": "noise" in summary.lower(),
            "effect_pass": (
                r.get("ok") is True
                and stdout.get("status") == "reduced"
                and stdout.get("text") is None
                and ("added" in summary.lower() or "12" in summary)
                and "noise" not in summary.lower()
            ),
        }
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return results
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_ledger_and_file_ops():
    section("4) file ops + observation ledger")
    if not AE:
        return {"skipped": True}
    td = Path(tempfile.mkdtemp(prefix="vs-e2e-ledger-"))
    try:
        (td / "src").mkdir()
        (td / "src" / "lib.rs").write_text(
            "fn main() { let x = 1; }\n", encoding="utf-8"
        )
        ops = [
            {"id": "1", "agent": "e2e", "op": "ops.list", "args": {}},
            {
                "id": "2",
                "agent": "e2e",
                "op": "file.view",
                "args": {"path": "src/lib.rs", "cursor": 1, "window": 20},
            },
            {
                "id": "3",
                "agent": "e2e",
                "op": "file.replace_exact",
                "args": {
                    "path": "src/lib.rs",
                    "old": "let x = 1;",
                    "new": "let x = 2;",
                },
            },
            {
                "id": "4",
                "agent": "e2e",
                "op": "ops.observation_recent",
                "args": {"limit": 10},
            },
            {
                "id": "5",
                "agent": "e2e",
                "op": "ops.observation_open_errors",
                "args": {},
            },
        ]
        resps = run_ae_ops(ops, td, timeout=40)
        by_id = {r.get("id"): r for r in resps}
        ops_list = by_id.get("1") or {}
        blob = json.dumps(ops_list)
        view = by_id.get("2") or {}
        rep = by_id.get("3") or {}
        recent = by_id.get("4") or {}
        body = (td / "src" / "lib.rs").read_text(encoding="utf-8")
        result = {
            "ops_list_ok": ops_list.get("ok") is True,
            "has_ledger_ops_in_list": "observation_recent" in blob,
            "file_view_ok": view.get("ok") is True,
            "file_view_has_hash": bool(((view.get("data") or {}).get("content_hash"))),
            "replace_ok": rep.get("ok") is True,
            "file_content_updated": "let x = 2;" in body,
            "recent_ok": recent.get("ok") is True,
            "recent_count": ((recent.get("data") or {}).get("count")),
            "n_responses": len(resps),
            "response_ids": list(by_id.keys()),
        }
        result["effect_pass"] = all(
            [
                result["ops_list_ok"],
                result["file_view_ok"],
                result["replace_ok"],
                result["file_content_updated"],
                result["recent_ok"],
                (result["recent_count"] or 0) >= 1,
            ]
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["effect_pass"]:
            print("DEBUG recent", json.dumps(recent, ensure_ascii=False)[:1000])
            print("DEBUG ops_list", blob[:1000])
        return result
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_aci_bench():
    section("5) ACI-Bench mock A/D advantage")
    p = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "aci" / "runners" / "run_suite.py"),
            "--mode",
            "mock",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    latest = json.loads((RESULTS / "latest.json").read_text(encoding="utf-8-sig"))
    cmp_ = (latest.get("comparison") or {}).get("comparisons") or []
    c0 = cmp_[0] if cmp_ else {}
    result = {
        "runner_exit": p.returncode,
        "comparison": c0,
        "effect_pass": bool(c0.get("meets_acceptance")),
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ae_binary": AE,
        "cwd": str(ROOT),
        "cases": {},
    }
    print("AE =", AE)
    report["cases"]["automated_gates"] = test_automated_gates()
    report["cases"]["cargo_semantic"] = test_real_cargo_semantic()
    report["cases"]["git_npm"] = test_git_and_npm_profiles()
    report["cases"]["ledger_file"] = test_ledger_and_file_ops()
    report["cases"]["aci_bench"] = test_aci_bench()

    flags = []
    for name, case in report["cases"].items():
        if not isinstance(case, dict):
            continue
        if case.get("skipped"):
            flags.append((name, "SKIP"))
            continue
        if "effect_pass" in case:
            flags.append((name, "PASS" if case["effect_pass"] else "FAIL"))
        elif name == "git_npm":
            sub = [
                v.get("effect_pass")
                for v in case.values()
                if isinstance(v, dict) and "effect_pass" in v
            ]
            if not sub:
                flags.append((name, "SKIP"))
            else:
                flags.append((name, "PASS" if all(sub) else "FAIL"))
    report["verdict"] = {k: v for k, v in flags}
    fails = [k for k, v in flags if v == "FAIL"]
    passes = [k for k, v in flags if v == "PASS"]
    report["summary"] = {
        "pass": len(passes),
        "fail": len(fails),
        "fail_names": fails,
        "overall": (
            "GOOD"
            if not fails and len(passes) >= 3
            else ("PARTIAL" if len(fails) <= 1 else "POOR")
        ),
    }
    section("VERDICT")
    print(json.dumps(report["verdict"], indent=2))
    print(json.dumps(report["summary"], indent=2))
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = RESULTS / "e2e_effect_eval.md"
    lines = [
        "# E2E Effect Evaluation",
        "",
        "Generated: " + report["generated_at"],
        "Binary: `" + str(AE) + "`",
        "",
        "## Verdict",
        "",
    ]
    for k, v in report["verdict"].items():
        lines.append("- **%s**: %s" % (k, v))
    lines += ["", "## Overall: **%s**" % report["summary"]["overall"], ""]
    cs = report["cases"].get("cargo_semantic") or {}
    if cs and not cs.get("skipped"):
        lines += [
            "## Cargo semantic effect",
            "",
            "- raw tokens est: %s" % cs.get("raw_tokens_est"),
            "- observation tokens est: %s" % cs.get("observation_tokens_est"),
            "- compression: %s" % cs.get("token_compression"),
            "- diagnostics: %s path=%s line=%s code=%s"
            % (
                cs.get("diagnostics_count"),
                cs.get("has_path"),
                cs.get("has_line"),
                cs.get("has_code"),
            ),
            "- summary: %s" % cs.get("summary"),
            "",
        ]
    ab = report["cases"].get("aci_bench") or {}
    if ab.get("comparison"):
        c = ab["comparison"]
        lines += [
            "## ACI-Bench A vs D",
            "",
            "- success A=%s D=%s delta=%s"
            % (
                c.get("success_rate_A"),
                c.get("success_rate_D"),
                c.get("success_advantage_D"),
            ),
            "- tool_calls ratio D/A=%s" % c.get("tool_call_ratio_D_over_A"),
            "- tokens ratio D/A=%s" % c.get("token_ratio_D_over_A"),
            "",
        ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", OUT)
    print("wrote", md)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
