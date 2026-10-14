"""L2 medium tier: 20 tasks with recovery, state, and parallel basics."""

from __future__ import annotations

from typing import Any

from .common import FIX_AMBIG, FIX_HASH, task


def tasks() -> list[dict[str, Any]]:
    t: list[dict[str, Any]] = []
    t.append(task("T201", "L2", "stale_hash",
        "Run `python3 /workspace/hash_edit.py --path stale.txt --old OLD --new NEW --expected-hash 0000000000000000000000000000000000000000000000000000000000000000`; read the actual_hash, rerun with it, then `cat stale.txt`. Finish with NEW in the summary.",
        [{"type": "file_equals", "path": "/workspace/stale.txt", "value": "NEW"},
         {"type": "recovered"}, {"type": "summary_contains", "value": "NEW"}],
        setup=["printf 'OLD\\n' > stale.txt"], fixtures=[FIX_HASH], files=["/workspace/stale.txt"]))
    t.append(task("T202", "L2", "ambiguous_edit",
        "Run `python3 /workspace/ambiguous_edit.py --path ambiguous.txt --old foo --new bar`; it reports two matches. Rerun with `--index 0`, then `cat ambiguous.txt`. Finish with the file text in the summary.",
        [{"type": "file_equals", "path": "/workspace/ambiguous.txt", "value": "bar foo"},
         {"type": "recovered"}, {"type": "summary_contains", "value": "bar foo"}],
        setup=["printf 'foo foo\\n' > ambiguous.txt"], fixtures=[FIX_AMBIG], files=["/workspace/ambiguous.txt"]))
    t.append(task("T203", "L2", "pipeline_fail_recover",
        "Run `cat nope.txt | wc -l` (fails), then create nope.txt with two lines and rerun the pipeline. Finish with the count 2 in the summary.",
        [{"type": "recovered"}, {"type": "stdout_seen", "regex": "\\b2\\b"},
         {"type": "summary_contains", "value": "2"}],
        setup=["rm -f nope.txt"], files=["/workspace/nope.txt"]))
    t.append(task("T204", "L2", "multi_file_merge",
        "Create p1.txt=`A`, p2.txt=`B`, p3.txt=`C`, then `cat p1.txt p2.txt p3.txt > merged.txt`, finish with ABC in the summary.",
        [{"type": "file_equals", "path": "/workspace/merged.txt", "value": "ABC"},
         {"type": "summary_contains", "value": "ABC"}], files=["/workspace/merged.txt"]))
    t.append(task("T205", "L2", "conditional_branch",
        "Run a shell conditional: if a value equals 5 print FIVE else print OTHER, with the value 5. Finish with FIVE in the summary.",
        [{"type": "stdout_seen", "regex": "FIVE"}, {"type": "summary_contains", "value": "FIVE"}]))
    t.append(task("T206", "L2", "config_merge",
        "Write `a=1` to c1 and `b=2` to c2, then combine them into config.txt with both keys, finish with a=1 and b=2 in the summary.",
        [{"type": "file_contains", "path": "/workspace/config.txt", "value": ["a=1", "b=2"]},
         {"type": "summary_contains", "value": ["a=1", "b=2"]}], files=["/workspace/config.txt"]))
    t.append(task("T207", "L2", "csv_transform",
        "Write `name,score\\nalice,10\\nbob,20\\n` to in.csv. Use python3 to emit a row count and the total score, finish with 2 and 30 in the summary.",
        [{"type": "file_contains", "path": "/workspace/in.csv", "value": "alice"},
         {"type": "summary_contains", "value": ["2", "30"]}], files=["/workspace/in.csv"]))
    t.append(task("T208", "L2", "log_aggregate",
        "Write a 3-line log with 2 ERROR and 1 INFO to log.txt, count ERROR lines, finish with 2 in the summary.",
        [{"type": "file_contains", "path": "/workspace/log.txt", "value": "ERROR"},
         {"type": "summary_contains", "value": "2"}], files=["/workspace/log.txt"]))
    t.append(task("T209", "L2", "process_lifecycle",
        "Run `nohup sleep 30 >/dev/null 2>&1 & echo $! > worker.pid`, verify alive with `kill -0`, kill it, then verify gone. Finish with LIFECYCLE_OK in the summary.",
        [{"type": "command_seen", "regex": "kill -0"}, {"type": "command_seen", "regex": "kill "},
         {"type": "no_process", "pattern": "sleep 30"},
         {"type": "summary_contains", "value": "LIFECYCLE_OK"}],
        setup=["rm -f worker.pid"], processes=True, files=["/workspace/worker.pid"]))
    t.append(task("T210", "L2", "retry_backoff",
        "Write a script that fails the first time and succeeds the second, then run it with a retry loop. Finish with SUCCESS in the summary.",
        [{"type": "recovered"}, {"type": "summary_contains", "value": "SUCCESS"}]))
    t.append(task("T211", "L2", "atomic_write",
        "Write `FINAL` to a temp file, then `mv` it to out.txt (atomic). Finish with FINAL in the summary.",
        [{"type": "file_equals", "path": "/workspace/out.txt", "value": "FINAL"},
         {"type": "summary_contains", "value": "FINAL"}], files=["/workspace/out.txt"]))
    t.append(task("T212", "L2", "lock_file",
        "Create lock.txt, run a shell block that only proceeds if the lock is absent, then removes it. Finish with LOCK_OK in the summary.",
        [{"type": "file_absent", "path": "/workspace/lock.txt"},
         {"type": "summary_contains", "value": "LOCK_OK"}], setup=["rm -f lock.txt"]))
    t.append(task("T213", "L2", "parallel_mixed",
        "Use run_parallel with `echo OK1`, `sh -c 'exit 3'`, `echo OK3` and timeout_seconds=5. Report which succeeded and which failed; finish with OK1 and OK3 in the summary.",
        [{"type": "parallel_used"}, {"type": "parallel_result_count", "count": 3},
         {"type": "summary_contains", "value": ["OK1", "OK3"]}]))
    t.append(task("T214", "L2", "parallel_ordering",
        "Use run_parallel with `sleep 1; echo SLOW` and `echo FAST`. Report both outputs; finish with SLOW and FAST in the summary.",
        [{"type": "parallel_used"}, {"type": "summary_contains", "value": ["SLOW", "FAST"]}]))
    t.append(task("T215", "L2", "timeout_verify",
        "Run `sleep 5` with timeout_seconds=1, then verify with ps that it is gone. Finish with TIMEOUT_OK in the summary.",
        [{"type": "command_seen", "regex": "ps "}, {"type": "no_process", "pattern": "sleep 5"},
         {"type": "summary_contains", "value": "TIMEOUT_OK"}]))
    t.append(task("T216", "L2", "nested_recover",
        "Attempt `cat a/b.txt` (fails), create dir a and a/b.txt with NESTED, then cat it. Finish with NESTED in the summary.",
        [{"type": "file_equals", "path": "/workspace/a/b.txt", "value": "NESTED"},
         {"type": "recovered"}, {"type": "summary_contains", "value": "NESTED"}],
        setup=["rm -rf a"], files=["/workspace/a/b.txt"]))
    t.append(task("T217", "L2", "idempotent",
        "Run the same append-to-file command twice against /workspace/idem.txt, then show that file has exactly one line. Finish with IDEMPOTENT in the summary.",
        [{"type": "file_count_lines", "path": "/workspace/idem.txt", "count": 1},
         {"type": "summary_contains", "value": "IDEMPOTENT"}], setup=["rm -f idem.txt"],
        files=["/workspace/idem.txt"]))
    t.append(task("T218", "L2", "rollback",
        "Write ORIGINAL to rb.txt, then run a failed transform, then restore ORIGINAL. Finish with ORIGINAL in the summary.",
        [{"type": "file_equals", "path": "/workspace/rb.txt", "value": "ORIGINAL"},
         {"type": "summary_contains", "value": "ORIGINAL"}], files=["/workspace/rb.txt"]))
    t.append(task("T219", "L2", "verify_checksum",
        "Write `DATA` to ck.txt, compute `sha256sum`, then verify it matches. Finish with VERIFIED in the summary.",
        [{"type": "stdout_seen", "regex": "[0-9a-f]{64}"},
         {"type": "summary_contains", "value": "VERIFIED"}], files=["/workspace/ck.txt"]))
    t.append(task("T220", "L2", "incremental_state",
        "Create counter.txt with 0, increment it 3 times, finish with 3 in the summary.",
        [{"type": "file_equals", "path": "/workspace/counter.txt", "value": "3"},
         {"type": "summary_contains", "value": "3"}], files=["/workspace/counter.txt"]))
    return t