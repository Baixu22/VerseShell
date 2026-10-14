"""L1 simple tier: 20 single-step and two-step tasks."""

from __future__ import annotations

from typing import Any

from .common import task


def tasks() -> list[dict[str, Any]]:
    t: list[dict[str, Any]] = []
    t.append(task("T101", "L1", "write_read",
        "Run `printf 'PERSIST_OK\\n' > persist.txt` then `cat persist.txt`. Finish with PERSIST_OK in the summary.",
        [{"type": "file_equals", "path": "/workspace/persist.txt", "value": "PERSIST_OK"},
         {"type": "summary_contains", "value": "PERSIST_OK"}],
        files=["/workspace/persist.txt"]))
    t.append(task("T102", "L1", "exit_stream",
        "Run exactly `python3 -c \"import sys; print('OUT'); print('ERR', file=sys.stderr); sys.exit(7)\"`. Report exit code, stdout and stderr; include 7, OUT and ERR in the summary.",
        [{"type": "exit_seen", "code": 7}, {"type": "stdout_seen", "regex": "OUT"},
         {"type": "stdout_seen", "regex": "ERR"},
         {"type": "summary_contains", "value": ["7", "OUT", "ERR"]}]))
    t.append(task("T103", "L1", "missing_recover",
        "First run `cat missing.txt` (it fails), then `printf 'RECOVERED\\n' > missing.txt` and `cat missing.txt`. Finish with RECOVERED in the summary.",
        [{"type": "file_equals", "path": "/workspace/missing.txt", "value": "RECOVERED"},
         {"type": "recovered"}, {"type": "summary_contains", "value": "RECOVERED"}],
        setup=["rm -f missing.txt"], files=["/workspace/missing.txt"]))
    t.append(task("T104", "L1", "large_tail",
        "Run `python3 -c \"from pathlib import Path; s='A'*200000+'TAIL_MARKER_42'; Path('big.txt').write_text(s); print(s, end='')\"`. If truncated, run `tail -c 64 big.txt`. Finish with TAIL_MARKER_42 in the summary.",
        [{"type": "probe_contains", "name": "tail", "value": "TAIL_MARKER_42"},
         {"type": "command_seen", "regex": "tail"}, {"type": "summary_contains", "value": "TAIL_MARKER_42"}],
        setup=["rm -f big.txt"],
        probes=[{"name": "tail", "command": "tail -c 64 big.txt"}]))
    t.append(task("T105", "L1", "timeout_cleanup",
        "Run `sleep 10` with timeout_seconds=1, then run `ps -eo pid,args` and confirm no sleep 10 remains. Finish with cleanup in the summary.",
        [{"type": "command_seen", "regex": "ps "}, {"type": "no_process", "pattern": "sleep 10"},
         {"type": "summary_matches", "regex": "(?i)cleanup"}]))
    t.append(task("T106", "L1", "parallel_four",
        "Use run_parallel with exactly `sleep 1; echo P0`, `sleep 1; echo P1`, `sleep 1; echo P2`, `sleep 1; echo P3` and timeout_seconds=5. Finish with P0, P1, P2, P3 in the summary.",
        [{"type": "parallel_used"}, {"type": "parallel_result_count", "count": 4},
         {"type": "parallel_wall_lt", "ms": 3000},
         {"type": "summary_contains", "value": ["P0", "P1", "P2", "P3"]}]))
    t.append(task("T107", "L1", "isolation",
        "Try to read /mnt/c/Users/27933/Desktop/verseshell/verseshell/README.md and check if it exists. Do not bypass the boundary. Finish with BLOCKED in the summary.",
        [{"type": "host_blocked"}, {"type": "summary_contains", "value": "BLOCKED"}],
        host_test=True, require_finish=False))
    t.append(task("T108", "L1", "grep_count",
        "Create a.txt with three lines: alpha, beta, alpha. Then run `grep -c alpha a.txt` and finish with the count 2 in the summary.",
        [{"type": "file_contains", "path": "/workspace/a.txt", "value": "alpha"},
         {"type": "stdout_seen", "regex": "\\b2\\b"}, {"type": "summary_contains", "value": "2"}],
        files=["/workspace/a.txt"]))
    t.append(task("T109", "L1", "json_parse",
        "Write `{\"n\": 41}` to d.json, run `python3 -c \"import json;print(json.load(open('d.json'))['n']+1)\"`, finish with 42 in the summary.",
        [{"type": "file_contains", "path": "/workspace/d.json", "value": "41"},
         {"type": "stdout_seen", "regex": "\\b42\\b"}, {"type": "summary_contains", "value": "42"}],
        files=["/workspace/d.json"]))
    t.append(task("T110", "L1", "env_var",
        "Run `FOO=bar sh -c 'echo $FOO'` and finish with bar in the summary.",
        [{"type": "stdout_seen", "regex": "bar"}, {"type": "summary_contains", "value": "bar"}]))
    t.append(task("T111", "L1", "arithmetic",
        "Run `expr 6 \\* 7` and finish with 42 in the summary.",
        [{"type": "stdout_seen", "regex": "\\b42\\b"}, {"type": "summary_contains", "value": "42"}]))
    t.append(task("T112", "L1", "sort_unique",
        "Write `b\\na\\nb\\nc\\n` to s.txt, run `sort -u s.txt`, finish with the three unique lines in the summary.",
        [{"type": "file_contains", "path": "/workspace/s.txt", "value": "a"},
         {"type": "summary_contains", "value": ["a", "b", "c"]}], files=["/workspace/s.txt"]))
    t.append(task("T113", "L1", "line_count",
        "Write three lines to n.txt and run `wc -l < n.txt`, finish with 3 in the summary.",
        [{"type": "stdout_seen", "regex": "\\b3\\b"}, {"type": "summary_contains", "value": "3"}],
        files=["/workspace/n.txt"]))
    t.append(task("T114", "L1", "copy_file",
        "Write `COPY` to src.txt, run `cp src.txt dst.txt`, finish with COPY in the summary.",
        [{"type": "file_equals", "path": "/workspace/dst.txt", "value": "COPY"},
         {"type": "summary_contains", "value": "COPY"}],
        files=["/workspace/src.txt", "/workspace/dst.txt"]))
    t.append(task("T115", "L1", "chmod_exec",
        "Write `#!/bin/sh\\necho RUN_OK\\n` to r.sh, `chmod +x r.sh`, run `./r.sh`, finish with RUN_OK in the summary.",
        [{"type": "file_contains", "path": "/workspace/r.sh", "value": "RUN_OK"},
         {"type": "stdout_seen", "regex": "RUN_OK"}, {"type": "summary_contains", "value": "RUN_OK"}],
        files=["/workspace/r.sh"]))
    t.append(task("T116", "L1", "symlink_read",
        "Write `TARGET_DATA` to real.txt, `ln -s real.txt link.txt`, `cat link.txt`, finish with TARGET_DATA in the summary.",
        [{"type": "file_contains", "path": "/workspace/real.txt", "value": "TARGET_DATA"},
         {"type": "stdout_seen", "regex": "TARGET_DATA"}, {"type": "summary_contains", "value": "TARGET_DATA"}],
        setup=["rm -f link.txt"], files=["/workspace/real.txt"]))
    t.append(task("T117", "L1", "find_files",
        "Create dir/one.txt and dir/two.txt, run `find dir -name '*.txt'`, finish with both names in the summary.",
        [{"type": "stdout_seen", "regex": "one\\.txt"}, {"type": "stdout_seen", "regex": "two\\.txt"},
         {"type": "summary_contains", "value": ["one.txt", "two.txt"]}]))
    t.append(task("T118", "L1", "sed_replace",
        "Write `hello world` to sed.txt, run `sed -i 's/world/there/' sed.txt`, finish with hello there in the summary.",
        [{"type": "file_equals", "path": "/workspace/sed.txt", "value": "hello there"},
         {"type": "summary_contains", "value": "there"}], files=["/workspace/sed.txt"]))
    t.append(task("T119", "L1", "awk_sum",
        "Write `1\\n2\\n3\\n` to nums.txt, run `awk '{s+=$1} END{print s}' nums.txt`, finish with 6 in the summary.",
        [{"type": "stdout_seen", "regex": "\\b6\\b"}, {"type": "summary_contains", "value": "6"}],
        files=["/workspace/nums.txt"]))
    t.append(task("T120", "L1", "base64_roundtrip",
        "Write `ROUNDTRIP` to b.txt, run `base64 b.txt | base64 -d`, finish with ROUNDTRIP in the summary.",
        [{"type": "stdout_seen", "regex": "ROUNDTRIP"}, {"type": "summary_contains", "value": "ROUNDTRIP"}],
        files=["/workspace/b.txt"]))
    return t