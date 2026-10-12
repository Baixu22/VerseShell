"""Candidate generation and A8 must use their own Cargo output directories."""
import os,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'bench/aci/runners')]
import task_admissibility as admission
import task_generate_v2 as generation
import live_agent_loop as h

class CandidateEnvironmentTests(unittest.TestCase):
    def test_generator_supplies_workspace_local_target(self):
        with patch.object(generation,'run_bounded',return_value=(0,b'ok',b'',False)) as run:
            self.assertTrue(generation.run_suite({'x.txt':'value'},['echo','ok'])[0])
        self.assertEqual(run.call_args.kwargs.get('env',{}).get('CARGO_TARGET_DIR'),str(Path(run.call_args.kwargs['cwd']).resolve()/'target'))

    def test_a8_supplies_local_target_and_execution_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'candidate';(c/'fixture').mkdir(parents=True)
            with patch.object(admission,'run_bounded',return_value=(7,b'failure',b'diagnostic',False)) as run:
                result=admission.observation_counts(c,{'type':'command_exit_0','argv':['tool']})
            self.assertEqual(run.call_args.kwargs.get('env',{}).get('CARGO_TARGET_DIR'),str(Path(run.call_args.kwargs['cwd']).resolve()/'target'))
            self.assertEqual(result['exit_code'],7)

    @unittest.skipUnless(shutil.which('cargo'),'cargo required')
    def test_a8_does_not_execute_cached_golden_for_a_pristine_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();shared=root/'shared'
            cargo='[package]\nname="a8_cache_probe"\nversion="0.1.0"\nedition="2021"\n'
            for name,value in [('golden',1),('pristine',0)]:
                w=root/name/'fixture';(w/'src').mkdir(parents=True)
                (w/'Cargo.toml').write_text(cargo)
                (w/'src/lib.rs').write_text('pub fn value()->i32{'+str(value)+'}\n#[test] fn check(){assert_eq!(value(),1);}')
                for p in w.rglob('*'):
                    if p.is_file():os.utime(p,(946684800,946684800))
            env={**os.environ,'CARGO_TARGET_DIR':str(shared),'CARGO_BUILD_JOBS':'1'}
            rc,_,err,timed=h.run_bounded(['cargo','test','--offline'],cwd=root/'golden/fixture',timeout=90,env=env)
            self.assertEqual(rc,0,err);self.assertFalse(timed)
            actual=[];original=admission.run_bounded
            def record(*args,**kw):
                result=original(*args,**kw);actual.append(result);return result
            with patch.dict(os.environ,env),patch.object(admission,'run_bounded',side_effect=record):
                admission.observation_counts(root/'pristine',{'type':'command_exit_0','argv':['cargo','test','--offline']},90)
            self.assertEqual(actual[0][0],101,actual[0][1].decode('utf-8','replace'))

if __name__=='__main__':unittest.main()
