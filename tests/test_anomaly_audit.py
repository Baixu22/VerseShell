"""No endpoint calls or historical command execution; synthetic observation files only."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'bench/aci/runners')]
import anomaly_audit as audit
from live_journal import ObservationStore


def row(cell,**updates):
    return dict(cell_id=cell,task_id=cell,model='offline',condition='raw_shell',prompt_variant='baseline',seed=42,
                run_index=0,success=True,success_reason='recorded predicate',turns=1,completion_truncated_turns=0,
                stop_reason='model_stopped',llm_prompt_tokens=2,llm_completion_tokens=1,usage_complete=True,
                trajectory=[],turn_diagnostics=[{'turn':1,'tool_call_count':0,'finish_reason':'stop',
                                                 'prompt_tokens':2,'completion_tokens':1,'completion_truncated':False}],**updates)


class AnomalyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=ObservationStore(self.root/'observations')
        self.config={'max_turns':3,'max_tokens':100}

    def observe(self,r,text='output\n[EXIT: 0]',args=None,envelope=None):
        args=args or {'command':'echo output'}
        ref=self.store.save(text,cell_id=r['cell_id'],op='run_command',args=args,envelope=envelope)
        r['trajectory'].append({'op':'run_command','args':args,'observation':ref})
        r['turn_diagnostics'][0]['tool_call_count']+=1
        return ref

    def analyse(self,rows,tasks=None):
        return audit.analyse({'rows':rows,'live_config':self.config},tasks or {r['task_id']:{'lang':'python'} for r in rows},self.root)

    def test_union_does_not_double_count_and_successes_are_controls(self):
        a=row('both');a.update(success=False,turns=3,stop_reason='turn_limit',llm_prompt_tokens=6,llm_completion_tokens=3)
        a['turn_diagnostics']=[dict(a['turn_diagnostics'][0],turn=i) for i in (1,2,3)]
        b=row('cost');b['usage_complete']=False
        c=row('healthy')
        report=self.analyse([a,b,c]);s=report['summary']
        self.assertEqual((s['recorded_scoring_failures'],s['cap_truncated'],s['usage_gaps'],s['primary_anomaly_union']),(1,1,1,2))
        self.assertEqual(s['successful_controls'],1)
        self.assertEqual(s['audited_rows'],3)
        self.assertEqual(s['failure_cap_intersection'],1)
        self.assertFalse(report['claimable'])
        self.assertTrue(report['cells'][0]['recorded_mechanisms'])
        self.assertEqual(report['cells'][0]['underlying_task_cause']['status'],'unknown')

    def test_verified_repetition_is_not_a_root_cause(self):
        r=row('repeat')
        for _ in range(3):self.observe(r)
        c=self.analyse([r])['cells'][0]
        self.assertEqual(c['observations']['verified'],3)
        self.assertEqual(c['observations']['longest_identical_call_streak'],3)
        self.assertEqual(c['observations']['max_identical_recorded_calls'],3)
        self.assertIn('repeated_recorded_call',c['domain_evidence']['model_actions'])
        self.assertEqual(c['observations']['max_identical_visible_observations'],3)
        self.assertEqual(c['underlying_task_cause']['status'],'unknown')

    def test_hash_failure_preserves_other_observations_and_original_score(self):
        r=row('damaged');ref=self.observe(r);self.observe(r,'different\n[EXIT: 0]')
        (self.root/ref['path']).write_text('{}')
        c=self.analyse([r])['cells'][0]
        self.assertEqual(c['observations']['verified'],1)
        self.assertFalse(c['observations']['complete'])
        self.assertTrue(c['recorded_scoring']['success'])
        self.assertEqual(c['recorded_scoring']['independent_rescore'],'not_run')

    def test_path_escape_is_rejected_without_reading_foreign_file(self):
        r=row('path');self.observe(r)
        r['trajectory'][0]['observation']['path']='../outside.json'
        c=self.analyse([r])['cells'][0]
        self.assertIn('leaves artifact',c['observations']['errors'][0]['reason'])

    def test_cell_operation_and_argument_binding_are_checked(self):
        for field,value in [('cell_id','wrong'),('op','wrong'),('args',{'command':'different'})]:
            r=row(field);ref=self.observe(r)
            old=json.loads((self.root/ref['path']).read_text())
            metadata={k:old[k] for k in ('cell_id','op','args')};metadata[field]=value
            r['trajectory'][0]['observation']=self.store.save(old['text'],**metadata)
            c=self.analyse([r])['cells'][0]
            self.assertFalse(c['observations']['complete'])

    def test_malformed_turns_and_huge_counts_are_unknown_not_memory_allocation(self):
        for value in (None,'bad',12,[{'turn':1,'tool_call_count':10**12}]):
            r=row('malformed');self.observe(r);r['turn_diagnostics']=value
            c=self.analyse([r])['cells'][0]
            self.assertEqual(c['observations']['call_turn_alignment'],'unknown')
            self.assertEqual(c['underlying_task_cause']['status'],'unknown')

    def test_exit_zero_test_marker_does_not_prove_task_completion(self):
        r=row('markers');r['success']=False
        self.observe(r,'3 passed in 0.2s\n[EXIT: 0]',{'command':'python -m pytest'})
        self.observe(r,'next\n[EXIT: 0]',{'command':'echo next'})
        c=self.analyse([r])['cells'][0]
        self.assertEqual(c['observations']['calls_after_test_success_marker'],1)
        self.assertFalse(c['recorded_scoring']['success'])
        self.assertEqual(c['underlying_task_cause']['status'],'unknown')

    def test_legacy_ack_is_hash_verified_without_fabricating_argument_binding(self):
        r=row('ack');r['success']=False
        reference=self.store.save(json.dumps({'ok':True,'acknowledged':True}),cell_id='ack',op='task_complete')
        r['trajectory']=[{'op':'task_complete','args':{'success':False},'observation':reference}]
        r['turn_diagnostics'][0]['tool_call_count']=1
        report=self.analyse([r]);c=report['cells'][0]
        self.assertEqual(c['observations']['verified'],1)
        self.assertEqual(report['summary']['legacy_ack_argument_gaps'],1)
        self.assertEqual(report['summary']['argument_bindings_not_verified'],1)
        self.assertFalse(c['recorded_scoring']['success'])

    def test_invalid_ack_does_not_escape_argument_validation(self):
        r=row('ack')
        reference=self.store.save(json.dumps({'ok':1,'acknowledged':True}),cell_id='ack',op='task_complete')
        r['trajectory']=[{'op':'task_complete','args':{'success':True},'observation':reference}]
        r['turn_diagnostics'][0]['tool_call_count']=1
        self.assertFalse(self.analyse([r])['cells'][0]['observations']['complete'])

    def test_nonterminal_exit_text_is_not_an_execution_result(self):
        r=row('marker-text');self.observe(r,'[EXIT: 0] quoted in a document')
        record=self.analyse([r])['cells'][0]['observations']['records'][0]
        self.assertIsNone(record['exit_code'])

    def test_platform_and_encoding_markers_are_observations_only(self):
        r=row('platform');self.observe(r,"foo is not recognized as an internal or external command \ufffd\n[EXIT: 1]")
        c=self.analyse([r])['cells'][0]
        self.assertIn('shell_syntax_or_command_lookup_diagnostic',c['observations']['signals'])
        self.assertIn('replacement_character_present',c['observations']['signals'])
        self.assertIn('replacement_character_present',c['domain_evidence']['platform_interface'])
        self.assertEqual(c['domain_evidence']['scoring'],[])
        self.assertEqual(c['underlying_task_cause']['status'],'unknown')

    def test_unknown_attempts_are_identified_without_billing_imputation(self):
        r=row('retry');t=r['turn_diagnostics'][0]
        t['transport_attempts']=[{'attempt':1,'status':502,'error':'unknown'}, {'attempt':2,'status':200}]
        c=self.analyse([r])['cells'][0]
        self.assertIn('usage_gap',c['membership'])
        self.assertEqual(len(c['usage']['unknown_attempts']),1)
        self.assertEqual(c['usage']['unknown_attempts'][0]['status'],502)
        self.assertTrue(c['recorded_scoring']['success'])

    def test_missing_environment_and_snapshot_stay_unknown(self):
        r=row('rust');c=self.analyse([r],{'rust':{'lang':'rust'}})['cells'][0]
        self.assertFalse(c['blind_spots']['build_environment_receipt_present'])
        self.assertFalse(c['blind_spots']['final_workspace_reference_present'])
        self.assertEqual(c['blind_spots']['historical_shared_cargo_target_inheritance'],'unknown')
        r['workspace_build_environment']={'policy':'workspace_local_default'}
        c=self.analyse([r])['cells'][0]
        self.assertTrue(c['blind_spots']['build_environment_receipt_present'])
        self.assertFalse(c['blind_spots']['build_environment_runtime_verified'])

    def test_groups_are_partitioned_and_language_is_not_guessed(self):
        a=row('rust_named_but_unknown');b=row('other');b.update(seed=43,prompt_variant='compact_all',condition='verseshell_aci')
        report=self.analyse([a,b],{'other':{'lang':'typescript'}})
        self.assertEqual(report['summary']['unknown_language_rows'],1)
        for axis,groups in report['groups'].items():self.assertEqual(sum(g['rows'] for g in groups),2,axis)
        selected=audit.analyse({'rows':[a,b],'live_config':self.config},{},self.root,'compact_all')
        self.assertEqual(selected['summary']['selected_rows'],1)

    def test_bad_identity_and_missing_caps_fail_closed(self):
        r=row('same')
        with self.assertRaisesRegex(ValueError,'identity'):self.analyse([r,copy.deepcopy(r)])
        with self.assertRaisesRegex(ValueError,'max_turns'):audit.analyse({'rows':[r]}, {}, self.root)

    def test_inspection_never_executes_commands_or_changes_source_bytes(self):
        r=row('untrusted');ref=self.observe(r,args={'command':'do-not-execute-this'})
        before=(self.root/ref['path']).read_bytes();original=copy.deepcopy(r)
        with patch('subprocess.run',side_effect=AssertionError('must not execute')),patch('subprocess.Popen',side_effect=AssertionError('must not execute')):
            self.analyse([r])
        self.assertEqual(r,original)
        self.assertEqual((self.root/ref['path']).read_bytes(),before)

    def test_cli_refuses_existing_or_raw_directory_outputs(self):
        source=self.root/'source.json';source.write_text('{}')
        with patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(audit.main(['--with-arm',str(source),'--task-set','unused','--out',str(self.root/'report.json')]),2)
        self.assertFalse((self.root/'report.json').exists())


if __name__=='__main__':unittest.main()
