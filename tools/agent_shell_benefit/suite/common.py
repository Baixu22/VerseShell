"""Shared helpers + tier registry for the 80-task agent-shell suite."""

from __future__ import annotations

from typing import Any

TIERS = {
    "L1": {"name": "simple", "range": (101, 120)},
    "L2": {"name": "medium", "range": (201, 220)},
    "L3": {"name": "hard", "range": (301, 320)},
    "L4": {"name": "devil", "range": (401, 420)},
}

FIX_HASH = {"source": "fixtures/hash_edit.py", "target": "/workspace/hash_edit.py"}
FIX_AMBIG = {"source": "fixtures/ambiguous_edit.py", "target": "/workspace/ambiguous_edit.py"}
FIX_LOCK = {"source": "suite/fixtures/lockfile.py", "target": "/workspace/lockfile.py"}
FIX_JOURNAL = {"source": "suite/fixtures/journal.py", "target": "/workspace/journal.py"}
FIX_QUEUE = {"source": "suite/fixtures/queue_worker.py", "target": "/workspace/queue_worker.py"}
FIX_RACE = {"source": "suite/fixtures/race_counter.py", "target": "/workspace/race_counter.py"}


def task(task_id: str, tier: str, title: str, prompt: str, checks: list[dict[str, Any]],
         setup: list[str] | None = None, fixtures: list[dict[str, str]] | None = None,
         files: list[str] | None = None, host_test: bool = False, processes: bool = False,
         require_finish: bool = True, probes: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "id": task_id,
        "tier": tier,
        "title": title,
        "prompt": prompt,
        "setup": setup or [],
        "fixtures": fixtures or [],
        "evidence": {"files": files or [], "host_test": host_test, "processes": processes, "probes": probes or []},
        "oracle": {"checks": checks, "require_finish_success": require_finish},
    }