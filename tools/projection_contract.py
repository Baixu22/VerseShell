#!/usr/bin/env python3
"""projection_contract: the reference client must not silently drop a tool's payload.

`bench/aci/runners/live_agent_loop.py::format_aci_result` decides what an agent
actually sees: it renders the product's `verseshell.observation/v1` envelope down
to a compact JSON or read-text/v1 projection. Every tool the runner exposes also has a description
that promises what it returns. Those two must agree.

This tool checks that contract against the **real** server (`ae --serve --agent`),
not a fixture of the projection:

  * `search_content` / `repo.search` promises "matching files and lines" — the
    projection must carry the matches.
  * `list_files` / `repo.summary` promises "branch, dirty files, top-level
    directory listing" — the projection must carry the listing, and must NOT leak
    the host `workspace` path.
  * `replace_in_file` / `file.replace_exact` must return a usable digest.
  * the FAILURE path must keep `E_AMBIGUOUS`'s structured `data.matches[]`
    (line/offset/snippet): that is exactly the payload claim C4's one-step
    recovery rests on, and it used to be dropped because the failure branch
    returned before the field was copied.
  * a zero-hit search must stay honest (`match_count: 0`), not look like a
    generic success blob.

Historical context: before this check existed, `repo.search` projected to
`{"ok": true}` on success, so an agent that searched learned nothing and fell
back to a raw `grep` through `exec.run`. That inflated condition D's cost and
made the `search_content` tool useless while the benchmark reported it as a
success. `repo.summary` lost `top_level`, and `E_AMBIGUOUS` lost its candidates.

Exit code is non-zero if any check fails, so this can gate a change.

Usage:
    python tools/projection_contract.py --out eval/projection_contract.json
"""
from __future__ import annotations

import argparse
import hashlib
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
    execute_aci_op,
    format_aci_result,
    parse_aci_result,
)

EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "tools/projection_contract.py",
]


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def build_workspace() -> Path:
    ws = Path(tempfile.mkdtemp(prefix="projection-contract-"))
    (ws / "src").mkdir()
    (ws / "src" / "lib.rs").write_text(
        "pub fn mul(a: i32, b: i32) -> i32 {\n    return a * b;\n}\n", encoding="utf-8")
    (ws / "src" / "other.rs").write_text("// TODO(fix-me) here\n", encoding="utf-8")
    # The same line three times makes `old` ambiguous -> E_AMBIGUOUS.
    (ws / "src" / "dup.rs").write_text("let a = 1;\nlet a = 1;\nlet a = 1;\n", encoding="utf-8")
    # A file longer than the reference client's old ten-line cutoff. The original
    # check used only the 3-line lib.rs above, which fell inside that cutoff and so
    # stayed green while a default `file.view` of any real source file returned
    # nothing but a hash (see claim C30).
    (ws / "src" / "long.rs").write_text(
        "".join(f"pub const K{i}: i32 = {i};\n" for i in range(1, 61)), encoding="utf-8")
    return ws


