import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import task_design_audit as design
import claim_gate as gate

class DesignAuditTests(unittest.TestCase):
    def inputs(self):
        return ({'task_set_version':'test','tasks':['a','b','c'],'n_tasks':3,'per_tier':{'large':2}},
                {'candidates':[{'task_id':'a','pristine_observation_tokens':1000,'checks':{'A1_pristine_fails':True}}]},
                {'task_set_version':'test','rows':[{'task_id':['a','b','c'][i%3],'condition':'raw_shell','model':'m','success':i<9} for i in range(10)]},
                {'preregistered_parameters':{'success_mde_absolute':0.15}})
    def test_quota_counts_growing_denominator(self):
        for total,large,expected in [(35,7,7),(40,12,2),(30,10,0),(25,4,7)]:
            self.assertEqual(design.additional_large_required(total,large),expected)
            self.assertGreaterEqual(3*(large+expected),total+expected)
            if expected: self.assertLess(3*(large+expected-1),total+expected-1)
    def test_unknown_is_not_small_or_a_tier_label(self):
        report=design.audit(*self.inputs())
        c=report['composition']
        self.assertEqual(c['measured_tasks'],1)
        self.assertEqual(c['confirmed_large_tasks'],['a'])
        self.assertEqual(c['unmeasured_tasks'],['b','c'])
        self.assertEqual(c['labelled_large_count'],2)
        self.assertAlmostEqual(report['difficulty']['observed_positive_headroom'],0.1)
        self.assertFalse(report['difficulty']['headroom_supports_positive_mde'])
    def test_conflicting_observations_cannot_be_cherry_picked(self):
        inputs=list(self.inputs()); other=copy.deepcopy(inputs[1]['candidates'][0]); other['pristine_observation_tokens']=5
        inputs[1]['candidates'].append(other)
        with self.assertRaises(ValueError): design.audit(*inputs)
    def test_mismatched_frozen_cohort_is_rejected(self):
        inputs=list(self.inputs()); inputs[2]['task_set_version']='old'
        with self.assertRaises(ValueError): design.audit(*inputs)
        inputs=list(self.inputs()); inputs[2]['rows'][0]['task_id']='foreign'
        with self.assertRaises(ValueError): design.audit(*inputs)
    def test_freshness_rejects_changed_source(self):
        self.assertIn('eval/task_design_audit.json',gate.EVIDENCE_ARTIFACTS)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'eval').mkdir(); source=root/'input.json'; source.write_text('{}',encoding='utf-8')
            with patch.object(gate,'ROOT',root),patch.object(gate,'EVIDENCE_ARTIFACTS',['eval/task_design_audit.json']):
                e={'globs':['input.json'],'fingerprint':gate.evidence_fingerprint(['input.json']),
                   'input_sha256':{'input.json':hashlib.sha256(source.read_bytes()).hexdigest()}}
                (root/'eval/task_design_audit.json').write_text(json.dumps({'evidence':e}),encoding='utf-8')
                self.assertTrue(gate.freshness_entries()[0]['pass'])
                source.write_text('{"changed":true}',encoding='utf-8')
                self.assertFalse(gate.freshness_entries()[0]['pass'])
if __name__=='__main__': unittest.main()
