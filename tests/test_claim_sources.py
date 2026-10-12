"""TF-0140: real input routes, conservative current-status labels and preserved thresholds."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import claim_sources as sources
import claim_gate as gate
import readme_claims_check as readme


def compact(value=.42,byte=.50):
    return {'families':[{'kind':'response','cases':[{'name':'response_small_hash','byte_savings':byte,'token_savings':value}]},
                        {'kind':'observation','cases':[{'roundtrip_ok':True}]}]}


class ClaimSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'eval').mkdir();(self.root/'code.txt').write_text('source')

    def test_defaults_and_explicit_paths_are_resolved_without_copying(self):
        source=self.root/'external.json';source.write_text('{}')
        selected,explicit=sources.selected_paths(self.root,SimpleNamespace(metrics=source),['eval/example.json'])
        self.assertEqual(selected['eval/metrics.json'],source.resolve())
        self.assertEqual(selected['eval/example.json'],self.root/'eval/example.json')
        self.assertEqual(explicit,{'eval/metrics.json'})
        self.assertFalse((self.root/'eval/metrics.json').exists())

    def test_map_relative_paths_are_relative_to_map_and_unknown_keys_fail(self):
        folder=self.root/'maps';folder.mkdir();p=folder/'inputs.json'
        p.write_text(json.dumps({'schema':'verseshell.claim-input-map/v1','artifacts':{'eval/example.json':'../external.json'}}))
        selected,_=sources.selected_paths(self.root,SimpleNamespace(artifact_map=p),['eval/example.json'])
        self.assertEqual(selected['eval/example.json'],self.root/'external.json')
        p.write_text(json.dumps({'schema':'verseshell.claim-input-map/v1','artifacts':{'tools/claim_gate.py':'payload.py'}}))
        with self.assertRaisesRegex(ValueError,'unknown'):sources.selected_paths(self.root,SimpleNamespace(artifact_map=p),[])

    def test_conflicting_cli_or_duplicate_normalized_paths_are_rejected(self):
        p=self.root/'inputs.json'
        for entries,kwargs in [({'eval/metrics.json':'one.json'},{'metrics':self.root/'two.json'}),
                               ({'eval/metrics.json':'one.json','eval\\metrics.json':'one.json'}, {})]:
            p.write_text(json.dumps({'schema':'verseshell.claim-input-map/v1','artifacts':entries}))
            with self.assertRaises(ValueError):sources.selected_paths(self.root,SimpleNamespace(artifact_map=p,**kwargs),[])

    def test_freshness_reads_selected_file_not_stale_canonical(self):
        canonical=self.root/'eval/projection_contract.json';canonical.write_text('{}')
        selected=self.root/'new.json'
        with patch.object(gate,'ROOT',self.root),patch.object(gate,'EVIDENCE_ARTIFACTS',['eval/projection_contract.json']):
            fp=gate.evidence_fingerprint(['code.txt'])
            selected.write_text(json.dumps({'evidence':{'globs':['code.txt'],'fingerprint':fp}}))
            result=gate.freshness_entries({'eval/projection_contract.json':selected})[0]
            self.assertTrue(result['pass'])
            self.assertEqual(result['selected_path'],str(selected))
            self.assertFalse(gate.freshness_entries()[0]['pass'])
        self.assertEqual(canonical.read_text(),'{}')

    def test_declared_old_input_hash_cannot_certify_different_selected_input(self):
        old=self.root/'eval/raw.json';old.write_text('old');new=self.root/'new.json';new.write_text('new')
        ev={'input_sha256':{'eval/raw.json':hashlib.sha256(old.read_bytes()).hexdigest()}}
        with patch.object(gate,'ROOT',self.root):
            self.assertEqual(gate.verify_input_hashes(ev),[])
            result=gate.verify_input_hashes(ev,selected={'eval/raw.json':new})
        self.assertIn('differs from selected',result[0])

    def test_source_or_consumed_input_mutation_demotes_c12(self):
        for before,after,ib,ia in [({'a':'1'},{'a':'2'},{'x':'1'},{'x':'1'}),
                                   ({'a':'1'},{'a':'1'},{'x':'1'},{'x':'2'})]:
            c=[{'id':'C12','value':1,'pass':True,'detail':{},'notes':'freshness'}]
            state=sources.apply_stability_guard(c,before,after,ib,ia)
            self.assertFalse(state['stable']);self.assertFalse(c[0]['pass'])
            self.assertEqual(c[0]['value'],0)

    def test_unverified_passing_measurement_cannot_leave_c12_green(self):
        claims=[{'id':'C12','pass':True,'value':1,'notes':'freshness','detail':{}}]
        inventory={'claims':[{'id':'C3','gated':True,'gate_pass':True,'status':'unverified'},
                             {'id':'C12','gated':True,'gate_pass':True,'status':'verified_current_check'}]}
        sources.require_current_evidence(claims,inventory)
        self.assertFalse(claims[0]['pass'])
        self.assertEqual(inventory['current_binding_missing_for'],['C3'])
        self.assertEqual(inventory['claims'][1]['status'],'not_met')

    def test_generated_outputs_are_not_treated_as_mutated_inputs(self):
        c=[{'id':'C12','value':1,'pass':True,'detail':{},'notes':'freshness'}]
        state=sources.apply_stability_guard(c,{'a':'1'},{'a':'1'},{'x':None},{'x':'2'},generated={'x':{'sha256':'2'}})
        self.assertTrue(state['stable']);self.assertTrue(c[0]['pass'])
        state=sources.apply_stability_guard(c,{'a':'1'},{'a':'1'},{'x':None},{'x':'3'},generated={'x':{'sha256':'2'}})
        self.assertFalse(state['stable']);self.assertFalse(c[0]['pass'])

    def inventory(self,claim,fresh=True,stable=True,generated=None):
        p=self.root/'measurement.json';p.write_text(json.dumps({'schema':'control/v1','task_set_version':'v3','git_rev':'old'}))
        registry={claim['id']:{'gated':True,'caliber':'controlled'}}
        return sources.build_inventory([claim],registry,{'eval/probe.json':p},
            [{'artifact':'eval/probe.json','pass':fresh}],
            {'stable':stable,'selected_input_sha256':{'eval/probe.json':hashlib.sha256(p.read_bytes()).hexdigest()}},
            generated or {},self.root)

    def test_historical_threshold_pass_is_not_current_verification(self):
        c={'id':'C9','pass':True,'threshold':'>=.4','value':.42,'mode':'deterministic','source':['eval/probe.json']}
        report=self.inventory(c,fresh=False)
        self.assertEqual(report['claims'][0]['status'],'historical_only')
        self.assertTrue(report['claims'][0]['gate_pass'])
        self.assertEqual(c['threshold'],'>=.4');self.assertEqual(c['value'],.42)
        self.assertEqual(c['source'],[str(self.root/'measurement.json')])
        self.assertEqual(report['artifacts']['eval/probe.json']['version']['git_rev'],'old')

    def test_fresh_selected_measurement_can_be_verified_but_not_a_formal_effect(self):
        c={'id':'C9','pass':True,'mode':'deterministic','source':['eval/probe.json']}
        report=self.inventory(c)
        self.assertEqual(report['claims'][0]['status'],'verified_selected_measurement')
        self.assertEqual(report['research_boundary']['formal_effect_verdict'],'not_granted_by_this_inventory')

    def test_nonempty_current_tests_are_distinct_from_zero_or_skipped_tests(self):
        for count,status in [(1,'verified_current_check'),(0,'unverified')]:
            c={'id':'C7','pass':True,'mode':'cargo_test','source':[],'exit_code':0,'test_totals':{'passed':count}}
            self.assertEqual(self.inventory(c)['claims'][0]['status'],status)
        c={'id':'C7','pass':True,'mode':'cargo_test','source':[],'exit_code':0,'test_totals':{'passed':1}}
        self.assertEqual(self.inventory(c,stable=False)['claims'][0]['status'],'unverified')

    def test_failed_predicate_stays_failed_even_if_input_is_fresh(self):
        c={'id':'C16','pass':False,'value':.08,'mode':'deterministic','source':['eval/probe.json']}
        self.assertEqual(self.inventory(c)['claims'][0]['status'],'not_met')

    def test_non_gated_declarations_are_included_without_creating_passes(self):
        registry={'C13':{'gated':False,'caliber':'endpoint_usage','source':['eval/probe.json'],'note':'diagnostic'}}
        report=sources.build_inventory([],registry,{},[],{'stable':True,'selected_input_sha256':{}},{},self.root)
        self.assertEqual(report['claims'][0]['status'],'diagnostic_only')
        self.assertIsNone(report['claims'][0]['gate_pass'])

    def test_replay_version_requires_actual_newer_bound_data_not_a_new_label(self):
        source=self.root/'live.json'
        def data(version='3.0.0'):
            source.write_text(json.dumps({'task_set_version':version,'rows':[{'task_id':'one'}]}))
            return {'source_identity':{'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'task_set_version':version}}
        report=data();freeze={'task_set_version':'3.0.0','tasks':['one']}
        self.assertTrue(gate.replay_source_binding(report,freeze,source)['pass'])
        self.assertFalse(gate.replay_source_binding({},freeze,source)['pass'])
        self.assertFalse(gate.replay_source_binding(report,dict(freeze,tasks=['other']),source)['pass'])
        for version in ('1.0.0','2.0.0','arbitrary-new-label'):
            report=data(version)
            self.assertFalse(gate.replay_source_binding(report,{'task_set_version':version,'tasks':['one']},source)['pass'])
        report=data();report['source_identity']['sha256']='0'*64
        self.assertFalse(gate.replay_source_binding(report,freeze,source)['pass'])

    def test_replay_uses_selected_binary_and_managed_process_contract(self):
        import tf45_envelope_replay as replay
        binary=self.root/'candidate.exe'
        with patch.object(replay,'AE',binary),patch.object(replay,'run_bounded',return_value=(0,b'{"ok":true}',b'',False)) as run:
            self.assertTrue(replay.run_op('file.view',{'path':'sample'},self.root)['ok'])
            self.assertEqual(run.call_args.args[0][0],str(binary))
            self.assertEqual(run.call_args.kwargs['env']['AETHER_WORKSPACE'],str(self.root))
        with patch.object(replay,'run_bounded',return_value=(None,b'',b'',True)):
            with self.assertRaises(TimeoutError):replay.run_op('file.view',{},self.root)

    def test_registry_preserves_all_37_ids_and_31_thresholds(self):
        self.assertEqual(set(gate.TOKEN_CALIBER)|set(gate.THRESHOLDS),{'C'+str(i) for i in range(1,38)})
        self.assertEqual(len(gate.THRESHOLDS),31)
        self.assertEqual(gate.THRESHOLDS['C14']['value'],.15)
        self.assertEqual(gate.THRESHOLDS['C16']['value'],.10)
        self.assertEqual(gate.THRESHOLDS['C34']['value'],.40)
        claims=[{'id':cid,'pass':False,'source':[]} for cid in gate.THRESHOLDS]
        inventory=sources.build_inventory(claims,gate.TOKEN_CALIBER,{},[],{'stable':True,'selected_input_sha256':{}},{},self.root)
        self.assertEqual(len(inventory['claims']),37)
        self.assertEqual(sum(c['gated'] for c in inventory['claims']),31)


class ReadmeInputTests(unittest.TestCase):
    def test_compact_percentage_uses_the_conservative_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'compact.json';p.write_text(json.dumps(compact()))
            self.assertTrue(readme.check_compact_encoding('measured 42.0% gated saving',p)[0]['pass'])
            self.assertFalse(readme.check_compact_encoding('measured 50.0% gated saving',p)[0]['pass'])
            p.write_text(json.dumps(compact(value=.1)))
            self.assertFalse(readme.check_compact_encoding('measured 10.0% gated saving; >=40%',p)[0]['pass'])

    def test_cross_shell_override_is_the_input_used_for_readme_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cross.json'
            p.write_text(json.dumps({'operations':[{'name':'check','shells':{'ae':{'median_ms':2},'pwsh':{'median_ms':4},'bash':{'median_ms':None}}}]}))
            text='| check | **2ms** | 4ms | N/A | **2.0x faster** |'
            result=readme.check_cross_shell(text,p)
            self.assertTrue(result[0]['pass']);self.assertIn(str(p),result[0]['source'])
            self.assertFalse(readme.check_cross_shell('old table',p)[0]['pass'])


if __name__=='__main__':unittest.main()
