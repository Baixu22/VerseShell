"""Behavioural grading for the small, std-only add/sum tasks (never edits inputs)."""
import re
import shutil
import tempfile
from pathlib import Path
from grading_contract import grading_environment


def rust_behavior(pred, workspace, run):
    name = pred.get('function')
    if name not in ('add', 'sum'):
        return None, 'unverified: unsupported Rust grading contract'
    with tempfile.TemporaryDirectory(prefix='aci-grade-') as tmp:
        copy = Path(tmp)/'work'
        shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns('target', '.git', '.ae'))
        source = copy/'src/lib.rs'
        if not source.exists():
            return False, 'missing src/lib.rs'
        original = source.read_text(encoding='utf-8')

        def cargo(*args):
            try:
                rc, stdout, stderr, timeout = run(['cargo', 'test', '--offline', '--lib', *args],
                                                 cwd=copy, timeout=int(pred.get('timeout_sec', 120)),
                                                 env=grading_environment(copy))
            except FileNotFoundError:
                return None, 'unverified: cargo not found'
            output = (stdout+stderr).decode('utf-8', 'replace')
            if timeout:
                return None, 'unverified: grading timeout'
            if 'linker' in output and 'not found' in output:
                return None, 'unverified: linker not found'
            return rc == 0, output

        ok, detail = cargo('--', '--test-threads=1')
        if ok is not True:
            return ok, detail if ok is None else 'student tests/build failed'
        if pred.get('require_unit_tests'):
            passed = re.findall(r'test result: ok\. (\d+) passed;', detail)
            if not passed or sum(map(int, passed)) == 0:
                return False, 'no executed unit tests'

        checks = '\n#[cfg(test)] mod __ae_behavior { #[test] fn contract() {\n'
        checks += f'for (a,b) in [(2,3),(-1,1),(0,7),(8,-3)] {{ assert_eq!(super::{name}(a,b),a+b); }}'
        checks += '\n}}\n'
        source.write_text(original+checks, encoding='utf-8')
        ok, detail = cargo('__ae_behavior::contract', '--', '--exact')
        if ok is not True:
            return ok, detail if ok is None else 'function behaviour failed'
        if not re.search(r'test result: ok\. 1 passed;', detail):
            return False, 'behaviour contract did not execute'

        if pred.get('require_unit_tests'):
            renamed, count = re.subn(r'(\bpub\s+fn\s+)'+name+r'(\s*\()', r'\1__ae_original\2', original)
            if count != 1:
                return None, 'unverified: unsupported public function declaration'
            for operator in ('-', '*'):
                source.write_text(renamed+f'\npub fn {name}(a:i32,b:i32)->i32{{a{operator}b}}\n', encoding='utf-8')
                ok, detail = cargo('--no-run')
                if ok is not True:
                    return None, 'unverified: mutant did not compile' if ok is False else detail
                ok, detail = cargo('--', '--test-threads=1')
                if ok is None:
                    return None, detail
                if ok:
                    return False, f'unit tests did not detect {operator} mutant'
        return True, 'behaviour and required unit-test checks passed'
