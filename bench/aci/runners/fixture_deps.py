#!/usr/bin/env python3
"""Materialise a fixture's declared offline dependencies into a workspace.

A fixture that asks the agent to make a tool succeed has to ship that tool, or the
measurement silently becomes "can you install TypeScript" instead of "can you fix
the type error". `ts_fix_type_error` therefore carries a pinned npm tarball under
`deps/`, and the harness extracts it into `node_modules/<package>` (plus the
`.bin` shims a real `npm install` would create) before the agent starts.

Two properties this buys:

  * **both conditions start from the same, self-consistent workspace** — no arm is
    charged for the environment, and the success check can actually run the command
    the task prompt names;
  * **no network at run time** — the toolchain is pinned and extracted offline, so a
    live baseline is reproducible on a machine that can reach the model endpoint but
    not the npm registry.

Fail-closed: if a fixture ships `deps/` but an archive cannot be extracted, the
caller raises rather than handing the agent a workspace that cannot verify itself.
"""
from __future__ import annotations

import json
import shutil
import tarfile
import re
from pathlib import Path, PurePosixPath

# A real `npm install` also writes these; `npx <tool>` looks them up in
# `node_modules/.bin`, so a model that reaches for `npx tsc` finds it.
BIN_SHIM_POSIX = """#!/bin/sh
basedir=$(dirname "$(echo "$0" | sed -e 's,\\\\,/,g')")
exec node "$basedir/../{package}/{entry}" "$@"
"""
BIN_SHIM_CMD = """@ECHO off
node "%~dp0\\..\\{package}\\{entry}" %*
"""


def _extract(archive: Path, workspace: Path) -> str:
    """Extract `package/` from an npm tarball into `node_modules/<name>`."""
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile("package/package.json")
        if handle is None:
            raise RuntimeError(f"{archive.name}: no package/package.json")
        manifest = json.loads(handle.read().decode("utf-8"))
        name = manifest["name"]
        if not isinstance(name,str) or not re.fullmatch(r'(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+',name) or any(p in ('.','..') or p.rstrip(' .')!=p for p in name.split('/')):
            raise RuntimeError('invalid offline package name')
        workspace=workspace.resolve()
        target = workspace / "node_modules" / name
        if not target.resolve().is_relative_to(workspace):raise RuntimeError('dependency target leaves workspace')
        for parent in (target,*target.parents):
            if parent==workspace:break
            if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(),'st_file_attributes',0)&0x400):
                raise RuntimeError('redirected dependency destination')
        members=[]
        for member in tar.getmembers():
            if not member.name.startswith('package/'):continue
            relative=member.name[len('package/'):]
            if not relative:continue
            if ('\\' in relative or ':' in relative or PurePosixPath(relative).is_absolute()
                    or any(p=='..' or p.rstrip(' .')!=p or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p)
                           for p in PurePosixPath(relative).parts)
                    or not (member.isfile() or member.isdir())):
                raise RuntimeError('unsafe offline dependency archive member')
            members.append((member,relative))
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        for member,relative in members:
            member.name = relative
            try:
                tar.extract(member, target, filter="data")
            except TypeError:  # Python < 3.11.4 has no `filter`
                tar.extract(member, target)
        _write_bin_shims(workspace, name, manifest)
    return name


def _write_bin_shims(workspace: Path, name: str, manifest: dict) -> None:
    bins = manifest.get("bin") or {}
    if isinstance(bins, str):
        bins = {name.rsplit('/',1)[-1]: bins}
    if not bins:
        return
    bin_dir = workspace / "node_modules" / ".bin"
    if not bin_dir.resolve().is_relative_to(workspace.resolve()) or bin_dir.is_symlink() or (bin_dir.exists() and getattr(bin_dir.lstat(),'st_file_attributes',0)&0x400):
        raise RuntimeError('redirected offline bin directory')
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool, entry in bins.items():
        if (not isinstance(tool,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*',tool)
                or tool.rstrip(' .')!=tool or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',tool)
                or not isinstance(entry,str) or not re.fullmatch(r'[A-Za-z0-9_./@+~-]+',entry)
                or PurePosixPath(entry).is_absolute() or any(p=='..' or p.rstrip(' .')!=p for p in PurePosixPath(entry).parts)):
            raise RuntimeError('invalid offline bin declaration')
        if not (workspace/'node_modules'/name/entry).is_file():raise RuntimeError('offline bin entry missing')
        posix = bin_dir / tool
        for path in (posix,bin_dir/f'{tool}.cmd'):
            if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
                raise RuntimeError('redirected offline bin file')
        posix.write_text(BIN_SHIM_POSIX.format(package=name, entry=entry),
                         encoding="utf-8", newline="\n")
        (bin_dir / f"{tool}.cmd").write_text(BIN_SHIM_CMD.format(package=name, entry=entry),
                                             encoding="utf-8", newline="\n")


def materialize_deps(fixture_dir: Path, workspace: Path) -> list[str]:
    """Extract every `deps/*.tgz` of a fixture into the workspace; return the names."""
    deps_dir = fixture_dir / "deps"
    if not deps_dir.is_dir():
        return []
    installed: list[str] = []
    for archive in sorted(deps_dir.glob("*.tgz")):
        try:
            installed.append(_extract(archive, workspace))
        except Exception as error:  # noqa: BLE001 - fail closed, but name the archive
            raise RuntimeError(
                f"fixture dependency {archive} could not be materialised: {error}"
            ) from error
    return installed
