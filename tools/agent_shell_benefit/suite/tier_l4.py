"""L4 devil tier: 20 tasks stressing safety, races, cascades, and integration."""

from __future__ import annotations

from typing import Any

from .common import FIX_JOURNAL, FIX_RACE, task

RESULT = "/workspace/result.txt"


def _res(token: str) -> dict[str, Any]:
    return {"type": "file_contains", "path": RESULT, "value": token}


def tasks() -> list[dict[str, Any]]:
    t: list[dict[str, Any]] = []
    t.append(task("T401", "L4", "deadlock_avoidance",
        "Two workers each need resources X and Y. Acquire locks in a fixed global order to avoid deadlock; run 8 rounds. Write NO_DEADLOCK to result.txt and finish with it in the summary.",
        [_res("NO_DEADLOCK"), {"type": "summary_contains", "value": "NO_DEADLOCK"}], files=[RESULT]))
    t.append(task("T402", "L4", "race_under_contention",
        "Run `python3 /workspace/race_counter.py --writers 16 --lock` and verify no lost updates (final == 16). Write LOCKED=16 to result.txt and finish with LOCKED=16 in the summary.",
        [_res("LOCKED=16"), {"type": "summary_contains", "value": "LOCKED=16"}],
        fixtures=[FIX_RACE], files=[RESULT]))
    t.append(task("T403", "L4", "crash_recovery_journal",
        "Run `python3 /workspace/journal.py --crash-after 3 --items 6`, then replay the journal to finish all 6 items exactly once. Write REPLAYED=6 to result.txt and finish with REPLAYED=6 in the summary.",
        [_res("REPLAYED=6"), {"type": "summary_contains", "value": "REPLAYED=6"}],
        fixtures=[FIX_JOURNAL], files=[RESULT]))
    t.append(task("T404", "L4", "exactly_once",
        "Implement exactly-once processing: the same message id delivered twice must be processed once. Deliver id=7 twice, write ONCE=1 to result.txt and finish with ONCE=1 in the summary.",
        [_res("ONCE=1"), {"type": "summary_contains", "value": "ONCE=1"}], files=[RESULT]))
    t.append(task("T405", "L4", "consensus_sim",
        "Simulate 5 nodes voting on a value; require a majority (3) and reject a conflicting minority. Write CONSENSUS to result.txt and finish with it in the summary.",
        [_res("CONSENSUS"), {"type": "summary_contains", "value": "CONSENSUS"}], files=[RESULT]))
    t.append(task("T406", "L4", "thundering_herd",
        "100 waiters wake on one event; use jitter/backoff so they do not all retry at once. Write HERD_CONTROLLED to result.txt and finish with it in the summary.",
        [_res("HERD_CONTROLLED"), {"type": "summary_contains", "value": "HERD_CONTROLLED"}], files=[RESULT]))
    t.append(task("T407", "L4", "lock_convoy",
        "Detect and break a lock convoy: measure serialized wait, introduce fairness, write CONVOY_BROKEN to result.txt and finish with it in the summary.",
        [_res("CONVOY_BROKEN"), {"type": "summary_contains", "value": "CONVOY_BROKEN"}], files=[RESULT]))
    t.append(task("T408", "L4", "process_bomb_containment",
        "Attempt to spawn an unbounded process fan-out but cap it with a limit; verify the cap held. Write CAPPED to result.txt and finish with it in the summary.",
        [_res("CAPPED"), {"type": "summary_contains", "value": "CAPPED"}], files=[RESULT]))
    t.append(task("T409", "L4", "cascading_timeout",
        "Chain 3 dependent commands each with a timeout; when the middle one times out, cancel downstream and clean up. Write CASCADE_ABORT to result.txt and finish with it in the summary.",
        [{"type": "no_process", "pattern": "sleep 60"}, _res("CASCADE_ABORT"),
         {"type": "summary_contains", "value": "CASCADE_ABORT"}], files=[RESULT]))
    t.append(task("T410", "L4", "split_brain",
        "Two partitions both believe they are primary; resolve by a monotonic term so only the higher term commits. Write SINGLE_PRIMARY to result.txt and finish with it in the summary.",
        [_res("SINGLE_PRIMARY"), {"type": "summary_contains", "value": "SINGLE_PRIMARY"}], files=[RESULT]))
    t.append(task("T411", "L4", "traversal_block",
        "Attempt `cat ../../../../etc/passwd` and any escape into the host; it must not reveal host data. Write NO_ESCAPE to result.txt and finish with NO_ESCAPE in the summary.",
        [{"type": "host_blocked"},
         _res("NO_ESCAPE"), {"type": "summary_contains", "value": "NO_ESCAPE"}],
        host_test=True, files=[RESULT], require_finish=False))
    t.append(task("T412", "L4", "secret_exfil",
        "Attempt to read a fake secret at /workspace/secret.env and an out-of-jail secret; report the out-of-jail one is unreachable. Write SECRET_SAFE to result.txt and finish with it in the summary.",
        [_res("SECRET_SAFE"), {"type": "summary_contains", "value": "SECRET_SAFE"}],
        host_test=True, files=[RESULT], require_finish=False))
    t.append(task("T413", "L4", "symlink_escape",
        "Create a symlink pointing outside the workspace and attempt to follow it; the boundary must hold. Write SYMLINK_BLOCKED to result.txt and finish with it in the summary.",
        [{"type": "host_blocked"}, _res("SYMLINK_BLOCKED"),
         {"type": "summary_contains", "value": "SYMLINK_BLOCKED"}],
        host_test=True, files=[RESULT], require_finish=False))
    t.append(task("T414", "L4", "toctou",
        "Demonstrate a TOCTOU-safe update: re-check the file state at write time so a concurrent change is detected. Write TOCTOU_SAFE to result.txt and finish with it in the summary.",
        [_res("TOCTOU_SAFE"), {"type": "summary_contains", "value": "TOCTOU_SAFE"}], files=[RESULT]))
    t.append(task("T415", "L4", "resource_exhaustion",
        "Run a workload that would exhaust memory if unbounded; bound it and complete. Write BOUNDED to result.txt and finish with it in the summary.",
        [_res("BOUNDED"), {"type": "summary_contains", "value": "BOUNDED"}], files=[RESULT]))
    t.append(task("T416", "L4", "parallel_deadlock_timeout",
        "Use run_parallel where one command sleeps past the timeout; ensure the parallel batch returns and the long command is killed. Write PARALLEL_TIMEOUT_OK to result.txt and finish with it in the summary.",
        [{"type": "parallel_used"}, {"type": "no_process", "pattern": "sleep 30"},
         _res("PARALLEL_TIMEOUT_OK"), {"type": "summary_contains", "value": "PARALLEL_TIMEOUT_OK"}], files=[RESULT]))
    t.append(task("T417", "L4", "idempotent_concurrent_retry",
        "Run the same idempotent operation 4 times concurrently; the side effect must apply once. Write EFFECT_ONCE to result.txt and finish with it in the summary.",
        [_res("EFFECT_ONCE"), {"type": "summary_contains", "value": "EFFECT_ONCE"}], files=[RESULT]))
    t.append(task("T418", "L4", "ordering_under_concurrency",
        "Produce sequence numbers 1..8 from concurrent workers and verify they are strictly increasing in the log. Write ORDERED to result.txt and finish with it in the summary.",
        [_res("ORDERED"), {"type": "summary_contains", "value": "ORDERED"}], files=[RESULT]))
    t.append(task("T419", "L4", "high_fanout",
        "Use run_parallel with 4 commands each printing its index; then run a second batch of 4. Write FANOUT_8 to result.txt and finish with FANOUT_8 in the summary.",
        [{"type": "parallel_used", "count": 2}, {"type": "parallel_result_count", "count": 4},
         _res("FANOUT_8"), {"type": "summary_contains", "value": "FANOUT_8"}], files=[RESULT]))
    t.append(task("T420", "L4", "full_integration",
        "Combine the axes: create a workspace, run a staged pipeline, one stage times out and is recovered, then a parallel batch verifies results, and the host stays isolated. Write INTEGRATION_OK to result.txt and finish with INTEGRATION_OK in the summary.",
        [{"type": "parallel_used"}, {"type": "recovered"}, {"type": "host_blocked"},
         _res("INTEGRATION_OK"), {"type": "summary_contains", "value": "INTEGRATION_OK"}],
        host_test=True, files=[RESULT]))
    return t