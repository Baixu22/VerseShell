"""Offline TF-0138 arithmetic/coverage and byte-identical transport controls."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import cost_attribution as cost
import live_agent_loop as h
from input_profile import input_profile, valid_profile


def row(condition, tokens, task='one', seed=42, variant='baseline', model='offline', turns=1):
    return dict(task_id=task, condition=condition, model=model, seed=seed, run_index=0,
                prompt_variant=variant, success=True, llm_prompt_tokens=tokens,
                llm_completion_tokens=0, usage_complete=True, turns=turns,
                observation_tokens=1, tool_calls=1)


def fixture(values=((1000, 100), (1, 3))):
    return {'mode':'live', 'live_config':{'max_turns':20}, 'rows':[
        row(condition, value, task=str(i)) for i, pair in enumerate(values)
        for condition, value in zip(('raw_shell','verseshell_aci'), pair)]}


def profile():
    payload={'messages':[{'role':'system','content':'private system'},
                         {'role':'user','content':'task 中文'},
                         {'role':'assistant','content':'thought-free history'},
                         {'role':'tool','content':'output 中文'}], 'tools':[], 'model':'offline'}
    body=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    return payload, body, input_profile(payload,body)


class CostAttributionTests(unittest.TestCase):
    def test_opposing_estimands_use_the_same_two_pairs(self):
        c=cost.analyse(fixture())['comparisons'][0];e=c['estimands']
        self.assertEqual(c['valid_pairs'],2)
        self.assertAlmostEqual(e['ratio_of_sums'],103/1001)
        self.assertAlmostEqual(e['cell_equal_mean_of_ratios'],1.55)
        self.assertAlmostEqual(e['baseline_cost_weighted_mean_of_ratios'],e['ratio_of_sums'])
        self.assertTrue(e['total_and_cell_direction_disagree'])
        self.assertFalse(c['acceptance']['claimable'])

    def test_task_equal_sensitivity_is_not_cell_weighting(self):
        p=fixture(((100,10),(100,10),(1,3)))
        p['rows'][2]['task_id']=p['rows'][3]['task_id']='0'
        p['rows'][2]['seed']=p['rows'][3]['seed']=43
        e=cost.analyse(p)['comparisons'][0]['estimands']
        self.assertEqual(e['n_tasks'],2)
        self.assertAlmostEqual(e['cell_equal_mean_of_ratios'],3.2/3)
        self.assertAlmostEqual(e['task_equal_mean_of_ratios'],1.55)
        self.assertAlmostEqual(e['task_equal_ratio_of_mean_costs'],13/101)

    def test_unknown_usage_zero_baseline_and_missing_partner_are_explicit(self):
        p=fixture(((10,5),(10,2),(0,2),(10,1)))
        p['rows'][2]['usage_complete']=False
        p['rows'].pop()
        c=cost.analyse(p)['comparisons'][0]
        self.assertEqual((c['candidate_pair_keys'],c['matched_pairs'],c['usage_eligible_pairs'],c['valid_pairs']),(4,3,2,1))
        reasons=[r for e in c['excluded_pairs'] for r in e['reasons']]
        self.assertIn('baseline:usage_complete=false',reasons)
        self.assertIn('zero_baseline_undefined_cell_ratio',reasons)
        self.assertIn('missing_aci',reasons)
        self.assertEqual(c['estimands']['ratio_of_sums'],.5)
        self.assertEqual(c['overhead_on_identical_pairs']['baseline']['rows'],1)

    def test_explicit_zero_treatment_is_retained(self):
        c=cost.analyse(fixture(((10,0),)))['comparisons'][0]
        self.assertEqual(c['valid_pairs'],1)
        self.assertEqual(c['estimands']['ratio_of_sums'],0)
        self.assertEqual(c['estimands']['cell_equal_mean_of_ratios'],0)

    def test_invalid_nonfinite_and_boolean_usage_are_not_imputed(self):
        for value in (None,False,-1,float('nan'),float('inf')):
            p=fixture();p['rows'][0]['llm_prompt_tokens']=value
            c=cost.analyse(p)['comparisons'][0]
            self.assertEqual(c['valid_pairs'],1)
            json.dumps(c,allow_nan=False)

    def test_duplicate_or_missing_identity_rejected(self):
        p=fixture();p['rows'].append(dict(p['rows'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'): cost.analyse(p)
        p=fixture();del p['rows'][0]['seed']
        with self.assertRaisesRegex(ValueError,'identity'): cost.analyse(p)

    def test_models_and_variants_are_separate(self):
        p=fixture();original=copy.deepcopy(p['rows'])
        for model,variant in [('other','baseline'),('offline','compact_all')]:
            p['rows'] += [dict(r,model=model,prompt_variant=variant) for r in original]
        report=cost.analyse(p)
        self.assertEqual(len(report['comparisons']),3)
        self.assertTrue(all(c['valid_pairs']==2 for c in report['comparisons']))
        self.assertEqual(len(cost.analyse(p,'compact_all')['comparisons']),1)
        with self.assertRaisesRegex(ValueError,'not present'):cost.analyse(p,'absent')

    def test_caps_and_top_decile_report_signed_contributions(self):
        p=fixture();p['rows'][0]['turns']=20
        c=cost.analyse(p)['comparisons'][0];groups=c['contributions']
        self.assertAlmostEqual(groups['baseline_cost_top_decile']['baseline_token_share'],1000/1001)
        cap=groups['baseline_turn_cap_partition']
        self.assertEqual(sum(g['n_pairs'] for g in cap.values()),2)
        self.assertEqual(cap['at_cap']['token_reduction_A_minus_D'],900)
        self.assertGreater(cap['at_cap']['signed_net_reduction_share'],1)
        del p['live_config']['max_turns']
        self.assertEqual(cost.analyse(p)['comparisons'][0]['contributions']['baseline_turn_cap_partition']['unknown']['n_pairs'],2)

    def test_quantiles_empty_singleton_and_interpolation(self):
        self.assertIsNone(cost.quantiles([])['50'])
        self.assertEqual(cost.quantiles([3])['95'],3)
        self.assertEqual(cost.quantiles([0,10])['25'],2.5)

    def test_historical_missing_profiles_and_first_turns_remain_unknown(self):
        c=cost.analyse(fixture())['comparisons'][0]
        for side in c['overhead_on_identical_pairs'].values():
            self.assertIsNone(side['first_turn_prompt_tokens']['complete_total'])
            self.assertIsNone(side['request_input_profiles']['complete_prepared_bytes'])
            self.assertFalse(side['request_input_profiles']['coverage_complete'])

    def test_received_first_later_and_profile_byte_partition(self):
        _,_,prof=profile();r=row('raw_shell',30,turns=2)
        r['turn_diagnostics']=[{'turn':i+1,'prompt_tokens':v,'completion_tokens':0,
            'transport_attempts':[{'status':200,'request_body_sha256':prof['body_sha256'],'input_profile':prof}]} for i,v in enumerate((10,20))]
        o=cost.overhead([r]);p=o['request_input_profiles']
        self.assertEqual(o['first_turn_prompt_tokens']['complete_total'],10)
        self.assertEqual(o['later_turn_prompt_tokens']['complete_total'],20)
        self.assertTrue(p['coverage_complete'])
        totals=p['complete_prepared_bytes']
        self.assertEqual(totals['prepared_body_bytes'],sum(v for k,v in totals.items() if k!='prepared_body_bytes'))
        self.assertEqual(totals['prepared_body_bytes'],2*prof['prepared_body_bytes'])
        r['turn_diagnostics'][1]['transport_attempts'][0]['request_body_sha256']='0'*64
        self.assertIsNone(cost.overhead([r])['request_input_profiles']['complete_prepared_bytes'])

    def test_partial_never_becomes_claimable_despite_observed_costs(self):
        p=fixture();p['partial']=True
        c=cost.analyse(p)['comparisons'][0]
        self.assertTrue(c['estimands']['available'])
        self.assertIn('partial_artifact',c['acceptance']['policy_blocked_reasons'])

    def test_cli_preserves_input_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'frozen'/'source.json';source.parent.mkdir()
            source.write_text(json.dumps(fixture()),encoding='utf-8');before=source.read_bytes()
            target=root/'reports'/'report.json'
            args=['--with-arm',str(source),'--out',str(target)]
            with patch('sys.stdout',new_callable=io.StringIO),patch('sys.stderr',new_callable=io.StringIO):
                self.assertEqual(cost.main(args),0)
                saved=target.read_bytes()
                self.assertEqual(cost.main(args),2)
                self.assertEqual(cost.main(['--with-arm',str(source),'--out',str(source.parent/'new.json')]),2)
            self.assertEqual(target.read_bytes(),saved)
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(json.loads(saved)['source_sha256'],hashlib.sha256(before).hexdigest())

    def test_refresh_requires_new_cost_stage_and_markdown(self):
        import refresh_live_artifacts as refresh
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'latest_live.json').write_text('{}')
            calls=[]
            def runner(argv,**kw):
                calls.append(argv[1]);target=Path(argv[argv.index('--out')+1]);target.write_text('{}')
                return SimpleNamespace(returncode=0)
            with self.assertRaisesRegex(ValueError,'required report'):
                refresh.refresh_collection(source,root/'missing',root/'tasks.json',runner=runner)
            self.assertIn('tools/cost_attribution.py',calls)
            self.assertFalse(json.loads((root/'missing/refresh-status.json').read_text())['complete'])

    def test_frozen_confirmatory_family_preserves_both_estimands(self):
        plan=json.loads((ROOT/'bench/aci/studies/prelive-v1/analysis-plan.json').read_text())
        for base in ('raw_shell','raw_shell_coached'):
            metrics={h['metric'] for h in plan['hypotheses'] if h['baseline']==base and h['kind']=='variant'}
            self.assertTrue({'usage_token_ratio','usage_mean_of_ratios'} <= metrics)


class InputProfileTests(unittest.TestCase):
    def test_utf8_profile_is_additive_and_does_not_persist_text(self):
        payload,body,p=profile()
        self.assertTrue(valid_profile(p,hashlib.sha256(body).hexdigest()))
        self.assertNotIn('private system',json.dumps(p))
        self.assertNotIn('task',json.dumps(p))
        self.assertGreater(p['message_item_bytes_by_role']['tool'],0)
        self.assertEqual(payload['messages'][1]['content'],'task 中文')

    def test_invalid_profiles_cannot_fill_coverage(self):
        _,_,p=profile()
        for key,value in [('prepared_body_bytes',0),('tool_schema_bytes',True),('schema','other')]:
            self.assertFalse(valid_profile(dict(p,**{key:value}),p['body_sha256']))
        self.assertFalse(valid_profile(p,'other-body'))

    def test_responses_function_items_are_counted_as_history(self):
        payload={'input':[{'type':'function_call','name':'f','arguments':'{}'},
                          {'type':'function_call_output','call_id':'a','output':'value'},
                          {'type':'reasoning','summary':[]}],'tools':[]}
        body=json.dumps(payload,ensure_ascii=False).encode('utf-8');p=input_profile(payload,body)
        self.assertTrue(valid_profile(p,p['body_sha256']))
        self.assertEqual(p['message_counts_by_role']['assistant'],2)
        self.assertEqual(p['message_counts_by_role']['tool'],1)

    def test_production_cell_retains_profiles_after_json_persistence(self):
        from live_journal import atomic_json
        class Response:
            status=200;headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'choices':[{'message':{'content':'done'},'finish_reason':'stop'}],
                                              'usage':{'prompt_tokens':10,'completion_tokens':2}}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();workspace=root/'workspace';workspace.mkdir()
            self.assertTrue(workspace.resolve().is_relative_to(root))
            (workspace/'answer.txt').write_text('ok')
            task={'id':'offline-input-profile','workspace_fixture':'stubbed','prompt':'control',
                  'success':{'type':'file_equals','path':'answer.txt','equals':'ok'}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h.urllib.request,'urlopen',return_value=Response()):
                result=h.run_agent_loop(task,'raw_shell',model='offline',api_key='not-real',
                                        base_url='https://offline.invalid',max_turns=2,seed=42)
            atomic_json(root/'cell.json',result)
            stored=json.loads((root/'cell.json').read_text(encoding='utf-8'))
            self.assertTrue(stored['success'])
            attempt=stored['turn_diagnostics'][0]['transport_attempts'][0]
            self.assertTrue(valid_profile(attempt['input_profile'],attempt['request_body_sha256']))
            self.assertTrue(cost.overhead([stored])['request_input_profiles']['coverage_complete'])

    def test_real_transport_builder_body_unchanged_across_retries_and_protocols(self):
        class Response:
            status=200;headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(self.data).encode('utf-8')
        for protocol in ('chat','responses'):
            messages=[{'role':'system','content':'private 中文'}, {'role':'user','content':'task'}]
            tools=[{'type':'function','function':{'name':'f','parameters':{'type':'object'}}}]
            captured=[];resp=Response()
            resp.data=({'choices':[{'message':{'content':'done'},'finish_reason':'stop'}],
                        'usage':{'prompt_tokens':2,'completion_tokens':3}} if protocol=='chat' else
                       {'status':'completed','output':[],'usage':{'input_tokens':2,'output_tokens':3}})
            def urlopen(req,**kw):
                captured.append(req.data)
                if len(captured)==1:raise urllib.error.HTTPError('offline',500,'retry',{},io.BytesIO(b'failure'))
                return resp
            with patch.object(h.urllib.request,'urlopen',side_effect=urlopen),patch.object(h.time,'sleep'):
                result=h.chat_completion(messages,tools,model='offline',api_key='not-a-real-key',
                    base_url='https://offline.invalid/v1'+('/responses' if protocol=='responses' else ''),seed=42)
            self.assertEqual(captured[0],captured[1])
            expected=({'model':'offline','messages':messages,'tools':tools,'tool_choice':'auto',
                       'max_tokens':4096,'temperature':.1,'seed':42} if protocol=='chat' else
                      {'model':'offline','input':messages,'tools':[dict(tools[0]['function'],type='function',strict=False)],
                       'tool_choice':'auto','max_output_tokens':4096,'temperature':.1,'store':False})
            self.assertEqual(captured[0],json.dumps(expected,ensure_ascii=False).encode('utf-8'))
            sent=json.loads(captured[0]);self.assertNotIn('input_profile',sent)
            self.assertEqual(sent['tools'],tools if protocol=='chat' else [dict(tools[0]['function'],type='function',strict=False)])
            self.assertEqual(sent.get('messages',sent.get('input')),messages)
            for attempt in result['_transport_attempts']:
                self.assertTrue(valid_profile(attempt['input_profile'],hashlib.sha256(captured[0]).hexdigest()))
            self.assertFalse(result['_transport_attempts'][0]['usage_complete'])


class GradingIsolationTests(unittest.TestCase):
    def test_command_grader_ignores_shared_target_but_preserves_host_environment(self):
        import os
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'CARGO_TARGET_DIR':'outer-shared','PATHEXT':'.EXE','APPDATA':'host-data'}):
            with patch.object(h,'run_bounded',return_value=(0,b'',b'',False)) as run:
                self.assertTrue(h.check_success({'type':'command_exit_0','argv':['cargo','test']},Path(tmp))[0])
            env=run.call_args.kwargs['env']
            self.assertEqual(Path(env['CARGO_TARGET_DIR']),Path(tmp).resolve()/'target')
            self.assertEqual(env['PATHEXT'],'.EXE')
            self.assertEqual(env['APPDATA'],'host-data')
            self.assertEqual(os.environ['CARGO_TARGET_DIR'],'outer-shared')

    def test_semantic_grader_uses_its_own_copy_not_the_callers_target(self):
        from semantic_checks import rust_behavior
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';(source/'src').mkdir(parents=True)
            (source/'src/lib.rs').write_text('pub fn add(a:i32,b:i32)->i32 { a+b }')
            calls=[]
            def run(argv,**kw):
                calls.append(kw)
                self.assertEqual(Path(kw['env']['CARGO_TARGET_DIR']),kw['cwd'].resolve()/'target')
                self.assertNotEqual(kw['cwd'],source)
                return 0,b'test result: ok. 1 passed;',b'',False
            self.assertTrue(rust_behavior({'function':'add'},source,run)[0])
            self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
