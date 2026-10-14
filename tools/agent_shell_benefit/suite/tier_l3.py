"""L3 hard tier: 20 multi-step tasks with concurrency, transactions, recovery."""

from __future__ import annotations

from typing import Any

from .common import FIX_JOURNAL, FIX_LOCK, FIX_QUEUE, FIX_RACE, task

RESULT = "/workspace/result.txt"


def _res(token: str) -> dict[str, Any]:
    return {"type": "file_contains", "path": RESULT, "value": token}


def tasks() -> list[dict[str, Any]]:
    t: list[dict[str, Any]] = []
    t.append(task("T301", "L3", "staged_pipeline",
        "Build a 3-stage pipeline in /workspace: stage1 writes /workspace/s1 containing STAGE1, stage2 depends on s1 and writes /workspace/s2 containing STAGE2, stage3 depends on s2 and writes /workspace/s3 containing STAGE3. Run stages in dependency order; finish with STAGE3 in the summary.",
        [{"type": "file_contains", "path": "/workspace/s1", "value": "STAGE1"},
         {"type": "file_contains", "path": "/workspace/s2", "value": "STAGE2"},
         {"type": "file_contains", "path": "/workspace/s3", "value": "STAGE3"},
         {"type": "summary_contains", "value": "STAGE3"}],
        files=["/workspace/s1", "/workspace/s2", "/workspace/s3"]))
    t.append(task("T302", "L3", "race_detect",
        "Run `python3 /workspace/race_counter.py` with 8 concurrent writers to counter.txt and report the observed final value and whether any lost update occurred. Write the token RACE_REPORTED to result.txt and finish with RACE_REPORTED in the summary.",
        [{"type": "stdout_seen", "regex": "(?i)(lost|race|final)"},
         _res("RACE_REPORTED"), {"type": "summary_contains", "value": "RACE_REPORTED"}],
        setup=["rm -f counter.txt"], fixtures=[FIX_RACE], files=[RESULT]))
    t.append(task("T303", "L3", "parallel_write_contention",
        "Use run_parallel to have 4 writers each append their id to shared.txt, then count the lines. Finish with the count 4 in the summary.",
        [{"type": "parallel_used"}, {"type": "file_count_lines", "path": "/workspace/shared.txt", "count": 4},
         {"type": "summary_contains", "value": "4"}], setup=["rm -f shared.txt"], files=["/workspace/shared.txt"]))
    t.append(task("T304", "L3", "lock_contention",
        "Run `python3 /workspace/lockfile.py --path app.lock --wait 0.5 --run 'echo CRITICAL'` twice concurrently (the 0.5s critical section guarantees overlap); exactly one should enter. Write LOCK_SERIALIZED to result.txt and finish with it in the summary.",
        [{"type": "stdout_seen", "regex": "CRITICAL"}, _res("LOCK_SERIALIZED"),
         {"type": "summary_contains", "value": "LOCK_SERIALIZED"}],
        setup=["rm -f app.lock"], fixtures=[FIX_LOCK], files=[RESULT]))
    t.append(task("T305", "L3", "resource_limit",
        "Run a command that spawns a bounded number of background jobs (max 4), wait for all, then confirm none remain. Write RESOURCE_OK to result.txt and finish with it in the summary.",
        [{"type": "no_process", "pattern": "sleep 60"}, _res("RESOURCE_OK"),
         {"type": "summary_contains", "value": "RESOURCE_OK"}], files=[RESULT]))
    t.append(task("T306", "L3", "circuit_breaker",
        "Implement a circuit breaker: after 3 consecutive failures it opens and stops calling. Simulate 5 calls, write CIRCUIT_OPEN to result.txt and report the open state in the summary.",
        [_res("CIRCUIT_OPEN"), {"type": "summary_contains", "value": "CIRCUIT_OPEN"}], files=[RESULT]))
    t.append(task("T307", "L3", "saga_compensation",
        "Execute 3 steps writing /workspace/state.txt; make step 3 fail, then compensate steps 2 and 1 in reverse order so /workspace/state.txt is exactly CLEAN. Write COMPENSATED to result.txt and finish with it in the summary.",
        [{"type": "file_equals", "path": "/workspace/state.txt", "value": "CLEAN"},
         _res("COMPENSATED"), {"type": "summary_contains", "value": "COMPENSATED"}],
        files=["/workspace/state.txt", RESULT]))
    t.append(task("T308", "L3", "distributed_lock",
        "Simulate a distributed lock using /workspace/dlock as the lock file with a pid owner: acquire, run a critical section, release. Verify /workspace/dlock is free. Write DLOCK_OK to result.txt and finish with it in the summary.",
        [{"type": "file_absent", "path": "/workspace/dlock"}, _res("DLOCK_OK"),
         {"type": "summary_contains", "value": "DLOCK_OK"}], setup=["rm -f dlock"], files=[RESULT]))
    t.append(task("T309", "L3", "queue_drain",
        "Run `python3 /workspace/queue_worker.py --queue jobs.txt --workers 4` after seeding 8 jobs; drain all jobs, write DRAINED=8 to result.txt and finish with DRAINED=8 in the summary.",
        [{"type": "stdout_seen", "regex": "DRAINED"}, _res("DRAINED=8"),
         {"type": "summary_contains", "value": "DRAINED"}],
        setup=["rm -f jobs.txt"], fixtures=[FIX_QUEUE], files=[RESULT]))
    t.append(task("T310", "L3", "backpressure",
        "Feed 10 items to a consumer that processes at most 3 at a time; write BACKPRESSURE_OK to result.txt after all 10 are processed with max in-flight <= 3, and finish with it in the summary.",
        [_res("BACKPRESSURE_OK"), {"type": "summary_contains", "value": "BACKPRESSURE_OK"}], files=[RESULT]))
    t.append(task("T311", "L3", "partial_failure",
        "Run 4 subtasks where 2 succeed and 2 fail; record per-subtask status to result.txt and continue past failures, writing PARTIAL_OK. Finish with PARTIAL_OK in the summary.",
        [_res("PARTIAL_OK"), {"type": "summary_contains", "value": "PARTIAL_OK"}], files=[RESULT]))
    t.append(task("T312", "L3", "checkpoint_resume",
        "Write a 5-item job, checkpoint after item 3, resume and complete items 4-5, then write RESUMED=5 to result.txt. Finish with RESUMED=5 in the summary.",
        [_res("RESUMED=5"), {"type": "summary_contains", "value": "RESUMED=5"}], files=[RESULT]))
    t.append(task("T313", "L3", "batch_error_isolation",
        "Process 6 items where item 3 is malformed; isolate the failure and write GOOD=5 and BAD=1 to result.txt. Finish with GOOD=5 and BAD=1 in the summary.",
        [_res(["GOOD=5", "BAD=1"]), {"type": "summary_contains", "value": ["GOOD=5", "BAD=1"]}], files=[RESULT]))
    t.append(task("T314", "L3", "schema_migration",
        "Migrate data.json from schema v1 to v2 by adding a field; on failure roll back. Write MIGRATED to result.txt and finish with it in the summary.",
        [{"type": "file_contains", "path": "/workspace/data.json", "value": "v2"},
         _res("MIGRATED"), {"type": "summary_contains", "value": "MIGRATED"}],
        setup=["rm -f data.json"], files=["/workspace/data.json", RESULT]))
    t.append(task("T315", "L3", "concurrent_counter",
        "Use a lock to run 10 concurrent increments on counter.txt; verify the final value is exactly 10. Write the value 10 to result.txt and finish with 10 in the summary.",
        [{"type": "file_equals", "path": "/workspace/counter.txt", "value": "10"},
         _res("10"), {"type": "summary_contains", "value": "10"}],
        setup=["rm -f counter.txt"], files=["/workspace/counter.txt", RESULT]))
    t.append(task("T316", "L3", "timeout_cascade",
        "Run a parent command that starts a child with a shorter timeout; ensure both are cleaned up when the child times out. Write CASCADE_CLEAN to result.txt and finish with it in the summary.",
        [{"type": "no_process", "pattern": "sleep 30"}, _res("CASCADE_CLEAN"),
         {"type": "summary_contains", "value": "CASCADE_CLEAN"}], files=[RESULT]))
    t.append(task("T317", "L3", "retry_storm",
        "Implement retries with a cap of 3 attempts and jitter so a failing call is not retried unboundedly. Write ATTEMPTS=3 to result.txt and finish with it in the summary.",
        [_res("ATTEMPTS=3"), {"type": "summary_contains", "value": "ATTEMPTS=3"}], files=[RESULT]))
    t.append(task("T318", "L3", "dependency_graph",
        "Given edges A->B, A->C, B->D, C->D, compute a valid execution order, write it to order.txt (space separated) and write ORDER_OK to result.txt. Finish with ORDER_OK in the summary.",
        [{"type": "file_contains", "path": "/workspace/order.txt", "value": "A"},
         _res("ORDER_OK"), {"type": "summary_contains", "value": "ORDER_OK"}],
        files=["/workspace/order.txt", RESULT]))
    t.append(task("T319", "L3", "two_phase_commit",
        "Implement prepare/commit: in prepare write /workspace/tpc_a and /workspace/tpc_b each containing prepared; commit only if both prepared, else abort. Write COMMITTED to result.txt and finish with it in the summary.",
        [{"type": "file_contains", "path": "/workspace/tpc_a", "value": "prepared"},
         {"type": "file_contains", "path": "/workspace/tpc_b", "value": "prepared"},
         _res("COMMITTED"), {"type": "summary_contains", "value": "COMMITTED"}],
        files=["/workspace/tpc_a", "/workspace/tpc_b", RESULT]))
    t.append(task("T320", "L3", "fault_injection",
        "Run `python3 /workspace/journal.py --inject-fault-after 2 --items 5`; recover from the injected fault and complete all items. Write RECOVERED_ALL to result.txt and finish with it in the summary.",
        [_res("RECOVERED_ALL"), {"type": "summary_contains", "value": "RECOVERED_ALL"}],
        fixtures=[FIX_JOURNAL], files=[RESULT]))
    return t