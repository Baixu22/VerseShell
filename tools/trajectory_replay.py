#!/usr/bin/env python3
"""Infer candidate file text from a stored trajectory, without executing commands.

This is a legacy sensitivity aid, NOT a final-workspace reconstruction proof:
commands can fail, write other files, or mutate state outside the parsed forms.
Callers must not equate a non-None candidate with independent live re-scoring.
Use final_workspace_audit.py for hash-verified saved grading inputs.
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
    """Infer text from typed write arguments; outcomes and other edits are unknown."""
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
    return (body if touched else None), ("candidate from typed write arguments" if touched else "no supported typed write found")


def inline_write(pristine: str, trajectory: list[dict], path: str) -> tuple[str | None, str]:
    """Parse a candidate from a Python literal or echo, without proving execution."""
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
    return (body if touched else None), ("candidate from inline shell write" if touched else "no supported inline write found")


def reconstruct(condition: str, pristine: str, trajectory: list[dict],
                path: str) -> tuple[str | None, str]:
    """Pick a candidate parser for the condition, not an exact state replay."""
    if condition == "verseshell_aci":
        return typed_write(pristine, trajectory, path)
    return inline_write(pristine, trajectory, path)
