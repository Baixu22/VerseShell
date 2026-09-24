#!/usr/bin/env python3
"""Recover the file a stored live run left behind, from its trajectory alone.

Success predicates are re-scored after the fact — "would the current predicate
accept what this run actually produced?" — so the analysis tools need the final
content of the file each run wrote. Both conditions write it, just differently:

  * condition D uses typed ops (`file.write` / `file.replace_exact`), which replay
    exactly;
  * raw shell folds the write into a command, in practice a
    `python -c "open('f','w').write('...')"` one-liner, which is decoded back into
    the string literal it wrote.

Nothing here re-runs a workspace; it only reconstructs text, and it reports
`None` when it cannot, so a caller never silently scores a missing artifact.
"""
from __future__ import annotations

import ast
import re

INLINE_WRITE_RE = re.compile(
    r"open\(\s*(?:r)?(?P<q1>['\"])(?P<path>.*?)(?P=q1)\s*,\s*['\"]w['\"]\s*\)\s*\.\s*"
    r"write\(\s*(?P<q2>['\"])(?P<body>(?:\\.|(?!(?P=q2)).)*?)(?P=q2)",
    re.DOTALL,
)

# `echo <text>> file` / `echo <text> > file`: how raw shell often writes a one-line
# summary. The body is everything before the redirection operator.
ECHO_REDIRECT_RE = re.compile(
    r"\becho\s+(?P<body>[^\r\n>]*?)\s*(?:1)?>>?\s*(?P<path>[^\s>&|]+)",
)


def step_text(step: dict) -> str:
    """The command a step ran, whether it used `argv` (D) or a shell string (A)."""
    args = step.get("args") or {}
    argv = args.get("argv")
    if isinstance(argv, list):
        return " ".join(str(a) for a in argv)
    return str(args.get("command", ""))


def typed_write(pristine: str, trajectory: list[dict], path: str) -> tuple[str | None, str]:
    """Replay the typed writes a D run left in the workspace."""
    body = pristine
    touched = False
    for step in trajectory:
        op = step.get("op")
        args = step.get("args") or {}
        if op == "file.write" and args.get("path") == path:
            body = str(args.get("content", ""))
            touched = True
        elif op == "file.replace_exact" and args.get("path") == path:
            old = str(args.get("old", ""))
            new = str(args.get("new", ""))
            if old and old in body:
                body = body.replace(old, new, 1)
                touched = True
    return (body if touched else None), ("typed file ops" if touched else "no write to the file")


def inline_write(pristine: str, trajectory: list[dict], path: str) -> tuple[str | None, str]:
    """Recover a raw-shell write from an inline command (python one-liner or echo)."""
    body = pristine
    touched = False
    for step in trajectory:
        if step.get("op") != "run_command":
            continue
        command = step_text(step)
        for match in INLINE_WRITE_RE.finditer(command):
            target = match.group("path").replace("\\", "/")
            if target != path.replace("\\", "/"):
                continue
            quote = match.group("q2")
            try:
                body = ast.literal_eval(f"{quote}{match.group('body')}{quote}")
                touched = True
            except (ValueError, SyntaxError) as error:
                return None, f"could not decode the inline write: {error}"
        for match in ECHO_REDIRECT_RE.finditer(command):
            target = match.group("path").strip('"').replace("\\", "/")
            if target != path.replace("\\", "/"):
                continue
            body = match.group("body")
            touched = True
    return (body if touched else None), ("inline shell write" if touched else "no write to the file")


def reconstruct(condition: str, pristine: str, trajectory: list[dict],
                path: str) -> tuple[str | None, str]:
    """Pick the reconstruction that matches the condition."""
    if condition == "verseshell_aci":
        return typed_write(pristine, trajectory, path)
    return inline_write(pristine, trajectory, path)
