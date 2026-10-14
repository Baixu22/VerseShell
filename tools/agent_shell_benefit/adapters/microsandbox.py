"""microsandbox 0.7.8 adapter used by all three experiment arms."""

from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..common import OBSERVATION_SCHEMA, elapsed_ms_since, estimate_tokens, validate_observation


@dataclass
class AdapterRun:
    observation: dict[str, Any]
    transport: dict[str, Any]


class MicrosandboxError(RuntimeError):
    pass


class MicrosandboxAdapter:
    """Thin wrapper around `msb`; one adapter instance owns one sandbox."""

    def __init__(
        self,
        msb_path: str,
        *,
        name: str,
        ae_linux_path: str | None = None,
        workspace: str = "/workspace",
        display_cap: int = 8000,
        memory: str = "512M",
        state_dir: str = "/var/ae-state",
    ) -> None:
        self.msb_path = msb_path
        self.name = name
        self.ae_linux_path = ae_linux_path
        self.workspace = workspace
        self.display_cap = display_cap
        self.memory = memory
        # Runtime bookkeeping (artifacts, audit log, tx journals) must not live
        # inside the agent-visible workspace: a plain `ls` there was enough to
        # send the model exploring our implementation instead of the task.
        self.state_dir = state_dir
        self.created = False

    def _run_cli(
        self,
        args: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout_seconds: float = 180,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [self.msb_path, *args],
            input=input_bytes,
            capture_output=True,
            timeout=timeout_seconds,
        )

    def _require_ok(self, proc: subprocess.CompletedProcess[bytes], action: str) -> None:
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace")
            raise MicrosandboxError(f"{action} failed rc={proc.returncode}: {stderr[-2000:]}")

    def create(self, *, install_ae: bool = False) -> None:
        self._run_cli(["rm", "--force", "--quiet", self.name], timeout_seconds=30)
        create_argv = ["create", "--name", self.name, "--cpus", "1"]
        if self.memory:
            create_argv += ["--memory", self.memory]
        create_argv.append("python")
        proc = self._run_cli(create_argv, timeout_seconds=300)
        self._require_ok(proc, "microsandbox create")
        self.created = True
        proc = self._run_cli(
            ["exec", "-q", "--no-tty", "--no-stdin", self.name, "--", "mkdir", "-p", self.workspace],
            timeout_seconds=60,
        )
        self._require_ok(proc, "workspace create")
        if install_ae:
            if not self.ae_linux_path or not Path(self.ae_linux_path).is_file():
                raise MicrosandboxError("Linux ae binary is required for provider D")
            proc = self._run_cli(
                ["copy", "--quiet", str(Path(self.ae_linux_path).resolve()), f"{self.name}:/usr/local/bin/ae"],
                timeout_seconds=120,
            )
            self._require_ok(proc, "copy ae into sandbox")
            proc = self._run_cli(
                ["exec", "-q", "--no-tty", "--no-stdin", self.name, "--", "chmod", "+x", "/usr/local/bin/ae"],
                timeout_seconds=60,
            )
            self._require_ok(proc, "chmod ae")

    def close(self) -> None:
        if self.created:
            self._run_cli(["rm", "--force", "--quiet", self.name], timeout_seconds=30)
            self.created = False

    def copy_host_file(self, local_path: str | Path, sandbox_path: str) -> None:
        proc = self._run_cli(
            ["copy", "--quiet", str(Path(local_path).resolve()), f"{self.name}:{sandbox_path}"],
            timeout_seconds=120,
        )
        self._require_ok(proc, f"copy {local_path}")

    def run_raw(self, command: str, timeout_seconds: float = 10) -> AdapterRun:
        started = time.perf_counter()
        # The sandbox must enforce the caller's timeout; the host wrapper only
        # needs enough headroom to observe the killed process.
        sandbox_timeout = max(1, int(math.ceil(timeout_seconds)))
        host_timeout = sandbox_timeout + 20
        argv = [
            "exec", "-q", "--no-tty", "--no-stdin", "-w", self.workspace, "--timeout",
            f"{sandbox_timeout}s", self.name, "--", "sh", "-c", command,
        ]
        timed_out = False
        rc: int | None = None
        stdout = b""
        stderr = b""
        host_error: str | None = None
        try:
            proc = self._run_cli(argv, timeout_seconds=host_timeout)
            rc = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            rc = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            host_error = f"host subprocess timeout after {host_timeout}s"
        elapsed = elapsed_ms_since(started)
        stdout_text = stdout.decode("utf-8", "replace")
        stderr_text = stderr.decode("utf-8", "replace")
        if "timed out" in stderr_text.lower() or "context deadline exceeded" in stderr_text.lower():
            timed_out = True
        observation = {
            "schema": "agent-shell.raw-observation/v1",
            "exit_code": rc,
            "stdout": stdout_text[: self.display_cap],
            "stderr": stderr_text[: self.display_cap],
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_truncated": len(stdout_text) > self.display_cap,
            "stderr_truncated": len(stderr_text) > self.display_cap,
            "elapsed_ms": elapsed,
            "timed_out": timed_out,
            "error": host_error,
        }
        return AdapterRun(
            observation=observation,
            transport={
                "kind": "microsandbox.raw",
                "argv": argv,
                "rc": rc,
                "host_elapsed_ms": elapsed,
                "host_error": host_error,
                "stderr": stderr_text[-4000:],
            },
        )

    def run_verseshell(self, command: str, timeout_seconds: float = 10) -> AdapterRun:
        """Run `ae exec.run` inside the same persistent microVM workspace."""
        timeout_ms = max(100, int(round(timeout_seconds * 1000)))
        request = {
            "id": f"benefit-{os.urandom(6).hex()}",
            "agent": "agent-shell-benefit",
            "op": "exec.run",
            "args": {
                "argv": ["sh", "-c", command],
                "cwd": ".",
                "profile": "auto",
                "artifact": "auto",
                "timeout_ms": timeout_ms,
            },
            "timeout_ms": timeout_ms,
            "budget": {"max_tokens": 4000},
        }
        payload = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        outer_timeout = max(3, int(math.ceil(timeout_seconds + 20)))
        argv = [
            "exec", "-q", "--no-tty", "-w", self.workspace, "-e", "AETHER_APPROVE_ALL=1",
            *(["-e", f"AETHER_STATE_DIR={self.state_dir}"] if self.state_dir else []),
            "-e", f"AETHER_WORKSPACE={self.workspace}", self.name, "--", "/usr/local/bin/ae",
            "--serve", "--cap", "shell.exec", "--agent", "--workspace", self.workspace,
        ]
        started = time.perf_counter()
        timed_out = False
        rc: int | None = None
        stdout = b""
        stderr = b""
        host_error: str | None = None
        try:
            proc = self._run_cli(argv, input_bytes=payload, timeout_seconds=outer_timeout)
            rc = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            rc = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            host_error = f"host ae wrapper timeout after {outer_timeout}s"
        elapsed = elapsed_ms_since(started)
        stdout_text = stdout.decode("utf-8", "replace")
        stderr_text = stderr.decode("utf-8", "replace")
        parsed: dict[str, Any] | None = None
        for line in stdout_text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("schema") == OBSERVATION_SCHEMA:
                parsed = candidate
                break
        transport = {
            "kind": "microsandbox.verseshell",
            "argv": argv,
            "rc": rc,
            "host_elapsed_ms": elapsed,
            "host_error": host_error,
            "stderr": stderr_text[-4000:],
            "request": request,
            "stdout": stdout_text[-8000:],
        }
        if parsed is None:
            if timed_out or host_error:
                parsed = {
                    "schema": OBSERVATION_SCHEMA,
                    "id": request["id"],
                    "op": "exec.run",
                    "ok": False,
                    "data": {"exit_code": 124 if timed_out else None, "timed_out": True},
                    "error": {
                        "code": "E_TIMEOUT" if timed_out else "E_ADAPTER",
                        "message": host_error or f"ae wrapper rc={rc}",
                        "recoverable": True,
                    },
                    "diagnostics": [],
                    "meta": {"elapsed_ms": elapsed, "profile": "adapter", "token_estimate": 0},
                    "suggested_next": [],
                }
            else:
                raise MicrosandboxError(
                    "ae did not return verseshell.observation/v1: " + (stdout_text + "\n" + stderr_text)[-3000:]
                )
        errors = validate_observation(parsed)
        if errors:
            raise MicrosandboxError("invalid ae observation: " + "; ".join(errors))
        return AdapterRun(observation=parsed, transport=transport)

    def read_text(self, path: str, timeout_seconds: float = 10) -> dict[str, Any]:
        quoted = shlex.quote(path)
        result = self.run_raw(f"if [ -f {quoted} ]; then cat -- {quoted}; else exit 44; fi", timeout_seconds)
        return {
            "path": path,
            "exists": result.observation.get("exit_code") == 0,
            "text": result.observation.get("stdout") or "",
            "stderr": result.observation.get("stderr") or "",
            "exit_code": result.observation.get("exit_code"),
        }

    def check_ae_contract(self) -> dict[str, Any]:
        version = self._run_cli(
            ["exec", "-q", "--no-tty", "--no-stdin", self.name, "--", "/usr/local/bin/ae", "--version"],
            timeout_seconds=60,
        )
        self._require_ok(version, "ae --version")
        run = self.run_verseshell("printf 'contract\\n'", timeout_seconds=5)
        return {
            "version": version.stdout.decode("utf-8", "replace").strip(),
            "schema": run.observation.get("schema"),
            "observation_keys": sorted(run.observation.keys()),
            "token_estimate": run.observation.get("meta", {}).get("token_estimate"),
            "validation_errors": validate_observation(run.observation),
        }

    def output_token_proxy(self, observation: dict[str, Any]) -> int:
        return estimate_tokens(json.dumps(observation, ensure_ascii=False, separators=(",", ":")))