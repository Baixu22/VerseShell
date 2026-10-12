"""No-network regressions for source identity, merge integrity and Responses."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bench/aci/runners'))
import live_agent_loop as h
import merge_live_runs as merger
from live_identity import validate_run
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import live_round


def payload(seed=42):
    cfg = dict(model='offline', api_base='http://offline.invalid/v1/responses', protocol='responses',
               caps='file.read', max_turns=8, max_tokens=16384, temperature=0, exclude_tools=[],
               tasks=['task'], conditions=['verseshell_aci'], repeat=1, collection_id='test-study', seed=seed)
    evidence = dict(globs=['test'], fingerprint='original-acquisition')
    identity = {k:v for k,v in cfg.items() if k != 'seed'}
    identity.update(seeds=[seed], task_set_version='test', evidence=evidence, binary_sha256='binary')
    row = dict(task_id='task', condition='verseshell_aci', model='offline', seed=seed, run_index=0,
               success=True, tool_calls=1, observation_tokens=10, elapsed_ms=1, turns=1, trajectory=[])
    return dict(schema='test', mode='live', task_set_version='test', git_rev='original-revision',
                evidence=evidence, run_identity=identity, live_config=cfg, rows=[row])


class PreflightTests(unittest.TestCase):
    def merge(self, sources):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); out=root/'out.json'; out.write_text('sentinel')
            paths=[]
            for i,p in enumerate(sources):
                path=root/f'{i}.json'; path.write_text(json.dumps(p), encoding='utf-8'); paths.append(str(path))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc=merger.main([*paths, '--out', str(out)])
            return rc, out.read_text(encoding='utf-8')

    def test_merge_keeps_acquisition_source_and_repeat_count(self):
        rc,text=self.merge([payload(42),payload(43)])
        self.assertEqual(rc,0)
        merged=json.loads(text)
        self.assertEqual(merged['evidence']['fingerprint'],'original-acquisition')
        self.assertEqual(merged['git_rev'],'original-revision')
        self.assertEqual(merged['live_config']['repeat'],1)
        self.assertEqual(merged['run_identity']['seeds'],[42,43])
        self.assertEqual(len(merged['sources']),2)
        validate_run(merged)

    def test_mixed_missing_and_duplicate_inputs_preserve_output(self):
        for case in ('duplicate','missing','code','tasks','caps','legacy'):
            with self.subTest(case=case):
                a=payload(); b=payload(43)
                if case=='duplicate': b=copy.deepcopy(a)
                elif case=='missing': b['rows']=[]
                elif case=='code': b['evidence']['fingerprint']='different'
                elif case=='tasks': b['task_set_version']='different'
                elif case=='caps': b['live_config']['caps']='file.write'
                else: b.pop('run_identity')
                rc,text=self.merge([a,b])
                self.assertEqual((rc,text),(2,'sentinel'))

    def test_old_checkpoint_is_refused_before_any_model_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out.json'; cp=out.with_name(out.name+'.rows.jsonl')
            cp.write_text(json.dumps({'_config':{'model':'offline'}})+'\n',encoding='utf-8')
            original=cp.read_bytes()
            with patch.object(h,'run_agent_loop') as model, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc=h.main(['--model','offline','--api-key','test','--tasks','rust_fix_compile_error',
                           '--conditions','verseshell_aci','--out',str(out)])
            self.assertEqual(rc,2); model.assert_not_called()
            self.assertEqual(cp.read_bytes(),original); self.assertFalse(out.exists())

    def test_responses_roundtrip_retains_reasoning_and_call_identity(self):
        output=[{'type':'reasoning','id':'rs1','summary':[], 'encrypted_content':'opaque'},
                {'type':'function_call','id':'fc1','call_id':'call1','name':'read_file','arguments':'{"path":"x"}'}]
        response=h.responses_result({'status':'completed','output':output,
                                     'usage':{'input_tokens':12,'output_tokens':7,'output_tokens_details':{'reasoning_tokens':5}}})
        msg=response['choices'][0]['message']
        self.assertEqual(msg['tool_calls'][0]['id'],'call1')
        self.assertEqual(response['usage'],{'prompt_tokens':12,'completion_tokens':7})
        self.assertNotIn('reasoning_content',msg)
        messages=[{'role':'user','content':'read x'}, {'role':'assistant',**msg},
                  {'role':'tool','tool_call_id':'call1','content':'file contents'}]
        items=h.responses_input(messages)
        self.assertEqual(items[1:3],output)
        self.assertEqual(items[3],{'type':'function_call_output','call_id':'call1','output':'file contents'})

    def test_responses_truncation_and_missing_usage_stay_honest(self):
        result=h.responses_result({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]})
        self.assertEqual(result['choices'][0]['finish_reason'],'length')
        self.assertEqual(result['usage'],{})
        with self.assertRaises(ValueError): h.responses_result({'status':'failed','error':{'code':'server_error'}})

    def test_responses_request_uses_exact_url_and_optional_schema(self):
        response=io.BytesIO(json.dumps({'status':'completed','output':[],'usage':{'input_tokens':1,'output_tokens':1}}).encode())
        response.status=200
        with patch.object(h.urllib.request,'urlopen',return_value=response) as request:
            h.chat_completion([{'role':'user','content':'hello'}],h.ACI_TOOLS,model='glm-5.3-flash',
                              api_key='test',base_url='http://offline.invalid/v1/responses',seed=42,max_tokens=16384)
        req=request.call_args.args[0]; body=json.loads(req.data)
        self.assertEqual(req.full_url,'http://offline.invalid/v1/responses')
        self.assertNotIn('seed',body); self.assertFalse(body['store'])
        self.assertEqual(body['max_output_tokens'],16384)
        self.assertFalse(body['tools'][0]['strict'])
        self.assertEqual(body['tools'][0]['parameters'],h.ACI_TOOLS[0]['function']['parameters'])

    def test_runner_starts_with_user_turn_for_responses_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'workspace'; workspace.mkdir()
            reply={'usage':{'prompt_tokens':1,'completion_tokens':1},
                   'choices':[{'finish_reason':'stop','message':{'content':'done'}}]}
            task={'id':'offline','workspace_fixture':'offline','prompt':'Test task', 'success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace), patch.object(h,'check_success',return_value=(True,'offline')), patch.object(h,'chat_completion',return_value=reply) as call:
                h.run_agent_loop(task,'verseshell_aci',model='offline',api_key='test',base_url='http://offline.invalid/v1/responses')
            messages=call.call_args.args[0]
            self.assertEqual(messages[0]['role'],'system')
            self.assertEqual(messages[1],{'role':'user','content':'Begin the task.'})

    def test_checkpoint_binds_source_tasks_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out.json'
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error',
                  '--conditions','verseshell_aci','--seed','42','--out',str(out)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main([*args,'--dry-run']),0)
            frozen=json.loads(out.read_text(encoding='utf-8'))['run_identity']
            cp=out.with_name(out.name+'.rows.jsonl')
            for field in ('caps','tasks','binary_sha256','evidence','collection_id'):
                changed=copy.deepcopy(frozen); changed[field]='different'
                cp.write_text(json.dumps({'_config':changed})+'\n',encoding='utf-8')
                before=cp.read_bytes()
                with patch.object(h,'run_agent_loop') as model, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(h.main(args),2)
                model.assert_not_called(); self.assertEqual(cp.read_bytes(),before)

    def test_round_dry_run_freezes_and_rejects_legacy_output_without_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); env=root/'.env.local'
            env.write_text('ACI_BENCH_MODEL=offline\nACI_BENCH_BASE_URL=http://offline.invalid/v1/responses\nACI_BENCH_API_KEY=test\n')
            args=['live_round.py','--tag','study','--env-file',str(env)]
            with patch.object(live_round,'RESULTS',root), patch.object(live_round,'run') as execute, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with patch.object(sys,'argv',[*args,'--dry-run']): self.assertEqual(live_round.main(),0)
                freeze=(root/'study/collection.json').read_bytes()
                (root/'study/with_seed42.json').write_text('{}')
                with patch.object(sys,'argv',args): self.assertEqual(live_round.main(),2)
                execute.assert_not_called()
                self.assertEqual((root/'study/collection.json').read_bytes(),freeze)


if __name__=='__main__': unittest.main()