def run_check(name: str, op: str, args: dict, workspace: Path,
              predicate) -> dict:
    """Run one real op and apply `predicate(projected_dict) -> (ok, detail)`."""
    response = execute_aci_op(op, args, str(workspace), ACI_CAPABILITIES)
    text = format_aci_result(response)
    try:
        projected = parse_aci_result(text)
    except ValueError:
        projected = None
    ok, detail = (False, "projection could not be decoded") if projected is None else predicate(projected)
    return {
        "check": name,
        "op": op,
        "args": args,
        "server_ok": response.get("ok"),
        "server_data_keys": sorted((response.get("data") or {}).keys()),
        "projection": projected,
        "pass": bool(ok),
        "detail": detail,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "projection_contract.json")
    args = ap.parse_args(argv)

    ws = build_workspace()
    checks: list[dict] = []
    try:
        def search_ok(p: dict):
            if p.get("match_count") != 1:
                return False, f"expected match_count 1, got {p.get('match_count')!r}"
            m = (p.get("matches") or [{}])[0]
            if m.get("path") != "src/other.rs" or m.get("line") != 1:
                return False, f"match did not carry path/line: {m!r}"
            if "TODO" not in (m.get("text") or ""):
                return False, f"match did not carry text: {m!r}"
            return True, "matches carry path/line/text"

        checks.append(run_check("search_content returns matches", "repo.search",
                                {"query": "TODO"}, ws, search_ok))

        def search_empty_ok(p: dict):
            if p.get("match_count") != 0 or p.get("matches") != []:
                return False, f"a zero-hit search must report 0/[]: {p!r}"
            return True, "zero-hit search reports match_count 0"

        checks.append(run_check("search_content reports zero hits honestly", "repo.search",
                                {"query": "zzz-no-such-symbol-zzz"}, ws, search_empty_ok))

        def summary_ok(p: dict):
            repo = p.get("repo") or {}
            if "top_level" not in repo:
                return False, f"list_files promised a top-level listing: {repo!r}"
            if "workspace" in repo:
                return False, "the host workspace path must not be projected"
            names = [e.get("name") for e in repo.get("top_level") or []]
            if "src" not in names:
                return False, f"top_level missing src: {names!r}"
            return True, f"top_level carried, no host path leak: {names}"

        checks.append(run_check("list_files returns the top-level listing", "repo.summary",
                                {}, ws, summary_ok))

        def ambiguous_ok(p: dict):
            err = p.get("error") or {}
            if err.get("code") != "E_AMBIGUOUS":
                return False, f"expected E_AMBIGUOUS, got {err.get('code')!r}"
            matches = p.get("matches")
            if not matches:
                return False, ("E_AMBIGUOUS must project its candidate sites "
                               "(C4 one-step recovery depends on it)")
            first = matches[0]
            missing = [k for k in ("line", "offset", "snippet") if k not in first]
            if missing:
                return False, f"candidate site missing locator fields {missing}: {first!r}"
            return True, f"{len(matches)} candidate site(s) with line/offset/snippet"

        checks.append(run_check("E_AMBIGUOUS keeps its candidate sites", "file.replace_exact",
                                {"path": "src/dup.rs", "old": "let a = 1;", "new": "let a = 2;"},
                                ws, ambiguous_ok))

        def edit_ok(p: dict):
            if not p.get("content_hash"):
                return False, "a successful edit must return a digest to chain the next edit"
            return True, "digest present"

        checks.append(run_check("replace_in_file returns a digest", "file.replace_exact",
                                {"path": "src/lib.rs", "old": "return a * b;",
                                 "new": "return a + b;"}, ws, edit_ok))

        def read_ok(p: dict):
            if "text" not in p and "lines" not in p:
                return False, f"read_file must return the content: {p!r}"
            return True, "content present"

        checks.append(run_check("read_file returns content", "file.view",
                                {"path": "src/lib.rs"}, ws, read_ok))

        # The default window is 80 lines, so a plain `file.view` of a normal source
        # file must carry its content. Gating this on a 3-line fixture is what let a
        # ten-line cutoff ship unnoticed (claim C30).
        def default_window_read_ok(p: dict):
            expected = [f"pub const K{i}: i32 = {i};" for i in range(1, 61)]
            if p.get("text") != "\n".join(expected):
                return False, "the complete default window must survive projection and decoding"
            return True, "all 60 lines preserved exactly"

        checks.append(run_check("default window view returns content", "file.view",
                                {"path": "src/long.rs"}, ws, default_window_read_ok))

        # And the same for a multi-file batch read.
        def read_many_ok(p: dict):
            files = p.get("files")
            if not isinstance(files, list) or not files:
                return False, f"read_many must project per-file entries: {p!r}"
            carried = [f for f in files
                       if isinstance(f, dict) and ("text" in f or "lines" in f)]
            if not carried:
                return False, ("read_many returned no file content for a 60-line file: "
                               f"{[sorted(f) for f in files if isinstance(f, dict)]}")
            return True, f"{len(carried)}/{len(files)} entries carry content"

        checks.append(run_check("read_many returns content", "file.read_many",
                                {"paths": ["src/long.rs"]}, ws, read_many_ok))

        def paged_batch_ok(p: dict):
            entries = p.get("files") or []
            if len(entries) != 3:
                return False, "batch lost an entry"
            first, missing, deferred = entries
            expected = "\n".join(f"pub const K{i}: i32 = {i};" for i in range(1, 4))
            ok = (first.get("path") == "src/long.rs" and first.get("text") == expected
                  and first.get("total_lines") == 60 and first.get("truncated") is True
                  and first.get("next_start_line") == 4 and bool(first.get("content_hash"))
                  and missing.get("path") == "src/missing.rs" and bool(missing.get("error"))
                  and deferred.get("path") == "src/lib.rs" and deferred.get("deferred") is True
                  and deferred.get("next_start_line") == 1)
            return ok, "content, paths, error, deferred entry and continuation preserved"

        checks.append(run_check("batch paging and missing-file metadata survive", "file.read_many",
                                {"paths": ["src/long.rs", "src/missing.rs", "src/lib.rs"],
                                 "max_total_lines": 3}, ws, paged_batch_ok))

        viewed = execute_aci_op("file.view", {"path": "src/lib.rs"}, str(ws), ACI_CAPABILITIES)
        shown_hash = parse_aci_result(format_aci_result(viewed))["content_hash"]
        edit_args = {"path": "src/lib.rs", "old": "return a + b;", "new": "return a - b;",
                     "expected_hash": shown_hash}
        checks.append(run_check("displayed read digest authorizes a fresh edit", "file.replace_exact",
                                edit_args, ws, lambda p: (p.get("ok") is True, "displayed digest accepted")))
        def stale_ok(p: dict):
            rejected = (p.get("error") or {}).get("code") == "E_STALE_HASH"
            unchanged = "return a - b;" in (ws / "src/lib.rs").read_text()
            return rejected and unchanged, "stale digest rejected without changing content"

        checks.append(run_check("displayed read digest rejects stale reuse", "file.replace_exact",
                                {**edit_args, "old": "return a - b;", "new": "return a * b;"},
                                ws, stale_ok))
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    payload = {
        "schema": "verseshell.projection_contract/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/projection_contract.py",
        "protocol": "every check runs a real op through `ae --serve --agent` and inspects the "
                    "projection format_aci_result hands to the model",
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
        "summary": {"checks": total, "passed": passed, "failed": total - passed,
                    "pass": passed == total},
        "checks": checks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"wrote {args.out}")
    for c in checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}: {c['detail']}")
        if not c["pass"]:
            print(f"         projection was: {json.dumps(c['projection'], ensure_ascii=False)}")
    print(f"\nprojection contract: {passed}/{total} checks pass")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
