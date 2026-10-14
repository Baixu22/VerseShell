"""Provider implementations for raw, matched-raw, and VerseShell arms."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ..adapters.microsandbox import MicrosandboxAdapter
from ..common import estimate_tokens
from .prompts import MATCHED_SYSTEM_PROMPT, RAW_SYSTEM_PROMPT, VERSESHELL_SYSTEM_PROMPT


@dataclass
class ProviderResult:
    observation: dict[str, Any]
    transport: dict[str, Any]

    def model_text(self) -> str:
        return json.dumps(self.observation, ensure_ascii=False, separators=(",", ":"))

    def observation_tokens(self) -> int:
        return estimate_tokens(self.model_text())


class BaseProvider:
    arm: str
    system_prompt: str

    def __init__(self, adapter: MicrosandboxAdapter) -> None:
        self.adapter = adapter

    def run_shell(self, command: str, timeout_seconds: float = 10) -> ProviderResult:
        raise NotImplementedError

    def run_parallel(self, commands: list[str], timeout_seconds: float = 10) -> ProviderResult:
        started = time.perf_counter()
        workers = max(1, min(4, len(commands)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.run_shell, command, timeout_seconds) for command in commands]
            items = [future.result() for future in futures]
        wall_ms = int(round((time.perf_counter() - started) * 1000))
        observation = {
            "schema": "agent-shell.parallel-observation/v1",
            "wall_ms": wall_ms,
            "results": [item.observation for item in items],
        }
        return ProviderResult(
            observation=observation,
            transport={"kind": "parallel", "wall_ms": wall_ms, "items": [item.transport for item in items]},
        )


class RawProvider(BaseProvider):
    arm = "A"
    system_prompt = RAW_SYSTEM_PROMPT

    def run_shell(self, command: str, timeout_seconds: float = 10) -> ProviderResult:
        run = self.adapter.run_raw(command, timeout_seconds)
        return ProviderResult(run.observation, run.transport)


class MatchedRawProvider(RawProvider):
    arm = "A_prime"
    system_prompt = MATCHED_SYSTEM_PROMPT


class VerseshellProvider(BaseProvider):
    arm = "D"
    system_prompt = VERSESHELL_SYSTEM_PROMPT

    def run_shell(self, command: str, timeout_seconds: float = 10) -> ProviderResult:
        run = self.adapter.run_verseshell(command, timeout_seconds)
        return ProviderResult(run.observation, run.transport)


def make_provider(arm: str, adapter: MicrosandboxAdapter) -> BaseProvider:
    if arm == "A":
        return RawProvider(adapter)
    if arm in ("A_prime", "A′"):
        return MatchedRawProvider(adapter)
    if arm == "D":
        return VerseshellProvider(adapter)
    raise ValueError(f"unknown arm: {arm}")