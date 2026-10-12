"""Freeze verifier bytes before student edits; shared by live and admission.

This detects file tampering, not arbitrary adversarial code execution. It does
not make same-user grading a security sandbox.
"""
import hashlib
import shutil
import tempfile
import os
from pathlib import Path
from fixture_deps import materialize_deps

VERIFIER_PATTERNS = (
    'test_*.py', '*_test.py', 'conftest.py', 'tests/**/*.py',
    '*_test.rs', 'tests/**/*.rs', '*.test.ts', '*.spec.ts',
    '*.test.js', '*.spec.js', 'tests/**/*.ts', 'test_*.sh', '*_test.sh',
)
GRADING_IGNORES = ('target','__pycache__','.pytest_cache','.ae')

GRADING_HOOKS = ('conftest.py','pytest.ini','sitecustomize.py','usercustomize.py',
                 '.cargo/config','.cargo/config.toml')


def grading_environment(workspace):
    """Tools and grading copies must not reuse another workspace's Cargo binaries.

    Keep PATH/PATHEXT and other host variables; only the build output is local to
    this workspace (a disposable copy when grading). This is not an environment sandbox.
    """
    return {**os.environ, 'CARGO_TARGET_DIR': str(Path(workspace).resolve()/'target')}


def grading_configs(predicate):
    """Configuration which selects what the declared verifier actually runs."""
    configs=set()
    def walk(node):
        if not isinstance(node,dict):return
        argv=node.get('argv') or []
        executable=Path(str(argv[0])).name.lower() if argv else ''
        if node.get('type')=='rust_behavior' or executable in ('cargo','cargo.exe'):
            configs.update(('Cargo.toml','Cargo.lock'))
        if any('pytest' in str(arg) for arg in argv):
            configs.update(('pytest.ini','pyproject.toml','setup.cfg','tox.ini'))
        for child in node.get('of') or []:walk(child)
    walk(predicate)
    return configs


def predicate_executed_paths(predicate, fixture):
    fixture = Path(fixture).resolve()
    found = set()
    def walk(node):
        if not isinstance(node, dict): return
        if node.get('type') == 'command_exit_0':
            for arg in node.get('argv') or []:
                if not isinstance(arg, str): continue
                path = fixture / arg.replace('\\', '/')
                if path.resolve().is_relative_to(fixture) and path.is_relative_to(fixture) and path.is_file():
                    found.add(path.relative_to(fixture).as_posix())
        for child in node.get('of') or []: walk(child)
    walk(predicate)
    return sorted(found)


def freeze_verifiers(predicate, fixture):
    fixture = Path(fixture).resolve()
    paths = set(predicate_executed_paths(predicate, fixture))
    paths.update(name for name in grading_configs(predicate) if (fixture/name).is_file())
    if any(p.endswith(('typescript/bin/tsc','typescript/lib/tsc.js')) for p in paths) and (fixture/'tsconfig.json').is_file():
        paths.add('tsconfig.json')
    # Declared offline toolchains are part of the verifier, not student code.
    # Protect transitive compiler modules, not only the tiny bin/tsc entrypoint.
    paths.update(p.relative_to(fixture).as_posix() for p in (fixture/'node_modules').rglob('*') if p.is_file())
    paths.update(name for name in GRADING_HOOKS if (fixture/name).is_file())
    for pattern in VERIFIER_PATTERNS:
        paths.update(p.relative_to(fixture).as_posix() for p in fixture.glob(pattern) if p.is_file())
    frozen = {}
    for name in sorted(paths):
        path = fixture / name
        if path.is_symlink() or not path.resolve().is_relative_to(fixture):
            raise ValueError(f'verifier leaves fixture: {name}')
        frozen[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return frozen


def freeze_fixture_verifiers(predicate, fixture):
    """Use the same materialized dependency surface as prepare_workspace."""
    with tempfile.TemporaryDirectory(prefix='aci-contract-') as tmp:
        workspace=Path(tmp)/'work'
        shutil.copytree(fixture,workspace,ignore=shutil.ignore_patterns('GOLDEN','deps','target','__pycache__','.pytest_cache'))
        materialize_deps(Path(fixture),workspace)
        return freeze_verifiers(predicate,workspace)


def verify_verifiers(workspace, frozen, predicate=None):
    workspace = Path(workspace).resolve()
    for name in set(GRADING_HOOKS)|(grading_configs(predicate)-{'Cargo.lock'}):
        if (workspace/name).exists() and name not in frozen:
            return False, f'unregistered grading hook: {name}'
    for path in workspace.glob('tests/**/conftest.py'):
        if path.relative_to(workspace).as_posix() not in frozen:
            return False, 'unregistered nested grading hook'
    for name, digest in frozen.items():
        path = workspace / name
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(workspace):
                return False, f'protected verifier redirected: {name}'
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return False, f'protected verifier changed: {name}'
        except OSError:
            return False, f'protected verifier missing: {name}'
    return True, 'protected verifier bytes intact'


def guarded_success(predicate, workspace, frozen, evaluator, before_evaluate=None):
    ok, reason = verify_verifiers(workspace, frozen, predicate)
    if not ok: return ok, reason
    # Grade a disposable copy, never the live agent's writable workspace.
    # Protected files are checked both before copying and after execution.
    # This is execution-state isolation, not a same-user security sandbox.
    with tempfile.TemporaryDirectory(prefix='aci-verify-') as tmp:
        copy=Path(tmp)/'work'
        for root,dirs,files in os.walk(workspace):
            dirs[:]=[d for d in dirs if d not in GRADING_IGNORES]
            for name in dirs+files:
                path=Path(root)/name
                if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
                    return False, f'grading workspace contains redirected path: {path.relative_to(workspace)}'
        shutil.copytree(workspace,copy,ignore=shutil.ignore_patterns(*GRADING_IGNORES))
        ok,reason=verify_verifiers(copy,frozen,predicate)
        if not ok:return ok,reason
        if before_evaluate is not None:before_evaluate(copy)
        result=evaluator(predicate,copy)
        ok,reason=verify_verifiers(copy,frozen,predicate)
        if not ok:return ok,reason
        ok,reason=verify_verifiers(workspace,frozen,predicate)
        return result if ok else (ok,reason)
