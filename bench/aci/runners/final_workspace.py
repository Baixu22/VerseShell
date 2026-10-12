"""Bounded grading inputs with explicit external verifier references, not a sandbox."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

from grading_contract import GRADING_IGNORES
from live_journal import redact

MAX_FILES = 10000
MAX_BYTES = 128 * 1024**2
MAX_FILE_BYTES = 64 * 1024**2
MAX_MANIFEST_BYTES = 8 * 1024**2
GRADER_FILES = ('live_agent_loop.py', 'grading_contract.py', 'semantic_checks.py', 'fixture_deps.py',
                'final_workspace.py', 'live_journal.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def grader_hashes():
    return {name: digest(Path(__file__).with_name(name).read_bytes()) for name in GRADER_FILES}


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or any(c in name for c in ':<>"|?*') or any(ord(c) < 32 for c in name):
        raise ValueError('invalid snapshot path')
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name or any(p in ('.', '..') or p.endswith((' ', '.')) for p in path.parts):
        raise ValueError('invalid snapshot path')
    if any(re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])', p.split('.')[0]) for p in path.parts):
        raise ValueError('reserved snapshot path')
    return path


def check_verifier_digests(frozen):
    if not isinstance(frozen, dict):
        raise ValueError('invalid snapshot grading contract')
    for name, sha in frozen.items():
        safe_name(name)
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('invalid snapshot verifier digest')


def inside(root, name):
    safe_name(name)
    root = Path(root).resolve()
    path = root/name
    if not path.resolve().is_relative_to(root):
        raise ValueError('snapshot path leaves artifact directory')
    current = root
    for part in PurePosixPath(name).parts:
        current = current/part
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('snapshot path is redirected')
    return path


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        body = stream.read(limit+1)
    if len(body) > limit:
        raise ValueError('snapshot byte limit exceeded')
    return body


def store_bytes(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read_bounded(path, len(body)) != body:
            raise ValueError('stored snapshot content mismatch')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='snapshot-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


class FinalWorkspaceStore:
    def __init__(self, directory, secrets=(), *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
        if any(type(n) is not int or n < 0 for n in (max_files, max_bytes)):
            raise ValueError('invalid snapshot limits')
        self.directory = Path(directory)
        self.secrets = tuple(s.encode('utf-8').decode('latin-1') for s in secrets if s)
        self.max_files = min(max_files, MAX_FILES)
        self.max_bytes = min(max_bytes, MAX_BYTES)

    def _check_secret(self, body, *, protected=False):
        text = body.decode('latin-1')
        if redact(text, self.secrets) != text:
            # Never persist these bytes. Only unchanged, pre-frozen verifier files
            # may be referenced externally; an actual runtime secret still fails.
            if protected and not any(secret in text for secret in self.secrets):
                return True
            raise ValueError('snapshot contains credential material; exact capture unavailable')
        return False

    def _scan(self, workspace, save, protected_verifiers):
        files = []; directories = []; total = 0; names = set()
        workspace = Path(workspace).resolve()
        def walk_error(error):raise error
        for root, dirs, filenames in os.walk(workspace, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if d not in GRADING_IGNORES)
            for name in dirs + sorted(n for n in filenames if n not in GRADING_IGNORES):
                path = Path(root)/name
                rel = path.relative_to(workspace).as_posix()
                safe_name(rel)
                self._check_secret(rel.encode('utf-8'))
                info = path.lstat()
                if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('snapshot contains a redirected path')
                if rel.casefold() in names:
                    raise ValueError('snapshot has case-colliding paths')
                names.add(rel.casefold())
                if len(names) > self.max_files:
                    raise ValueError('snapshot entry limit exceeded')
                if stat.S_ISDIR(info.st_mode):
                    directories.append(rel)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('snapshot contains a non-regular file')
                body = read_bounded(path, min(MAX_FILE_BYTES, max(0, self.max_bytes-total)))
                sha = digest(body)
                reference_only = self._check_secret(body, protected=protected_verifiers.get(rel) == sha)
                total += len(body)
                if total > self.max_bytes:
                    raise ValueError('snapshot byte limit exceeded')
                if save and not reference_only:store_bytes(inside(self.directory, 'blobs/'+sha), body)
                files.append({'path': rel, 'sha256': sha, 'bytes': len(body),
                              'mode': stat.S_IMODE(info.st_mode) & 0o777,
                              'storage': 'protected_verifier' if reference_only else 'blob'})
        return files, directories, total

    def capture(self, workspace, *, cell_id, task_id, predicate, protected_verifiers):
        workspace = Path(workspace).resolve()
        if self.directory.resolve().is_relative_to(workspace):
            raise ValueError('snapshot store must be outside grading input')
        check_verifier_digests(protected_verifiers)
        files, directories, total = self._scan(workspace, True, protected_verifiers)
        if (files, directories, total) != self._scan(workspace, False, protected_verifiers):
            raise ValueError('grading input changed during capture')
        reference_count = sum(entry['storage'] == 'protected_verifier' for entry in files)
        manifest = {'schema': 'verseshell.final-workspace/v2', 'stage': 'before_grading_evaluator',
                    'cell_id': cell_id, 'task_id': task_id, 'predicate': predicate,
                    'protected_verifiers': protected_verifiers, 'grader_sha256': grader_hashes(),
                    'files': files, 'directories': directories, 'total_bytes': total,
                    'excluded_names': list(GRADING_IGNORES),
                    'scope': 'grading-input files only; external verifier references require explicit hash-matching source bytes; excludes runtime environment, toolchain executables, network and process state'}
        body = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode('utf-8')
        self._check_secret(body)
        if len(body) > MAX_MANIFEST_BYTES:
            raise ValueError('snapshot manifest limit exceeded')
        sha = digest(body)
        store_bytes(inside(self.directory, 'manifests/'+sha+'.json'), body)
        return {'state': 'requires_verifier_source' if reference_count else 'available',
                'path': self.directory.name+'/manifests/'+sha+'.json',
                'sha256': sha, 'file_count': len(files), 'total_bytes': total,
                'protected_reference_count': reference_count,
                'scope': manifest['scope']}


def entry_body(store, entry, verifier_source=None):
    external = entry.get('storage', 'blob') == 'protected_verifier'
    if external:
        if verifier_source is None:
            raise ValueError('snapshot requires an explicit frozen verifier source')
        path = inside(verifier_source, entry['path'])
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('snapshot verifier source is not a regular file')
    else:
        path = inside(store, 'blobs/'+entry['sha256'])
    label = 'verifier source' if external else 'blob'
    try:
        body = read_bounded(path, entry['bytes'])
    except ValueError as error:
        raise ValueError(f'snapshot {label} size mismatch') from error
    if len(body) != entry['bytes'] or digest(body) != entry['sha256']:
        raise ValueError(f'snapshot {label} hash mismatch')
    return body


def load_manifest(root, reference, *, verifier_source=None):
    if not isinstance(reference, dict) or reference.get('state') not in ('available', 'requires_verifier_source'):
        raise ValueError('final workspace snapshot unavailable')
    manifest_path = inside(root, reference.get('path'))
    body = read_bounded(manifest_path, MAX_MANIFEST_BYTES)
    if digest(body) != reference.get('sha256'):
        raise ValueError('snapshot manifest hash mismatch')
    manifest = json.loads(body)
    if (not isinstance(manifest, dict) or manifest.get('schema') not in ('verseshell.final-workspace/v1', 'verseshell.final-workspace/v2')
            or manifest.get('stage') != 'before_grading_evaluator'):
        raise ValueError('unsupported snapshot schema or stage')
    frozen = manifest.get('protected_verifiers')
    if not isinstance(manifest.get('predicate'), dict) or not isinstance(frozen, dict):
        raise ValueError('invalid snapshot grading contract')
    check_verifier_digests(frozen)
    files = manifest.get('files'); directories = manifest.get('directories')
    if (not isinstance(files, list) or not isinstance(directories, list) or len(files)+len(directories) > MAX_FILES
            or any(not isinstance(entry, dict) or 'path' not in entry for entry in files)):
        raise ValueError('invalid snapshot inventory')
    if manifest.get('excluded_names') != list(GRADING_IGNORES):
        raise ValueError('snapshot scope differs from grader')
    names = set(); total = 0
    for name in directories + [entry['path'] for entry in files]:
        safe_name(name)
        if name.casefold() in names:
            raise ValueError('duplicate snapshot path')
        if any(part in GRADING_IGNORES for part in PurePosixPath(name).parts):
            raise ValueError('snapshot includes excluded grading paths')
        names.add(name.casefold())
    directory_names = set(directories)
    for name in directories + [entry['path'] for entry in files]:
        if any(str(parent) not in directory_names for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ValueError('snapshot directory inventory incomplete')
    for entry in files:
        if (type(entry.get('bytes')) is not int or not 0 <= entry['bytes'] <= MAX_FILE_BYTES
                or type(entry.get('mode')) is not int or not 0 <= entry['mode'] <= 0o777
                or not isinstance(entry.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
            raise ValueError('invalid snapshot file metadata')
        storage = entry.get('storage', 'blob')
        if ((manifest['schema'] == 'verseshell.final-workspace/v1' and 'storage' in entry)
                or (manifest['schema'] == 'verseshell.final-workspace/v2' and 'storage' not in entry)
                or storage not in ('blob', 'protected_verifier')
                or (storage == 'protected_verifier' and frozen.get(entry['path']) != entry['sha256'])):
            raise ValueError('invalid snapshot storage or protected verifier reference')
        total += entry['bytes']
        if total > MAX_BYTES:
            raise ValueError('snapshot byte limit exceeded')
    if (type(manifest.get('total_bytes')) is not int or type(reference.get('file_count')) is not int
            or type(reference.get('total_bytes')) is not int or total != manifest['total_bytes']
            or len(files) != reference['file_count'] or total != reference['total_bytes']):
        raise ValueError('snapshot totals mismatch')
    reference_count = sum(entry.get('storage') == 'protected_verifier' for entry in files)
    if (type(reference.get('protected_reference_count', 0)) is not int
            or reference.get('protected_reference_count', 0) != reference_count
            or reference['state'] != ('requires_verifier_source' if reference_count else 'available')):
        raise ValueError('snapshot protected reference count or state mismatch')
    store = manifest_path.parent.parent
    for entry in files:
        entry_body(store, entry, verifier_source)
    return manifest, store


def restore(root, reference, destination, *, verifier_source=None):
    manifest, store = load_manifest(root, reference, verifier_source=verifier_source)
    destination = Path(destination)
    if destination.exists():
        raise ValueError('snapshot restore requires a new destination')
    destination.mkdir(parents=True)
    for name in sorted(manifest['directories'], key=lambda p: len(PurePosixPath(p).parts)):
        inside(destination, name).mkdir(parents=True, exist_ok=True)
    for entry in manifest['files']:
        body = entry_body(store, entry, verifier_source)
        target = inside(destination, entry['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:stream.write(body)
        target.chmod(entry['mode'])
    return manifest
