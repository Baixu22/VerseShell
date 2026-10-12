import contextlib,copy,io,json,os,subprocess,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'bench/aci/runners'),str(ROOT/'tools')]
import live_agent_loop as h
from live_journal import RunStatus,ObservationStore,atomic_text,load_observation,read_status
from live_uncertainty import reported_usage,ratio_bootstrap
from replay_observations import replay


class RecoveryTests(unittest.TestCase):
    def invoke(self,args,response):
        output=io.StringIO()
        with patch.object(h,'run_agent_loop',side_effect=response) as model,contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            code=h.main(args)
        self.last_output=output.getvalue()
        return code,model.call_count

    @staticmethod
    def row(task,condition,status=None,**kwargs):
        return dict(task_id=task['id'],condition=condition,model='offline',run_index=0,success=status is None,
                    success_reason='offline control',tool_calls=0,observation_tokens=0,elapsed_ms=1,turns=1,
                    trajectory=[],api_error=status is not None,endpoint_status=status,last_error=None)

    def test_auth_quota_pause_and_resume_without_replaying_completed_cells(self):
        for status in (401,402,403):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'run.json'
                args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error,rust_add_unit_test',
                      '--conditions','raw_shell','--seed','42','--out',str(out)]
                code,calls=self.invoke(args,lambda task,condition,**kw:self.row(task,condition,status=status))
                self.assertEqual((code,calls),(75,1))
                self.assertEqual(read_status(str(out)+'.status.json')['state'],'paused')
                self.assertEqual(self.invoke(args,self.row),(75,0))
                result=self.invoke([*args,'--resume-paused'],self.row)
                self.assertEqual(result,(0,1),self.last_output)
                data=json.loads(out.read_text(encoding='utf-8'))
                self.assertEqual(len(data['rows']),2)
                self.assertTrue(data['rows'][0]['api_error'])
                self.assertEqual(self.invoke(args,self.row),(0,0))
                history=json.loads(Path(str(out)+'.attempts.json').read_text(encoding='utf-8'))
                self.assertEqual(len(history['attempts']),2)

    def test_storage_pause_at_cell_boundary_and_explicit_same_identity_resume(self):
        import live_storage
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json'; low=[False]
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error,rust_add_unit_test',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            def row(task,condition,**kwargs):
                low[0]=True
                return self.row(task,condition,**kwargs)
            with patch.dict(os.environ,ACI_STORAGE_RESERVES=json.dumps({str(Path(tmp).resolve()):10})), \
                 patch.object(live_storage.shutil,'disk_usage',side_effect=lambda p:type('Disk',(),{'free':9 if low[0] else 10})()):
                self.assertEqual(self.invoke(args,row),(75,1))
                checkpoint=Path(str(out)+'.rows.jsonl')
                original=checkpoint.read_bytes()
                self.assertTrue((Path(tmp)/'STOP').exists())
                self.assertEqual(json.loads(Path(str(out)+'.pause.json').read_text())['reason'],'storage_reserve')
                self.assertEqual(self.invoke([*args,'--resume-paused'],self.row),(75,0))
                low[0]=False
                self.assertEqual(self.invoke([*args,'--resume-paused'],self.row),(75,0))
                self.assertEqual(checkpoint.read_bytes(),original)
                (Path(tmp)/'STOP').rename(Path(tmp)/'STOP.acknowledged-offline')
                self.assertEqual(self.invoke([*args,'--resume-paused'],self.row),(0,1),self.last_output)
                rows=json.loads(out.read_text())['rows']
                self.assertEqual(len(rows),2)
                self.assertEqual(len({r['cell_id'] for r in rows}),2)
                self.assertEqual(self.invoke(args,self.row),(0,0))

    def test_collection_stop_marker_reaches_runner_without_guessing_shard_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'arbitrary-shard-name.json'
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error,rust_add_unit_test',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            def row(task,condition,**kwargs):
                (Path(tmp)/'STOP').write_text('offline stop')
                return self.row(task,condition,**kwargs)
            self.assertEqual(self.invoke(args,row),(75,1))
            self.assertEqual(self.invoke(args,self.row),(75,0))
            self.assertTrue((Path(tmp)/'STOP').exists())
            self.assertFalse(out.exists())

    def test_checkpoint_write_failure_preserves_committed_row_and_stops_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json'; checkpoint=Path(str(out)+'.rows.jsonl'); writes=[0]
            args=['--model','offline','--api-key','test',
                  '--tasks','rust_fix_compile_error,rust_add_unit_test,rust_search_and_edit',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            real_write=h.atomic_text
            def write(path,text):
                if Path(path)==checkpoint:
                    writes[0]+=1
                    if writes[0]==3:
                        raise OSError(28,'injected full disk before replacing checkpoint')
                return real_write(path,text)
            with patch.object(h,'atomic_text',side_effect=write), patch.object(h,'run_agent_loop',side_effect=self.row) as model, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(OSError):h.main(args)
            self.assertEqual(model.call_count,2)
            entries=[json.loads(line) for line in checkpoint.read_text().splitlines()]
            self.assertEqual(len(entries),2)  # identity plus the first committed row
            self.assertFalse(out.exists())
            self.assertEqual(read_status(str(out)+'.status.json')['state'],'failed')
            self.assertEqual(self.invoke(args,self.row),(75,0))

    def test_sustained_write_failure_stays_failed_and_never_dispatches_more(self):
        # A disk that stays full must never yield a success artifact and must not
        # dispatch further cells. Diagnostics may be unwritable; when they are, the
        # run stays failed rather than claiming the current cell is recoverable.
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json'; checkpoint=Path(str(out)+'.rows.jsonl'); writes=[0]
            args=['--model','offline','--api-key','test',
                  '--tasks','rust_fix_compile_error,rust_add_unit_test,rust_search_and_edit',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            real_write=h.atomic_text
            def write(path,text):
                if Path(path)==checkpoint:
                    writes[0]+=1
                    if writes[0]>=3:
                        raise OSError(28,'injected persistent full disk')
                return real_write(path,text)
            attempted=[]
            def model(task,condition,**kwargs):
                attempted.append(task['id'])
                return self.row(task,condition)
            with patch.object(h,'atomic_text',side_effect=write), patch.object(h,'run_agent_loop',side_effect=model), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(OSError):
                    h.main(args)
                self.assertFalse(out.exists())
                self.assertEqual(read_status(str(out)+'.status.json')['state'],'failed')
                # Same persistent fault on an explicit resume still must not claim success.
                with self.assertRaises(OSError):
                    h.main([*args,'--resume-paused'])
            self.assertNotIn('rust_search_and_edit',attempted)
            self.assertEqual(attempted[0],'rust_fix_compile_error')
            self.assertFalse(out.exists())
            entries=[json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(entries),2)  # identity header plus the one committed row
            self.assertIn('_config',entries[0])
            self.assertEqual(entries[1]['task_id'],'rust_fix_compile_error')

    def test_three_failed_cells_open_circuit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json'
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error,rust_add_unit_test,rust_search_and_edit,python_fix_pytest_fail',
                  '--conditions','raw_shell','--seed','42','--out',str(out)]
            self.assertEqual(self.invoke(args,lambda t,c,**kw:self.row(t,c,status=502)),(75,3))

    def test_existing_output_and_fresh_flag_never_erase_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run.json';out.write_text('historical evidence')
            args=['--model','offline','--api-key','test','--tasks','rust_fix_compile_error','--out',str(out)]
            self.assertEqual(self.invoke(args,self.row),(2,0))
            self.assertEqual(self.invoke([*args,'--fresh'],self.row),(2,0))
            self.assertEqual(self.invoke([*args,'--dry-run'],self.row),(2,0))
            self.assertEqual(out.read_text(),'historical evidence')

    def test_retry_budget_and_fatal_status(self):
        for status,attempts in [(401,1),(402,1),(403,1),(503,3),(429,3)]:
            def fail(*args,**kwargs):raise urllib.error.HTTPError('http://offline',status,'failure',{},io.BytesIO(b'error'))
            with self.subTest(status=status),patch.object(h.urllib.request,'urlopen',side_effect=fail) as request,patch.object(h.time,'sleep') as sleep:
                with self.assertRaises(RuntimeError) as caught:
                    h.chat_completion([],[],model='offline',api_key='test',base_url='http://offline')
                self.assertEqual(request.call_count,attempts)
                self.assertEqual(len(caught.exception.attempts),attempts)
                self.assertEqual(sleep.call_count,attempts-1)

    def test_atomic_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'checkpoint';out.write_text('previous')
            with patch('live_journal.os.replace',side_effect=OSError('interrupted write')):
                with self.assertRaises(OSError):atomic_text(out,'replacement')
            self.assertEqual(out.read_text(),'previous')

    def test_status_records_explicit_abnormal_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'status.json'
            with self.assertRaises(SystemExit):
                with RunStatus(out):raise SystemExit(7)
            self.assertEqual(read_status(out)['exit_code'],7)
            self.assertEqual(read_status(out)['state'],'failed')

    def test_killed_owner_is_not_running_and_lock_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'status.json'
            code="import sys,time;sys.path.insert(0,sys.argv[1]);from live_journal import RunStatus\nwith RunStatus(sys.argv[2]):\n print('ready',flush=True)\n time.sleep(60)"
            process=subprocess.Popen([(getattr(sys,'_base_executable',None) or sys.executable),'-B','-c',code,str(ROOT/'bench/aci/runners'),str(out)],stdout=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                self.assertEqual(process.stdout.readline().strip(),b'ready')
                process.kill();process.wait(timeout=10)
                self.assertEqual(read_status(out)['state'],'interrupted')
                with RunStatus(out) as owner:owner.update(state='completed')
                self.assertEqual(read_status(out)['state'],'completed')
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()

    def test_generated_read_observations_replay_and_equal_length_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=ObservationStore(root/'observations');steps=[]
            for text in ('before','after!'):
                env={'ok':True,'data':{'hash':'a'*16,'content_hash':'sha256:'+'a'*64,'total_lines':1,'lines':[{'line':1,'text':text}]}}
                ref=store.save(h.format_aci_result(env),envelope=env,op='file.view')
                steps.append({'op':'file.view','observation':ref})
            data=root/'run.json';data.write_text(json.dumps({'rows':[{'task_id':'generated','trajectory':steps}]}),encoding='utf-8')
            self.assertTrue(replay(data)['exact_replay_ok'])
            target=root/steps[0]['observation']['path'];body=target.read_text(encoding='utf-8')
            target.write_text(body.replace('before','forged'),encoding='utf-8')
            self.assertFalse(replay(data)['exact_replay_ok'])

    def test_observation_secrets_are_redacted_and_not_claimed_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=ObservationStore(root/'observations',('my-private-key',))
            ref=store.save('my-private-key',envelope={'accessToken':'other-private-token'})
            data=load_observation(root,ref)
            self.assertTrue(data['redacted']);self.assertNotIn('my-private-key',json.dumps(data))
            self.assertNotIn('other-private-token',json.dumps(data))

    def test_missing_usage_is_excluded_not_zero_filled(self):
        unknown={'llm_prompt_tokens':None,'llm_completion_tokens':None,'usage_complete':False}
        ratio=ratio_bootstrap([(10,20),(reported_usage(unknown),0)],kind='usage',keys=['a','b'],iterations=100)
        self.assertEqual(ratio['n_pairs'],1);self.assertEqual(ratio['point_estimate'],2)
        self.assertEqual(ratio['excluded_nonfinite_pairs'],1)

    def test_agent_loop_records_read_write_read_and_unknown_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'work';workspace.mkdir();store=ObservationStore(root/'observations')
            def envelope(text):return {'ok':True,'data':{'hash':'a'*16,'content_hash':'sha256:'+'a'*64,'total_lines':1,'lines':[{'line':1,'text':text}]}}
            responses=[]
            for i,name in enumerate(('read_file','write_file','read_file')):
                responses.append({'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':str(i),'function':{'name':name,'arguments':'{"path":"generated.txt","content":"after!"}'}}]}}]})
            responses.append({'usage':{'prompt_tokens':'invalid','completion_tokens':None},'choices':[{'finish_reason':'stop','message':{'content':'done'}}]})
            task={'id':'offline','workspace_fixture':'offline','prompt':'Edit generated file','success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h,'check_success',return_value=(True,'offline')),patch.object(h,'chat_completion',side_effect=responses),patch.object(h,'execute_aci_op',side_effect=[envelope('before'),{'ok':True,'data':{}},envelope('after!')]):
                row=h.run_agent_loop(task,'verseshell_aci',model='offline',api_key='private-key',base_url='http://offline',observation_store=store)
            self.assertFalse(row['usage_complete']);self.assertIsNone(row['llm_prompt_tokens'])
            self.assertIsNone(row['harness_fault'])
            self.assertEqual(row['reported_llm_prompt_tokens'],30)
            self.assertEqual(row['stop_reason'],'model_stop')
            data=root/'run.json';data.write_text(json.dumps({'rows':[row]}),encoding='utf-8')
            self.assertTrue(replay(data)['exact_replay_ok'])
            self.assertEqual(replay(data)['read_calls_matched'],2)

    def test_raw_shell_observations_are_recorded_without_unbound_result_text(self):
        # Regression: the shared observation_store block reads result_text, but
        # the raw_shell branch only ever bound raw_output. Every raw_shell and
        # raw_shell_coached cell died with UnboundLocalError -> harness_error,
        # which paused the whole 3-condition round on its first cell.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'work';workspace.mkdir();store=ObservationStore(root/'observations')
            responses=[]
            for i in range(2):
                responses.append({'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':str(i),'function':{'name':'run_command','arguments':'{"command":"echo hello"}'}}]}}]})
            responses.append({'usage':{'prompt_tokens':5,'completion_tokens':1},'choices':[{'finish_reason':'stop','message':{'content':'done'}}]})
            task={'id':'offline','workspace_fixture':'offline','prompt':'Run a command','success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h,'check_success',return_value=(True,'offline')),patch.object(h,'chat_completion',side_effect=responses),patch.object(h,'execute_shell_cmd',return_value='hello'):
                row=h.run_agent_loop(task,'raw_shell',model='offline',api_key='private-key',base_url='http://offline',observation_store=store)
            self.assertIsNone(row['harness_fault'])
            self.assertEqual(row['stop_reason'],'model_stop')
            self.assertEqual([s['op'] for s in row['trajectory']],['run_command','run_command'])
            for step in row['trajectory']:
                self.assertIn('observation',step)

    def test_unknown_tool_branch_records_an_observation_instead_of_aborting(self):
        # Sibling of the raw_shell regression: this branch also writes through
        # the shared observation_store block and had never been executed.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'work';workspace.mkdir();store=ObservationStore(root/'observations')
            responses=[{'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'0','function':{'name':'no_such_tool','arguments':'{}'}}]}}]},
                       {'usage':{'prompt_tokens':5,'completion_tokens':1},'choices':[{'finish_reason':'stop','message':{'content':'done'}}]}]
            task={'id':'offline','workspace_fixture':'offline','prompt':'x','success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h,'check_success',return_value=(True,'offline')),patch.object(h,'chat_completion',side_effect=responses):
                row=h.run_agent_loop(task,'verseshell_aci',model='offline',api_key='private-key',base_url='http://offline',observation_store=store)
            self.assertIsNone(row['harness_fault'])
            self.assertEqual(row['stop_reason'],'model_stop')
            self.assertEqual(row['trajectory'][0]['op'],'no_such_tool')
            self.assertIn('observation',row['trajectory'][0])

    def test_task_complete_branch_records_an_observation_and_stops(self):
        # Second sibling branch: also writes through the shared block.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'work';workspace.mkdir();store=ObservationStore(root/'observations')
            responses=[{'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'0','function':{'name':'task_complete','arguments':'{"success":true,"summary":"ok"}'}}]}}]}]
            task={'id':'offline','workspace_fixture':'offline','prompt':'x','success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h,'check_success',return_value=(True,'offline')),patch.object(h,'chat_completion',side_effect=responses):
                row=h.run_agent_loop(task,'verseshell_aci',model='offline',api_key='private-key',base_url='http://offline',observation_store=store)
            self.assertIsNone(row['harness_fault'])
            self.assertEqual(row['stop_reason'],'task_complete')
            self.assertEqual(row['trajectory'][0]['op'],'task_complete')
            self.assertIn('observation',row['trajectory'][0])

    def test_malformed_tool_arguments_do_not_abort_the_loop(self):
        # Third sibling branch: json.loads failure must degrade to {} rather
        # than propagate out of the loop.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'work';workspace.mkdir();store=ObservationStore(root/'observations')
            responses=[{'usage':{'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'0','function':{'name':'run_command','arguments':'{not valid json'}}]}}]},
                       {'usage':{'prompt_tokens':5,'completion_tokens':1},'choices':[{'finish_reason':'stop','message':{'content':'done'}}]}]
            task={'id':'offline','workspace_fixture':'offline','prompt':'x','success':{}}
            with patch.object(h,'prepare_workspace',return_value=workspace),patch.object(h,'check_success',return_value=(True,'offline')),patch.object(h,'chat_completion',side_effect=responses),patch.object(h,'execute_shell_cmd',return_value='')\
                    as shell:
                row=h.run_agent_loop(task,'raw_shell',model='offline',api_key='private-key',base_url='http://offline',observation_store=store)
            self.assertIsNone(row['harness_fault'])
            self.assertEqual(row['stop_reason'],'model_stop')
            # Unparseable arguments must degrade to {} rather than raise, so the
            # command seen by the shell is the empty default.
            shell.assert_called_once_with('',str(workspace),capture={})
            self.assertEqual(row['trajectory'][0]['args'],{'command':''})

    def test_compact_candidate_preserves_tool_contracts(self):
        original=json.dumps(h.ACI_TOOLS,sort_keys=True)
        baseline=h.prompt_and_tools('verseshell_aci','baseline')
        compact=h.prompt_and_tools('verseshell_aci','compact')
        self.assertEqual(baseline[:2],compact[:2])
        candidate=compact[2]
        for before,after in zip(h.ACI_TOOLS,candidate):
            self.assertEqual({k:v for k,v in before['function'].items() if k!='description'},
                             {k:v for k,v in after['function'].items() if k!='description'})
            self.assertLessEqual(len(after['function']['description']),60)
        self.assertLess(len(json.dumps(candidate)),len(json.dumps(h.ACI_TOOLS)))
        self.assertEqual(json.dumps(h.ACI_TOOLS,sort_keys=True),original)
        self.assertEqual(h.prompt_and_tools('raw_shell','compact'),h.prompt_and_tools('raw_shell','baseline'))


if __name__=='__main__':unittest.main()
