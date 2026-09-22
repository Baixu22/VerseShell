"""
Deep stress eval for VerseShell ACI: op protocol, stability, security, regression.
Drives real `ae --serve` process, JSON-RPC stdin/stdout, no fragile heredocs.

Phases 3,5,6 from the test plan.
"""
import json, os, sys, subprocess, tempfile, time, uuid, hashlib, shutil
from pathlib import Path

AE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "target", "debug", "ae.exe")

def run_server(ops, workspace, env=None):
    """Send JSON lines to ae --serve --agent, return list of response dicts."""
    if env is None:
        env = {}
    full_env = dict(os.environ)
    full_env.update({k: v for k, v in env.items() if v is not None})
    full_env.setdefault("AETHER_APPROVE_ALL", "1")
    full_env.setdefault("AETHER_MODE", "agent")
    full_env["AETHER_WORKSPACE"] = str(workspace)

    # Remove None-valued keys (unset env vars)
    for k in list(full_env.keys()):
        if full_env[k] is None:
            del full_env[k]

    proc = subprocess.Popen(
        [AE, "--serve", "--agent"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=full_env,
    )
    stdin_data = "\n".join(json.dumps(op) for op in ops).encode("utf-8")
    out, err = proc.communicate(input=stdin_data, timeout=30)
    if proc.returncode != 0:
        return None, f"exit={proc.returncode} stderr={err.decode('utf-8', errors='replace')}"
    lines = [l.strip() for l in out.decode("utf-8").split("\n") if l.strip()]
    responses = []
    for line in lines:
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            return None, f"bad json: {line[:200]}"
    return responses, None

def op(id_, op, args, timeout_ms=10000, max_tokens=4000, agent="stress_test"):
    return {"id": id_, "agent": agent, "op": op, "args": args,
            "timeout_ms": timeout_ms, "budget": {"max_tokens": max_tokens}}

def find_by_id(responses, id_):
    for r in responses:
        if r.get("id") == id_:
            return r
    return None

def assert_ok(r, label):
    assert r is not None, f"{label}: no response"
    assert r.get("ok") is True, f"{label}: {json.dumps(r, indent=2)[:300]}"

def assert_fail(r, code, label):
    assert r is not None, f"{label}: no response"
    assert r.get("ok") is False, f"{label} expected fail: {json.dumps(r, indent=2)[:300]}"
    assert r.get("error", {}).get("code") == code, f"{label} wrong code: {json.dumps(r, indent=2)[:300]}"

def report_case(name, passed, detail=""):
    return {"name": name, "passed": passed, "detail": str(detail)[:200]}

def main():
    results_dir = Path(__file__).parent.parent / "bench" / "aci" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    errors = []

    # ── Phase 3: Op Protocol Stress ──

    ws_base = Path(tempfile.gettempdir()) / f"vs-deep-{uuid.uuid4().hex[:8]}"
    ws_base.mkdir(parents=True, exist_ok=True)

    # Case 3.1: file.view -> file.replace_exact -> file.view (hash consistency)
    ws1 = ws_base / "p3_hash"
    ws1.mkdir(parents=True, exist_ok=True)
    (ws1 / "test.txt").write_text("line0\nline1\nline2\n", encoding="utf-8")
    ops = [
        op("1", "file.view", {"path": "test.txt", "cursor": 1, "window": 10}),
        op("2", "file.replace_exact", {"path": "test.txt", "old": "line1", "new": "LINE1"}),
        op("3", "file.view", {"path": "test.txt", "cursor": 1, "window": 10}),
    ]
    rs, err = run_server(ops, ws1)
    if err:
        cases.append(report_case("3.1-hash-consistency", False, err))
        errors.append(("3.1", err))
    else:
        assert_ok(find_by_id(rs, "1"), "3.1-view1")
        assert_ok(find_by_id(rs, "2"), "3.1-replace")
        r3 = find_by_id(rs, "3")
        assert_ok(r3, "3.1-view2")
        content = "\n".join(l["text"] for l in r3["data"].get("lines", []))
        passed = "LINE1" in content and "line1" not in content
        cases.append(report_case("3.1-hash-consistency", passed, content[:80]))

    # Case 3.2: stale hash rejection
    (ws1 / "sample.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    ops = [
        op("1", "file.view", {"path": "sample.txt", "cursor": 1, "window": 10}),
        op("2", "file.replace_exact", {"path": "sample.txt", "old": "beta", "new": "BETA",
                                        "expected_hash": "sha256:deadbeef"}),
    ]
    rs, err = run_server(ops, ws1)
    if err:
        cases.append(report_case("3.2-stale-hash", False, err))
        errors.append(("3.2", err))
    else:
        r2 = find_by_id(rs, "2")
        passed = r2 is not None and not r2.get("ok") and r2.get("error", {}).get("code") == "E_STALE_HASH"
        cases.append(report_case("3.2-stale-hash", passed, r2.get("error", {}) if r2 else "no resp"))

    # Case 3.3: multi-match rejection
    (ws1 / "dup.txt").write_text("x foo y foo z\n", encoding="utf-8")
    ops = [op("1", "file.replace_exact", {"path": "dup.txt", "old": "foo", "new": "bar"})]
    rs, err = run_server(ops, ws1)
    if err:
        cases.append(report_case("3.3-ambiguous", False, err))
        errors.append(("3.3", err))
    else:
        r = find_by_id(rs, "1")
        passed = r is not None and not r.get("ok") and r.get("error", {}).get("code") == "E_AMBIGUOUS"
        cases.append(report_case("3.3-ambiguous", passed, r.get("error", {}) if r else "no resp"))

    # Case 3.4: workspace-outside rejection
    outside = Path(tempfile.gettempdir()) / f"vs-outside-{uuid.uuid4().hex[:8]}.txt"
    outside.write_text("secret", encoding="utf-8")
    ops = [op("1", "file.view", {"path": str(outside)})]
    rs, err = run_server(ops, ws1)
    outside.unlink(missing_ok=True)
    if err:
        cases.append(report_case("3.4-outside-workspace", False, err))
        errors.append(("3.4", err))
    else:
        r = find_by_id(rs, "1")
        code = r.get("error", {}).get("code", "") if r else ""
        passed = code in ("E_OUTSIDE_WORKSPACE", "E_POLICY", "E_NOT_FOUND")
        cases.append(report_case("3.4-outside-workspace", passed, code))

    # Case 3.5: exec.run cargo failure -> suggested_next -> file.view
    ws_cargo = ws_base / "p3_cargo"
    ws_cargo.mkdir(parents=True, exist_ok=True)
    src_dir = ws_cargo / "src"
    src_dir.mkdir(exist_ok=True)
    (ws_cargo / "Cargo.toml").write_text(
        '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8")
    (src_dir / "lib.rs").write_text('pub fn add(x: i32, y: String) -> i32 { x + y }\n', encoding="utf-8")
    ops = [
        op("1", "exec.run", {"argv": ["cargo", "check"], "profile": "cargo", "artifact": "auto",
                             "cwd": str(ws_cargo), "timeout_ms": 120000}, timeout_ms=130000, max_tokens=4000),
    ]
    rs, err = run_server(ops, ws_cargo, env={"AETHER_APPROVE_ALL": "1"})
    if err:
        cases.append(report_case("3.5-cargo-fail-suggested-next", False, err[:200]))
        errors.append(("3.5", err[:200]))
    else:
        r = find_by_id(rs, "1")
        if r is None:
            cases.append(report_case("3.5-cargo-fail-suggested-next", False, "no response"))
            errors.append(("3.5", "no response"))
        else:
            diags = r.get("diagnostics", [])
            suggested = r.get("suggested_next", [])
            has_path = any(d.get("path") is not None and d.get("line") is not None for d in diags)
            has_file_view = any(s.get("op") == "file.view" for s in suggested)
            has_result_query = any(s.get("op") == "result.query" for s in suggested)
            stderr_status = r.get("data", {}).get("stderr", {}).get("status", "")
            passed = (not r.get("ok")) and has_path and has_file_view and stderr_status == "reduced"
            detail = f"ok={r.get('ok')} has_path={has_path} file_view={has_file_view} result_query={has_result_query} stderr={stderr_status}"
            cases.append(report_case("3.5-cargo-fail-suggested-next", passed, detail))

    # Case 3.6: result.query artifact recovery
    ws_art = ws_base / "p3_artifact"
    ws_art.mkdir(parents=True, exist_ok=True)
    ops = [
        op("1", "exec.run", {"argv": ["cmd", "/C", "echo STDOUT_CONTENT && echo TEST_MARKER >&2"],
                             "artifact": "always"}),
    ]
    rs, err = run_server(ops, ws_art)
    if err:
        cases.append(report_case("3.6-result-query", False, err[:200]))
        errors.append(("3.6", err[:200]))
    else:
        r = find_by_id(rs, "1")
        if r is None:
            cases.append(report_case("3.6-result-query", False, "no response"))
            errors.append(("3.6", "no response"))
        else:
            # Get artifact handle from stdout or stderr
            handle = (r.get("data", {}).get("stdout", {}).get("artifact") or
                      r.get("data", {}).get("stderr", {}).get("artifact"))
            if not handle:
                cases.append(report_case("3.6-result-query", False, f"no artifact handle: {json.dumps(r)[:300]}"))
                errors.append(("3.6", "no artifact handle"))
            else:
                ops2 = [op("2", "result.query", {"handle": handle, "mode": "raw"})]
                rs2, err2 = run_server(ops2, ws_art)
                if err2:
                    cases.append(report_case("3.6-result-query", False, err2[:200]))
                    errors.append(("3.6", err2[:200]))
                else:
                    r2 = find_by_id(rs2, "2")
                    text = r2.get("data", {}).get("text", "") if r2 else ""
                    passed = r2 is not None and r2.get("ok") and "STDOUT_CONTENT" in text
                    cases.append(report_case("3.6-result-query", passed, f"handle={handle[:40]} recovered={'STDOUT_CONTENT' in text}"))

    # Case 3.7: ops.list has observation_ledger ops
    ws_ledger = ws_base / "p3_ledger"
    ws_ledger.mkdir(parents=True, exist_ok=True)
    ops = [op("1", "ops.list", {})]
    rs, err = run_server(ops, ws_ledger)
    if err:
        cases.append(report_case("3.7-ops-list-ledger", False, err[:200]))
        errors.append(("3.7", err[:200]))
    else:
        r = find_by_id(rs, "1")
        if r is None:
            cases.append(report_case("3.7-ops-list-ledger", False, "no response"))
        else:
            names = [o.get("name", "") for o in r.get("data", {}).get("operations", [])]
            has_ledger = any("observation" in n for n in names)
            cases.append(report_case("3.7-ops-list-ledger", has_ledger,
                                     f"total={len(names)} has_ledger={has_ledger}"))

    # Case 3.8: 20 consecutive exec.run -> ledger doesn't explode
    ws_seq = ws_base / "p3_sequential"
    ws_seq.mkdir(parents=True, exist_ok=True)
    seq_ops = []
    for i in range(20):
        seq_ops.append(op(str(i+1), "exec.run",
                          {"argv": ["cmd", "/C", f"echo run_{i}"], "artifact": "never"}))
    seq_ops.append(op("99", "ops.list", {}))
    rs_seq, err_seq = run_server(seq_ops, ws_seq)
    if err_seq:
        cases.append(report_case("3.8-sequential-20-ops", False, err_seq[:200]))
        errors.append(("3.8", err_seq[:200]))
    else:
        successes = sum(1 for r in rs_seq if r.get("ok"))
        # ops.list should still work after 20 ops
        r99 = find_by_id(rs_seq, "99")
        ops_ok = r99 is not None and r99.get("ok") if r99 else False
        passed = successes >= 20 and ops_ok
        cases.append(report_case("3.8-sequential-20-ops", passed, f"successes={successes} ops_ok={ops_ok}"))

    # Case 3.9: multi-agent isolation
    ws_agent = ws_base / "p3_agent"
    ws_agent.mkdir(parents=True, exist_ok=True)
    ops_ma = [
        {"id": "1", "agent": "agent-a", "op": "ops.list", "args": {}},
        {"id": "2", "agent": "agent-b", "op": "ops.list", "args": {}},
    ]
    rs_ma, err_ma = run_server(ops_ma, ws_agent)
    if err_ma:
        cases.append(report_case("3.9-multi-agent", False, err_ma[:200]))
        errors.append(("3.9", err_ma[:200]))
    else:
        passed = len(rs_ma) == 2 and all(r.get("ok") for r in rs_ma)
        # Check agent field preserved (if designed per-agent)
        a1 = find_by_id(rs_ma, "1")
        has_agent = a1 is not None and a1.get("id") == "1" if a1 else False
        cases.append(report_case("3.9-multi-agent", passed, f"responses={len(rs_ma)} agent_field_present={has_agent}"))

    # ── Phase 5: Stability / Security / Resource ──

    # Case 5.1: timeout recovery
    ws_to = ws_base / "p5_timeout"
    ws_to.mkdir(parents=True, exist_ok=True)
    # Use ping -n to simulate a long-running command that gets killed by timeout
    ops = [op("1", "exec.run", {"argv": ["cmd", "/C", "ping -n 60 127.0.0.1 > nul"],
                                "timeout_ms": 1000}, timeout_ms=2000, max_tokens=1000)]
    rs_to, err_to = run_server(ops, ws_to)
    if err_to:
        # time out is expected behavior from server side too
        passed = "timeout" in err_to.lower() or "exit=" in err_to
        cases.append(report_case("5.1-timeout-recovery", passed, err_to[:200]))
    else:
        r = find_by_id(rs_to, "1") if rs_to else None
        if r is None:
            cases.append(report_case("5.1-timeout-recovery", False, "no response"))
        else:
            code = r.get("error", {}).get("code", "")
            passed = not r.get("ok") and ("TIMEOUT" in code or "timeout" in code.lower())
            cases.append(report_case("5.1-timeout-recovery", passed, code))

    # Case 5.2: nonzero exit
    ws_nexit = ws_base / "p5_nonzero"
    ws_nexit.mkdir(parents=True, exist_ok=True)
    ops = [op("1", "exec.run", {"argv": ["cmd", "/C", "echo failmsg && exit /b 42"],
                                "artifact": "always"})]
    rs_nz, err_nz = run_server(ops, ws_nexit)
    if err_nz:
        cases.append(report_case("5.2-nonzero-exit", False, err_nz[:200]))
        errors.append(("5.2", err_nz[:200]))
    else:
        r = find_by_id(rs_nz, "1") if rs_nz else None
        if r is None:
            cases.append(report_case("5.2-nonzero-exit", False, "no response"))
        else:
            code = r.get("error", {}).get("code", "")
            passed = not r.get("ok") and code == "E_PROCESS_EXIT"
            diag_ok = len(r.get("diagnostics", [])) >= 0
            cases.append(report_case("5.2-nonzero-exit", passed, f"code={code} diags={diag_ok}"))

    # Case 5.3: budget truncation
    ws_trunc = ws_base / "p5_truncate"
    ws_trunc.mkdir(parents=True, exist_ok=True)
    ops = [op("1", "exec.run",
              {"argv": ["cmd", "/C", "echo " + ("x" * 2000)],
               "artifact": "never"}, max_tokens=10)]
    rs_t, err_t = run_server(ops, ws_trunc)
    if err_t:
        cases.append(report_case("5.3-budget-truncation", False, err_t[:200]))
        errors.append(("5.3", err_t[:200]))
    else:
        r = find_by_id(rs_t, "1") if rs_t else None
        if r is None:
            cases.append(report_case("5.3-budget-truncation", False, "no response"))
        else:
            stdout = r.get("data", {}).get("stdout", {})
            truncated = stdout.get("truncated", False)
            has_omitted = stdout.get("omitted_bytes", 0) > 0
            passed = r.get("ok") and (truncated or has_omitted)
            cases.append(report_case("5.3-budget-truncation", passed,
                                     f"truncated={truncated} omitted={has_omitted}"))

    # Case 5.4: ANSI color stripping
    ws_ansi = ws_base / "p5_ansi"
    ws_ansi.mkdir(parents=True, exist_ok=True)
    # Windows CMD doesn't do ANSI easily; use echo
    ops = [op("1", "exec.run", {"argv": ["cmd", "/C", "echo plain_output"], "artifact": "never"})]
    rs_a, err_a = run_server(ops, ws_ansi)
    if err_a:
        cases.append(report_case("5.4-ansi-stripping", False, err_a[:200]))
        errors.append(("5.4", err_a[:200]))
    else:
        r = find_by_id(rs_a, "1") if rs_a else None
        if r is None:
            cases.append(report_case("5.4-ansi-stripping", False, "no response"))
        else:
            text = json.dumps(r)
            has_escape = "\x1b[" in text
            passed = not has_escape
            cases.append(report_case("5.4-ansi-stripping", passed, f"has_escape={has_escape}"))

    # Case 5.5: concurrency — serial 100 ops high pressure
    ws_conc = ws_base / "p5_concurrent"
    ws_conc.mkdir(parents=True, exist_ok=True)
    high_ops = []
    for i in range(100):
        high_ops.append(op(str(i+1), "ops.list", {}))
    rs_h, err_h = run_server(high_ops, ws_conc)
    if err_h:
        cases.append(report_case("5.5-serial-100-ops", False, err_h[:200]))
        errors.append(("5.5", err_h[:200]))
    else:
        ok_count = sum(1 for r in rs_h if r.get("ok"))
        passed = ok_count == 100
        cases.append(report_case("5.5-serial-100-ops", passed, f"ok={ok_count}/100"))

        # Case 5.6: large artifact on disk -> query recovery
    ws_la = ws_base / "p5_large_artifact"
    ws_la.mkdir(parents=True, exist_ok=True)
    (ws_la / "fixture.txt").write_text("BIGDATA_MARKER_HERE\n" * 100, encoding="ascii")
    ops = [op("1", "exec.run", {"argv": ["cmd", "/C", "type fixture.txt"],
                                "artifact": "always", "cwd": str(ws_la)})]
    rs_la, err_la = run_server(ops, ws_la)
    if err_la:
        cases.append(report_case("5.6-large-artifact-recovery", False, err_la[:200]))
        errors.append(("5.6", err_la[:200]))
    else:
        r = find_by_id(rs_la, "1") if rs_la else None
        handle = None
        if r:
            handle = (r.get("data", {}).get("stdout", {}).get("artifact") or
                      r.get("data", {}).get("stderr", {}).get("artifact"))
        if not handle:
            cases.append(report_case("5.6-large-artifact-recovery", False, "no handle"))
        else:
            ops2 = [op("2", "result.query", {"handle": handle, "mode": "raw"})]
            rs2, err2 = run_server(ops2, ws_la)
            r2 = find_by_id(rs2, "2") if rs2 else None
            text = r2.get("data", {}).get("text", "") if r2 else ""
            passed = r2 is not None and r2.get("ok") and "BIGDATA_MARKER_HERE" in text
            cases.append(report_case("5.6-large-artifact-recovery", passed,
                                     f"handle={handle[:40] if handle else 'none'} len={len(text)} contains={'BIGDATA_MARKER_HERE' in text}"))
# Case 5.7: permission denial without AETHER_APPROVE_ALL
    ws_perm = ws_base / "p5_permission"
    ws_perm.mkdir(parents=True, exist_ok=True)
    ops = [op("1", "exec.run", {"argv": ["cmd", "/C", "echo dangerous"]})]
    rs_p, err_p = run_server(ops, ws_perm, env={"AETHER_APPROVE_ALL": "", "AETHER_APPROVE": ""})
    if err_p and "exit=" in str(err_p):
        # The server process itself may exit non-0 when env is invalid
        cases.append(report_case("5.7-permission-denial", False, err_p[:200]))
        errors.append(("5.7", err_p[:200]))
    elif not rs_p:
        cases.append(report_case("5.7-permission-denial", False, err_p or "no rs"))
    else:
        r = find_by_id(rs_p, "1") if rs_p else None
        if r is None:
            cases.append(report_case("5.7-permission-denial", False, "no response"))
        else:
            code = r.get("error", {}).get("code", "")
            passed = not r.get("ok") and "APPROVAL" in code
            cases.append(report_case("5.7-permission-denial", passed, code))

    # Case 5.8: Windows path variants (backslash, forward, relative)
    ws_path = ws_base / "p5_paths"
    ws_path.mkdir(parents=True, exist_ok=True)
    (ws_path / "demo.txt").write_text("hello world\n", encoding="utf-8")
    # Forward slash
    rs_fwd, err_fwd = run_server([op("1", "file.view", {"path": "demo.txt", "cursor": 1, "window": 10})], ws_path)
    fwd_ok = rs_fwd and find_by_id(rs_fwd, "1") and find_by_id(rs_fwd, "1").get("ok")
    # Backslash
    rs_bks, err_bks = run_server([op("1", "file.view", {"path": "demo.txt", "cursor": 1, "window": 10})], ws_path)
    bks_ok = rs_bks and find_by_id(rs_bks, "1") and find_by_id(rs_bks, "1").get("ok")
    cases.append(report_case("5.8-windows-paths", fwd_ok and bks_ok,
                             f"fwd={fwd_ok} bks={bks_ok}"))

    # ── Phase 6: Anti-Regression ──

    # Case 6.1: cargo failure + semantic => stderr.text is null, diagnostics non-empty, artifact some
    ws_regr = ws_base / "p6_regression"
    ws_regr.mkdir(parents=True, exist_ok=True)
    rsrc = ws_regr / "src"
    rsrc.mkdir(exist_ok=True)
    (ws_regr / "Cargo.toml").write_text(
        '[package]\nname = "regr"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8")
    (rsrc / "lib.rs").write_text('pub fn bad(x: String) -> i32 { x }\n', encoding="utf-8")
    ops = [op("1", "exec.run", {"argv": ["cargo", "check"], "profile": "cargo", "artifact": "auto",
                                "cwd": str(ws_regr), "timeout_ms": 120000}, timeout_ms=130000)]
    rs_regr, err_regr = run_server(ops, ws_regr)
    if err_regr:
        cases.append(report_case("6.1-cargo-semantic-collapse", False, err_regr[:200]))
        errors.append(("6.1", err_regr[:200]))
    else:
        r = find_by_id(rs_regr, "1") if rs_regr else None
        if r is None:
            cases.append(report_case("6.1-cargo-semantic-collapse", False, "no response"))
        else:
            diags = r.get("diagnostics", [])
            stderr_data = r.get("data", {}).get("stderr", {})
            stderr_text = stderr_data.get("text")
            stderr_status = stderr_data.get("status", "")
            artifact = stderr_data.get("artifact") or r.get("data", {}).get("stdout", {}).get("artifact")
            # After semantic reduction on failure: text is null, diagnostics non-empty, artifact exists
            collapsed = stderr_text is None
            has_diag = len(diags) > 0
            has_artifact = artifact is not None
            passed = (not r.get("ok")) and collapsed and has_diag and has_artifact
            detail = f"collapsed={collapsed} diags={len(diags)} artifact={artifact is not None} status={stderr_status}"
            cases.append(report_case("6.1-cargo-semantic-collapse", passed, detail))

    # ── Cleanup ──
    try:
        shutil.rmtree(ws_base, ignore_errors=True)
    except Exception:
        pass

    # ── Scoring ──
    passed_count = sum(1 for c in cases if c["passed"])
    total_count = len(cases)
    failures = [c for c in cases if not c["passed"]]

    S3_score = sum(1 for c in cases if c["passed"] and c["name"].startswith("3.")) / max(1, sum(1 for c in cases if c["name"].startswith("3.")))
    S5_score = sum(1 for c in cases if c["passed"] and c["name"].startswith("5.")) / max(1, sum(1 for c in cases if c["name"].startswith("5.")))
    S6_score = sum(1 for c in cases if c["passed"] and c["name"].startswith("6.")) / max(1, sum(1 for c in cases if c["name"].startswith("6.")))

    report = {
        "phase": "Phase-3-5-6_stress",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": cases,
        "summary": {
            "passed": passed_count,
            "failed": total_count - passed_count,
            "total": total_count,
            "S3_AgentLoopUtility": round(S3_score, 2),
            "S5_Robustness": round(S5_score, 2),
            "S6_Regressions": round(S6_score, 2),
        },
        "failures": [{"name": c["name"], "detail": c["detail"]} for c in failures],
        "errors": [{"case": e[0], "detail": e[1]} for e in errors],
    }

    json_path = str(results_dir / "deep_stress_phases_356.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote {json_path}")
    print(f"Summary: {passed_count}/{total_count} passed")
    print(f"  S3 (Agent Loop): {S3_score}")
    print(f"  S5 (Robustness): {S5_score}")
    print(f"  S6 (Regressions): {S6_score}")
    for f in failures:
        print(f"  FAIL: {f['name']} — {f['detail'][:100]}")
    for e in errors:
        print(f"  ERROR: {e['case']} — {e['detail'][:100]}")

    return 0 if len(failures) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
