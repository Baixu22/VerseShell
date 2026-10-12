import hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
import live_agent_loop as h
from task_sets import load_tasks


class SemanticTests(unittest.TestCase):
    def test_versioned_set_preserves_base_and_replaces_only_verified_contracts(self):
        base=ROOT/'bench/aci/tasks'
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.glob('*.json')}
        manifest,tasks=load_tasks(base,ROOT/'bench/aci/task_sets/3.1.0.json')
        self.assertEqual(manifest['task_set_version'],'3.1.0')
        self.assertEqual(tasks['rust_add_unit_test']['success']['type'],'rust_behavior')
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.glob('*.json')})

    def test_semantic_and_mutation_controls(self):
        cases=[('add',True,'#[test] fn tests(){assert_eq!(super::add(2,3),5);assert_eq!(super::add(-1,1),0);}',True),
               ('add',True,'',False),('add',True,'#[test] fn tests(){assert_eq!(1,1);}',False),
               ('add',True,'#[test] #[ignore] fn tests(){assert_eq!(super::add(2,3),5);}',False),
               ('sum',False,'',True)]
        for name,required,tests,expected in cases:
            with self.subTest(name=name,tests=tests),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'src').mkdir()
                (root/'Cargo.toml').write_text('[package]\nname="grading_control"\nversion="0.1.0"\nedition="2021"\n')
                source=f'pub fn {name}(a:i32,b:i32)->i32{{a+b}}\n#[cfg(test)] mod tests {{{tests}}}\n'
                (root/'src/lib.rs').write_text(source)
                result,reason=h.check_success({'type':'rust_behavior','function':name,'require_unit_tests':required},root)
                self.assertIs(result,expected,reason)
                self.assertEqual((root/'src/lib.rs').read_text(),source)

    def test_comment_spoof_does_not_pass(self):
        for name in ('add','sum'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'src').mkdir()
                (root/'Cargo.toml').write_text('[package]\nname="grading_control"\nversion="0.1.0"\nedition="2021"\n')
                (root/'src/lib.rs').write_text(f'// #[test] assert_eq!(add(1, 2), 3) return a + b\npub fn {name}(a:i32,b:i32)->i32{{a*b}}\n')
                result,reason=h.check_success({'type':'rust_behavior','function':name,'require_unit_tests':name=='add'},root)
                self.assertIs(result,False,reason)

    def test_grading_infrastructure_failure_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'src').mkdir();(root/'src/lib.rs').write_text('pub fn sum(a:i32,b:i32)->i32{a+b}')
            pred={'type':'rust_behavior','function':'sum'}
            with patch.object(h,'run_bounded',side_effect=FileNotFoundError):
                self.assertIsNone(h.check_success(pred,root)[0])
            with patch.object(h,'run_bounded',return_value=(None,b'',b'',True)):
                self.assertIsNone(h.check_success(pred,root)[0])

    def test_other_text_only_contracts_use_behavior_or_exact_artifacts(self):
        _,tasks=load_tasks(ROOT/'bench/aci/tasks',ROOT/'bench/aci/task_sets/3.1.0.json')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for body,expected in [('other:12',False),('src/main.rs:12',True),('src\\main.rs:12',True)]:
                (root/'ERR.txt').write_text(body)
                self.assertIs(h.check_success(tasks['windows_batch_capture_diag']['success'],root)[0],expected)
            (root/'tests').mkdir();(root/'tests/test_math.py').write_text('from mathlib import add\ndef test_add(): assert add(2,3)==5\n')
            for body,expected in [('def add(a,b): return (a+b)\n',True),('# return a + b\ndef add(a,b): return a*b\n',False)]:
                (root/'mathlib.py').write_text(body)
                self.assertIs(h.check_success(tasks['python_fix_pytest_fail']['success'],root)[0],expected)
            for script,expected in [('node -e "process.exit(0*1)"',True),('node -e "process.exit(1)"',False)]:
                (root/'package.json').write_text(json.dumps({'scripts':{'test':script},'note':'process.exit(0)'}))
                self.assertIs(h.check_success(tasks['ts_package_script_fail']['success'],root)[0],expected)


if __name__=='__main__':unittest.main()
