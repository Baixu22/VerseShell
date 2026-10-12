"""Portable R12 input integrity, output safety and no silent latest-data fallback."""
import hashlib,importlib.util,json
from pathlib import Path
import tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('r12_audit_inputs',ROOT/'audit-r12-scratch/audit_inputs.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)

def dump(path,data):path.write_text(json.dumps(data),encoding='utf-8')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class HistoricalInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.code=self.root/'audit-r12-scratch';self.code.mkdir()
        self.data=self.root/'data';self.data.mkdir();self.script=self.code/'verify_core.py';self.script.write_text('# calculator')
        self.conditions=['raw_shell','raw_shell_coached','verseshell_aci']
        cfg={'seed':42,'model':'unit','repeat':1,'conditions':self.conditions,'tasks':['task']}
        rows=[{'task_id':'task','condition':c,'model':'unit','run_index':0,'success':True,
               'observation_tokens':3,'llm_prompt_tokens':4,'llm_completion_tokens':5,
               'tool_calls':1,'turns':1,'elapsed_ms':2} for c in self.conditions]
        self.entries=[]
        for role in ('with','without'):
            p=self.data/(role+'.json');dump(p,{'mode':'live','task_set_version':'2.0.0','git_rev':'old','live_config':cfg,'rows':rows})
            self.entries.append({'role':role,'path':'../data/'+p.name,'seed':42,'rows':3,'sha256':sha(p)})
        ref=self.code/'reference.json';meta={}
        for prefix in ('main','ablation'):
            meta.update({prefix+'_live_config':{**cfg,'seeds':[42]},prefix+'_git_rev':'old',prefix+'_generated_at':'historical'})
        dump(ref,{'R2_ablation_vs_main_seed42':meta})
        self.manifest=self.code/'r12-inputs.json'
        self.config={'schema':'verseshell.r12-inputs/v1','experiment':'unit','task_set_version':'2.0.0','conditions':self.conditions,
            'inputs':self.entries,'expected_rows':{'with':3,'without':3},'scope':'synthetic control','source_basis':'test only',
            'metadata_reference':{'path':ref.name,'sha256':sha(ref)}}
        dump(self.manifest,self.config);self.output=self.root/'output'

    def load(self):return loader.AuditInputs(self.script,['--out-dir',str(self.output)])

    def change_shard(self,mutate,update_hash=False):
        p=self.data/'with.json';d=json.loads(p.read_text());mutate(d);dump(p,d)
        if update_hash:self.config['inputs'][0]['sha256']=sha(p);dump(self.manifest,self.config)

    def test_rows_and_metadata_are_recovered_without_latest(self):
        inputs=self.load()
        self.assertEqual(len(inputs.rows['with']),3)
        self.assertTrue(all(r['seed']==42 for r in inputs.rows['with']))
        self.assertEqual(inputs.with_payload['live_config']['seeds'],[42])
        self.assertFalse((self.root/'bench/aci/results/latest_live.json').exists())

    def test_wrong_hash_rejected_before_output(self):
        self.change_shard(lambda d:d.update(extra=True))
        with self.assertRaisesRegex(ValueError,'digest'):self.load()
        self.assertFalse(self.output.exists())

    def test_version_mismatch_is_not_recognized_as_r12(self):
        self.change_shard(lambda d:d.update(task_set_version='3.0.0'),True)
        with self.assertRaisesRegex(ValueError,'version'):self.load()

    def test_duplicate_or_incomplete_grid_rejected(self):
        self.change_shard(lambda d:d['rows'].__setitem__(1,dict(d['rows'][0])),True)
        with self.assertRaisesRegex(ValueError,'duplicate or incomplete'):self.load()

    def test_missing_usage_is_not_zero_imputed(self):
        self.change_shard(lambda d:d['rows'][0].update(llm_prompt_tokens=None),True)
        with self.assertRaisesRegex(ValueError,'numeric'):self.load()

    def test_metadata_mismatch_is_rejected(self):
        ref=self.code/'reference.json';d=json.loads(ref.read_text());d['R2_ablation_vs_main_seed42']['main_live_config']['max_tokens']=99;dump(ref,d)
        self.config['metadata_reference']['sha256']=sha(ref);dump(self.manifest,self.config)
        with self.assertRaisesRegex(ValueError,'configuration'):self.load()

    def test_input_change_after_loading_blocks_publication(self):
        inputs=self.load();(self.data/'with.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed during'):inputs.write({'result':1})
        self.assertFalse(inputs.output.exists())

    def test_existing_results_are_never_overwritten(self):
        self.output.mkdir();target=self.output/'verify_core.json';target.write_text('old')
        with self.assertRaisesRegex(ValueError,'already exists'):self.load()
        self.assertEqual(target.read_text(),'old')

    def test_success_receipt_binds_inputs_code_and_output(self):
        inputs=self.load();inputs.write({'result':3})
        receipt=json.loads(inputs.receipt.read_text())
        self.assertEqual(receipt['output_sha256'],sha(inputs.output))
        self.assertEqual(receipt['calculator_sha256'],sha(self.script))
        self.assertFalse(receipt['current_confirmatory_claim'])

    def test_readiness_source_snapshot_includes_historical_audit_dependencies(self):
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from prelive_check import source_hashes
        hashes=source_hashes(ROOT)
        for name in ('audit-r12-scratch/audit_inputs.py','audit-r12-scratch/verify_core.py',
                     'audit-r12-scratch/r12-inputs.json','audit-r12-scratch/r12-reference/verify_core.json',
                     'audit-r12-scratch/r12-inputs/with_seed42.json'):
            self.assertIn(name,hashes)

    def test_absolute_or_escaping_inputs_are_rejected(self):
        for value in ('C:/somewhere/input.json','../../outside.json'):
            self.config['inputs'][0]['path']=value;dump(self.manifest,self.config)
            with self.assertRaises(ValueError):self.load()

if __name__=='__main__':unittest.main()
