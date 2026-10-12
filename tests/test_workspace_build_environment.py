"""The model tools and graders must not share a host-global Cargo output directory."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'bench/aci/runners')]
import live_agent_loop as h


class WorkspaceEnvironmentTests(unittest.TestCase):
    def test_raw_tools_get_local_target_and_preserve_windows_environment(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CARGO_TARGET_DIR':'shared','PATHEXT':'.EXE','APPDATA':'host'}):
            with patch.object(h,'run_bounded',return_value=(0,b'ok',b'',False)) as run:
                h.execute_shell_cmd('echo ok',tmp)
            env=run.call_args.kwargs.get('env',{})
            self.assertEqual(env.get('CARGO_TARGET_DIR'),str(Path(tmp).resolve()/'target'))
            self.assertEqual(env.get('PATHEXT'),'.EXE')
            self.assertEqual(env.get('APPDATA'),'host')
            self.assertEqual(os.environ['CARGO_TARGET_DIR'],'shared')

    def test_aci_target_is_local_without_changing_binary_or_approval(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CARGO_TARGET_DIR':'shared'}):
            with patch.object(h,'run_bounded',return_value=(0,b'{"ok":true,"data":{}}',b'',False)) as run:
                h.execute_aci_op('exec.run',{'argv':['echo','ok']},tmp)
            env=run.call_args.kwargs['env']
            self.assertEqual(env['CARGO_TARGET_DIR'],str(Path(tmp).resolve()/'target'))
            self.assertEqual(env['AETHER_WORKSPACE'],tmp)
            self.assertEqual(env['AETHER_APPROVE_ALL'],'1')
            self.assertEqual(run.call_args.args[0][0],str(h.AE))

    def test_future_completion_observation_binds_original_arguments(self):
        from live_journal import ObservationStore,load_observation
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();ws=root/'work';ws.mkdir();(ws/'answer.txt').write_text('ok')
            self.assertTrue(ws.is_relative_to(root))
            args={'success':True,'summary':'done'}
            task={'id':'ack-control','workspace_fixture':'stubbed','prompt':'control',
                  'success':{'type':'file_equals','path':'answer.txt','equals':'ok'}}
            response={'choices':[{'message':{'tool_calls':[{'id':'ack','function':{
                       'name':'task_complete','arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}],
                      'usage':{'prompt_tokens':1,'completion_tokens':1}}
            with patch.object(h,'prepare_workspace',return_value=ws),patch.object(h,'chat_completion',return_value=response):
                row=h.run_agent_loop(task,'raw_shell',model='offline',api_key='',base_url='invalid://offline',
                                     max_turns=2,observation_store=ObservationStore(root/'observations'))
            step=row['trajectory'][0];saved=load_observation(root,step['observation'])
            self.assertEqual(saved['args'],args)
            self.assertEqual(saved['args'],step['args'])

    def test_future_cell_receipt_is_configuration_not_full_environment_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Path(tmp).resolve()/'work';ws.mkdir();(ws/'answer.txt').write_text('ok')
            self.assertTrue(ws.is_relative_to(Path(tmp).resolve()))
            task={'id':'env-control','workspace_fixture':'stubbed','prompt':'control',
                  'success':{'type':'file_equals','path':'answer.txt','equals':'ok'}}
            response={'choices':[{'message':{'content':'done'},'finish_reason':'stop'}],
                      'usage':{'prompt_tokens':1,'completion_tokens':1}}
            with patch.object(h,'prepare_workspace',return_value=ws),patch.object(h,'chat_completion',return_value=response):
                row=h.run_agent_loop(task,'raw_shell',model='offline',api_key='',base_url='invalid://offline',max_turns=2)
            receipt=row['workspace_build_environment']
            self.assertEqual(receipt['cargo_target_dir'],str(ws/'target'))
            self.assertEqual(receipt['policy'],'workspace_local_default')
            self.assertFalse(receipt['full_environment_captured'])


@unittest.skipUnless(os.environ.get('ACI_TEST_AE'),'candidate binary required')
class NativeWorkspaceEnvironmentTests(unittest.TestCase):
    def execute(self,condition,workspace,argv):
        if condition!='verseshell_aci':
            text=h.execute_shell_cmd(subprocess.list2cmdline(argv),str(workspace))
            match=re.search(r'\[EXIT: (-?\d+)\]\s*$',text)
            self.assertIsNotNone(match,text[-1000:])
            return int(match.group(1)),text
        result=h.execute_aci_op('exec.run',{'argv':argv,'timeout_ms':60000},str(workspace))
        self.assertIn('data',result,result)
        visible=h.parse_aci_result(h.format_aci_result(result,compact=False))
        return result['data']['exit_code'],visible.get('stdout_text','')+visible.get('stderr_text','')

    def test_child_observes_local_target_for_all_three_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            with patch.dict(os.environ,{'CARGO_TARGET_DIR':str(root/'host-shared')}):
                for condition in ('raw_shell','raw_shell_coached','verseshell_aci'):
                    ws=root/condition;ws.mkdir()
                    code,text=self.execute(condition,ws,[sys.executable,'-c','import os; print(os.environ.get("CARGO_TARGET_DIR"))'])
                    self.assertEqual(code,0,text)
                    self.assertIn(str(ws/'target').replace('\\','/'),text.replace('\\','/'))

    def test_pristine_and_golden_do_not_borrow_each_others_binaries(self):
        import task_set_audit as audit
        _,tasks=audit.load_versioned_tasks(audit.TASKS,ROOT/'bench/aci/task_sets/3.1.0.json')
        task=tasks['rust_config_parse_port_d6111a63']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            with patch.dict(os.environ,{'CARGO_TARGET_DIR':str(root/'host-shared')}):
                for condition in ('raw_shell','raw_shell_coached','verseshell_aci'):
                    for golden in (False,True):
                        ws=root/(condition+('-golden' if golden else '-pristine'))
                        self.assertTrue(ws.resolve().is_relative_to(root))
                        self.assertFalse(ws.exists())
                        audit.make_workspace(audit.FIXTURES/task['workspace_fixture'],ws,golden=golden)
                        code,text=self.execute(condition,ws,['cargo','test','--offline'])
                        self.assertEqual(code==0,golden,text[-2000:])


if __name__=='__main__':unittest.main()
