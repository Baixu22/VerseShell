#!/usr/bin/env python3
"""harness_encoding_contract: the raw-shell observation path must not lose bytes.

TF-0100. `execute_shell_cmd` runs the model's command through
`subprocess.run(..., text=True)`. With no explicit `encoding`, CPython decodes with
the *locale* codec (cp936 on a Chinese Windows host). A byte that is invalid in that
codec makes the reader thread raise, `stdout` comes back as `None`, and the old
`out += ...` then raised `TypeError` — which aborted the whole agent loop, threw
away the trajectory, and scored the run as an ordinary task failure. Measured on the
frozen round-12 live artifact: 3/75 `raw_shell` and 2/75 `raw_shell_coached` rows,
0/75 `verseshell_aci` rows.

This is the raw-shell analogue of `tools/projection_contract.py`, which gates the ACI
side. Until TF-0100 the raw-shell path had no such check, so the defect survived
three rounds of headline rewrites.

Checks:
  1. utf8_observation_roundtrip  — a real `type` of a UTF-8 file with U+2014 reaches
                                   the model intact, with the exit marker appended.
  2. empty_and_failing_commands  — no command shape makes the function raise or
                                   return a non-str.
  3. mechanism_control           — the fixture bytes are genuinely undecodable in
                                   cp936, i.e. the codec CPython would have used on a
                                   Chinese Windows host. Host-independent.
  4. locale_control              — whether *this* host's locale codec would have
                                   failed too (informational; not part of pass/fail).

Usage:
    python tools/harness_encoding_contract.py --out eval/harness_encoding_contract.json
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import locale
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))

from live_agent_loop import execute_shell_cmd  # noqa: E402

EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "tools/harness_encoding_contract.py",
]
# One U+2014 EM DASH: the exact character the ts fixture carried. It is 3 UTF-8 bytes
# and none of them is valid as a cp936 lead byte here.
FIXTURE_TEXT = "# em dash: \u2014\nvalue = 1\n"
FIXTURE_BYTES = FIXTURE_TEXT.encode("utf-8")


def evidence_fingerprint(globs: list[str]) -> str:
    digest = hashlib.sha256()
    for pat in globs:
        for path in sorted(ROOT.glob(pat)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_checks() -> dict:
    checks: list[dict] = []
    detail: dict = {
        "fixture_bytes_hex": FIXTURE_BYTES.hex(),
        "locale_preferred_encoding": locale.getpreferredencoding(False),
        "locale_getencoding": locale.getencoding() if hasattr(locale, "getencoding") else None,
    }

    with tempfile.TemporaryDirectory(prefix="ae_enc_") as td:
        ws = Path(td)
        target = ws / "sample.py"
        target.write_bytes(FIXTURE_BYTES)

        # 1. real command, real output, non-ASCII byte
        out = execute_shell_cmd(f'type "{target}"', str(ws))
        checks.append({
            "name": "utf8_observation_roundtrip",
            "pass": (isinstance(out, str) and "\u2014" in out and "[EXIT: 0]" in out),
            "detail": {
                "is_str": isinstance(out, str),
                "contains_em_dash": "\u2014" in out,
                "contains_exit_marker": "[EXIT: 0]" in out,
                "head": out[:120] if isinstance(out, str) else repr(out),
            },
        })

        # 2. degenerate command shapes must not raise and must stay str
        shapes = {
            "no_output": "ver > nul",
            "unknown_command": "definitely_not_a_command_9f3a",
            "empty_command": "",
        }
        shape_detail = {}
        ok = True
        for name, cmd in shapes.items():
            try:
                got = execute_shell_cmd(cmd, str(ws))
                good = isinstance(got, str) and "[EXIT:" in got
                shape_detail[name] = {"returned_str": isinstance(got, str),
                                      "has_exit_marker": isinstance(got, str) and "[EXIT:" in got}
                ok = ok and good
            except Exception as exc:  # noqa: BLE001 - the check exists to catch exactly this
                shape_detail[name] = {"raised": f"{type(exc).__name__}: {exc}"}
                ok = False
        checks.append({"name": "empty_and_failing_commands", "pass": ok, "detail": shape_detail})

    # 3. mechanism control: the bytes really are invalid in the codec CPython would
    #    have picked on a Chinese Windows host.
    cp936_raises = None
    cp936_error = None
    try:
        FIXTURE_BYTES.decode("cp936")
        cp936_raises = False
    except UnicodeDecodeError as exc:
        cp936_raises = True
        cp936_error = str(exc)
    checks.append({
        "name": "mechanism_control",
        "pass": cp936_raises is True,
        "detail": {"cp936_rejects_fixture": cp936_raises, "error": cp936_error},
    })

    # 4. informational: would this host's locale codec have failed too?
    loc = locale.getpreferredencoding(False)
    try:
        FIXTURE_BYTES.decode(loc)
        locale_would_fail = False
        locale_error = None
    except UnicodeDecodeError as exc:
        locale_would_fail = True
        locale_error = str(exc)
    detail["locale_control"] = {
        "codec": loc,
        "would_have_failed": locale_would_fail,
        "error": locale_error,
        "note": "informational only: on a UTF-8 host the pre-fix code would not have "
                "crashed, but the defect is still present in the code",
    }

    # 5. the pre-fix call shape, exercised on the fixture, for the record. The reader
    #    thread's traceback is captured rather than dumped: it IS the reproduction.
    pre_fix_stdout_none = None
    pre_fix_stderr = ""
    with tempfile.TemporaryDirectory(prefix="ae_enc_old_") as td:
        ws = Path(td)
        target = ws / "sample.py"
        target.write_bytes(FIXTURE_BYTES)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                r = subprocess.run(f'type "{target}"', shell=True, cwd=str(ws),
                                   capture_output=True, text=True, timeout=30)
            pre_fix_stdout_none = r.stdout is None
        except Exception as exc:  # noqa: BLE001
            pre_fix_stdout_none = f"raised {type(exc).__name__}"
        pre_fix_stderr = buf.getvalue().strip()
    detail["prefix_call_shape"] = {
        "stdout_is_none": pre_fix_stdout_none,
        "reader_thread_error": pre_fix_stderr.splitlines()[-1] if pre_fix_stderr else None,
        "note": "`None` here is exactly what made `out += ...` raise TypeError and "
                "throw the trajectory away; the reader-thread UnicodeDecodeError above "
                "is the mechanism",
    }

    value = 1.0 if all(c["pass"] for c in checks) else 0.0
    return {
        "schema": "verseshell.harness_encoding_contract/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/harness_encoding_contract.py",
        "claim": "the raw-shell observation path decodes non-ASCII output losslessly and "
                 "never lets a decode fault abort the agent loop",
        "value": value,
        "pass": value == 1.0,
        "checks": checks,
        "detail": detail,
        "evidence": {"globs": EVIDENCE_GLOBS, "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS)},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "eval" / "harness_encoding_contract.json")
    args = ap.parse_args()
    payload = run_checks()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    for c in payload["checks"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}")
    print(f"locale codec = {payload['detail']['locale_preferred_encoding']} "
          f"(would have failed: {payload['detail']['locale_control']['would_have_failed']})")
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
