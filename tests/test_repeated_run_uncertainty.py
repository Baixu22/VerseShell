"""Synthetic statistical controls only; these are not live repetitions."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import repeated_run_uncertainty as repeated

class RepeatedRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'tasks.json').write_text(json.dumps({'task_set_version':'test','tasks':['a','b','c']}),encoding='utf-8')
        self.spec={'task_manifest':'tasks.json','seeds':[42],'conditions':['raw_shell','verseshell_aci'],'runs':[]}
        for i in range(3):
            rows=[]
            for task in ['a','b','c']:
                for condition in self.spec['conditions']:
                    value=10 if condition=='raw_shell' else 10*(i+1)
                    rows.append({'task_id':task,'condition':condition,'model':'fixture','seed':42,'run_index':0,
                                 'success':True,'turns':1,'completion_truncated_turns':0,
                                 'tool_calls':value,'observation_tokens':value,'llm_prompt_tokens':value,'llm_completion_tokens':value})
            data={'mode':'live','synthetic_test_only':True,'generated_at':str(i),'git_rev':'test-revision',
                  'task_set_version':'test','evidence':{'fingerprint':'same-code'},
                  'live_config':{'model':'fixture','api_base':'invalid://offline','caps':'file.read',
                                 'max_turns':20,'max_tokens':16384,'temperature':0,'exclude_tools':[]},'rows':rows}
            name=f'run-{i}.json';(self.root/name).write_text(json.dumps(data),encoding='utf-8')
            self.spec['runs'].append({'run_id':str(i),'artifact':name})
        self.manifest=self.root/'study.json';self.save()
    def save(self): self.manifest.write_text(json.dumps(self.spec),encoding='utf-8')
    def alter(self,index,change):
        p=self.root/f'run-{index}.json';data=json.loads(p.read_text(encoding='utf-8'));change(data);p.write_text(json.dumps(data),encoding='utf-8')
    def test_raw_single_seed_configuration_is_supported(self):
        for i in range(3):
            def change(d):
                d['live_config']['seed']=42
                for row in d['rows']: row.pop('seed')
            self.alter(i,change)
        self.assertEqual(len(repeated.load_study(self.manifest)['runs']),3)
    def test_itt_scores_excluded_success_as_failure(self):
        from live_uncertainty import row_policy
        rows=[{'condition':'raw_shell','success':True},
              {'condition':'verseshell_aci','success':True,'completion_truncated_turns':1}]
        policy=row_policy(rows,['raw_shell','verseshell_aci'],20,[('raw_shell','verseshell_aci')])
        self.assertEqual(policy['per_arm']['verseshell_aci']['success_intention_to_treat'],0)
    def test_exclusion_threshold_does_not_use_rounded_display_rate(self):
        from live_uncertainty import row_policy
        n=20001;k=2001
        rows=[{'condition':'raw_shell','success':True}]*n
        rows += [{'condition':'verseshell_aci','success':True,'completion_truncated_turns':1}]*k
        rows += [{'condition':'verseshell_aci','success':True}]*(n-k)
        p=row_policy(rows,['raw_shell','verseshell_aci'],20,[('raw_shell','verseshell_aci')])
        self.assertEqual(p['per_arm']['verseshell_aci']['cap_truncated_rate'],0.1)
        self.assertFalse(p['comparisons']['verseshell_aci_vs_raw_shell']['rates_ok'])
    def test_sign_agreement_uses_exact_rates_not_display_rounding(self):
        from live_uncertainty import row_policy
        def rows(condition, successes, ordinary_failures, capped):
            return ([{'condition':condition,'success':True}]*successes+
                    [{'condition':condition,'success':False}]*ordinary_failures+
                    [{'condition':condition,'success':False,'completion_truncated_turns':1}]*capped)
        data=rows('raw_shell',5000,4001,999)+rows('verseshell_aci',5001,4002,997)
        p=row_policy(data,['raw_shell','verseshell_aci'],20,[('raw_shell','verseshell_aci')])
        self.assertFalse(p['comparisons']['verseshell_aci_vs_raw_shell']['sign_agreement'])
        self.assertFalse(p['comparisons']['verseshell_aci_vs_raw_shell']['claimable'])
    def test_closed_form_variance_components(self):
        c=repeated.variance_components([[1,2,3],[3,4,5],[5,6,7]])
        self.assertAlmostEqual(c['run_variance'],4)
        self.assertAlmostEqual(c['task_variance'],1)
        self.assertAlmostEqual(c['interaction_residual_variance'],0)
        self.assertAlmostEqual(sum(c['variance_of_mean_parts'].values()),5/3)
    def test_between_run_effect_widens_interval(self):
        study=repeated.load_study(self.manifest); report=repeated.analyse(study,1000,7)
        metric=report['comparisons']['verseshell_aci_vs_raw_shell']['views']['analysable']['observation_token_ratio']
        self.assertAlmostEqual(metric['point_estimate'],2)
        self.assertEqual(metric['diagnostic_task_only_ci95'],[2,2])
        self.assertLess(metric['headline_ci95'][0],2)
        self.assertGreater(metric['headline_ci95'][1],2)
        self.assertGreater(metric['variance_components']['run_variance'],0)
        self.assertEqual(report,repeated.analyse(study,1000,7) | {'generated_at':report['generated_at']})
    def test_constant_ratio_is_not_changed_by_resampling(self):
        matrix=[[(1,1,2,1),(5,1,10,1)],[(2,1,4,1),(7,1,14,1)],[(3,1,6,1),(9,1,18,1)]]
        result=repeated.summarize(matrix,'ratio',200,4)
        self.assertEqual(result['headline_ci95'],[2,2])
        self.assertEqual(result['variance_components']['run_variance'],0)

    def test_cpst_and_cell_mean_ratios_use_distinct_denominators(self):
        for i in range(3):
            def change(d):
                for row in d['rows']:
                    row['observation_tokens']=10 if row['condition']=='raw_shell' else 5
                    row['success']=row['condition']=='raw_shell' or row['task_id']=='a'
            self.alter(i,change)
        study=repeated.load_study(self.manifest)
        cpst=repeated.summarize(repeated.metric_cells(study,'raw_shell','analysable','observation_cost_per_success'),'ratio',100,42)
        self.assertAlmostEqual(cpst['point_estimate'],1.5)
        self.assertFalse(cpst['available'])  # some draws contain no D successes
        means=repeated.summarize(repeated.metric_cells(study,'raw_shell','analysable','observation_mean_of_ratios'),'difference',100,42)
        self.assertEqual(means['headline_ci95'],[.5,.5])

    def test_incomplete_usage_flag_blocks_both_ratio_estimators(self):
        self.alter(0,lambda d:d['rows'][0].update(usage_complete=False))
        study=repeated.load_study(self.manifest)
        for metric in ('usage_token_ratio','usage_mean_of_ratios','usage_cost_per_success'):
            with self.assertRaises(ValueError):repeated.metric_cells(study,'raw_shell','analysable',metric)
    def test_three_seeds_are_not_three_complete_repetitions(self):
        self.spec['seeds']=[42,43,44];self.save()
        with self.assertRaisesRegex(ValueError,'grid'): repeated.load_study(self.manifest)
    def test_missing_duplicate_and_mismatched_runs_rejected(self):
        self.alter(1,lambda d:d['rows'].pop())
        with self.assertRaisesRegex(ValueError,'grid'): repeated.load_study(self.manifest)
        self.alter(1,lambda d:d['rows'].append(d['rows'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate cell'): repeated.load_study(self.manifest)
    def test_budget_mismatch_and_duplicate_artifact_rejected(self):
        self.alter(1,lambda d:d['live_config'].update(max_tokens=8192))
        with self.assertRaisesRegex(ValueError,'configuration'): repeated.load_study(self.manifest)
        self.spec['runs'][1]['artifact']='run-0.json';self.save()
        with self.assertRaisesRegex(ValueError,'duplicate run'): repeated.load_study(self.manifest)
    def test_both_views_and_unknown_draws_are_explicit(self):
        self.alter(0,lambda d:d['rows'][1].update(completion_truncated_turns=1))
        report=repeated.analyse(repeated.load_study(self.manifest),200,42)
        views=report['comparisons']['verseshell_aci_vs_raw_shell']['views']
        self.assertEqual(views['analysable']['success_delta']['point_estimate'],0)
        self.assertLess(views['intention_to_treat']['success_delta']['point_estimate'],0)
        result=repeated.summarize([[(0,1,1,1),(1,1,1,1)]]*3,'ratio',500,2)
        self.assertGreater(result['undefined_draws']['crossed'],0)
        self.assertIsNone(result['headline_ci95'])
    def test_complete_multi_seed_three_condition_grid(self):
        self.spec['seeds']=[42,43,44];self.spec['run_indices']=[0,1]
        self.spec['conditions'].append('raw_shell_coached');self.save()
        for i in range(3):
            def expand(d):
                original=d['rows']
                original += [{**r,'condition':'raw_shell_coached'} for r in original if r['condition']=='raw_shell']
                d['rows']=[{**r,'seed':seed,'run_index':index} for r in original for seed in [42,43,44] for index in [0,1]]
            self.alter(i,expand)
        report=repeated.analyse(repeated.load_study(self.manifest),200,1)
        self.assertEqual(len(report['comparisons']),2)
        self.assertEqual(report['comparisons']['verseshell_aci_vs_raw_shell_coached']['views']['analysable']['observation_token_ratio']['point_estimate'],2)
    def test_missing_usage_is_not_zero_imputed(self):
        self.alter(0,lambda d:d['rows'][0].pop('llm_prompt_tokens'))
        report=repeated.analyse(repeated.load_study(self.manifest),200,1)
        metrics=report['comparisons']['verseshell_aci_vs_raw_shell']['views']['analysable']
        self.assertFalse(metrics['usage_token_ratio']['available'])
        self.assertTrue(metrics['observation_token_ratio']['available'])
    def test_fewer_than_three_runs_rejected(self):
        self.spec['runs'].pop();self.save()
        with self.assertRaisesRegex(ValueError,'three complete'):repeated.load_study(self.manifest)
if __name__=='__main__': unittest.main()
