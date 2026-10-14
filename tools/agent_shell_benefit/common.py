"""Shared, dependency-free helpers for the agent-shell benefit experiment."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVATION_SCHEMA = "verseshell.observation/v1"
RAW_OBSERVATION_SCHEMA = "agent-shell.raw-observation/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str | None) -> int:
    """Use the repository's historical model-visible token proxy."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def load_env_file(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def get_env_value(values: dict[str, str], key: str, default: str | None = None) -> str:
    value = values.get(key) or os.environ.get(key) or default
    if value is None or value == "":
        raise ValueError(f"missing required environment value: {key}")
    return value


def redact(text: str, secrets: list[str]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "<redacted>")
    return result


def validate_observation(value: Any) -> list[str]:
    """Validate the public verseshell.observation/v1 envelope used by provider D."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["observation is not an object"]
    if value.get("schema") != OBSERVATION_SCHEMA:
        errors.append(f"schema is not {OBSERVATION_SCHEMA}")
    for key, kind in (("id", str), ("op", str), ("ok", bool)):
        if not isinstance(value.get(key), kind):
            errors.append(f"{key} must be {kind.__name__}")
    if value.get("data") is not None and not isinstance(value.get("data"), dict):
        errors.append("data must be an object or null")
    error = value.get("error")
    if error is not None:
        if not isinstance(error, dict):
            errors.append("error must be an object or null")
        else:
            for key in ("code", "message"):
                if not isinstance(error.get(key), str):
                    errors.append(f"error.{key} must be a string")
            if not isinstance(error.get("recoverable"), bool):
                errors.append("error.recoverable must be a boolean")
    if value.get("diagnostics") is not None and not isinstance(value.get("diagnostics"), list):
        errors.append("diagnostics must be an array when present")
    meta = value.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")
    else:
        if not isinstance(meta.get("elapsed_ms"), (int, float)):
            errors.append("meta.elapsed_ms must be numeric")
        if not isinstance(meta.get("profile"), str):
            errors.append("meta.profile must be a string")
        if not isinstance(meta.get("token_estimate"), (int, float)):
            errors.append("meta.token_estimate must be numeric")
    if value.get("suggested_next") is not None and not isinstance(value.get("suggested_next"), list):
        errors.append("suggested_next must be an array when present")
    return errors


def obs_ok(observation: dict[str, Any]) -> bool:
    if observation.get("schema") == OBSERVATION_SCHEMA:
        return bool(observation.get("ok"))
    return observation.get("exit_code") == 0 and not observation.get("timed_out")


def obs_exit_code(observation: dict[str, Any]) -> int | None:
    if observation.get("schema") == OBSERVATION_SCHEMA:
        return (observation.get("data") or {}).get("exit_code")
    return observation.get("exit_code")


def obs_timed_out(observation: dict[str, Any]) -> bool:
    if observation.get("schema") == OBSERVATION_SCHEMA:
        return bool((observation.get("data") or {}).get("timed_out"))
    return bool(observation.get("timed_out"))


def obs_stdout(observation: dict[str, Any]) -> str:
    if observation.get("schema") == OBSERVATION_SCHEMA:
        stream = (observation.get("data") or {}).get("stdout") or {}
        return stream.get("text") or stream.get("summary") or ""
    return observation.get("stdout") or ""


def obs_stderr(observation: dict[str, Any]) -> str:
    if observation.get("schema") == OBSERVATION_SCHEMA:
        stream = (observation.get("data") or {}).get("stderr") or {}
        return stream.get("text") or stream.get("summary") or ""
    return observation.get("stderr") or ""


def obs_error_code(observation: dict[str, Any]) -> str | None:
    error = observation.get("error")
    return error.get("code") if isinstance(error, dict) else None


def elapsed_ms_since(started: float) -> int:
    return int(round((__import__("time").perf_counter() - started) * 1000))