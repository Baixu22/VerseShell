"""Assemble the 80-task catalog from the four tier modules."""

from __future__ import annotations

from typing import Any

from .common import TIERS
from . import tier_l1, tier_l2, tier_l3, tier_l4


def build_catalog() -> list[dict[str, Any]]:
    tasks = tier_l1.tasks() + tier_l2.tasks() + tier_l3.tasks() + tier_l4.tasks()
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids in catalog")
    for tier in TIERS:
        count = len([task for task in tasks if task["tier"] == tier])
        if count != 20:
            raise ValueError(f"tier {tier} has {count} tasks, expected 20")
    if len(tasks) != 80:
        raise ValueError(f"catalog has {len(tasks)} tasks, expected 80")
    return tasks