"""Offline controller/storage fault injection; no endpoint calls or real disk filling."""
import errno
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_control as control
import live_storage as storage
import refresh_live_artifacts as refresh


# Independent contract: do not derive this inventory from production constants.
EXPECTED_REPORT_FILES = (
    'task_set_audit.json', 'three_arm_report.json', 'cost_attribution.json',
    'cost_attribution.md', 'anomaly_audit.json', 'anomaly_audit.md',
    'acceptance_power.json',
)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.collection = self.root/'bench/aci/results/offline'
        self.collection.mkdir(parents=True)
        self.tasks = self.root/'tasks.json'
        self.tasks.write_text('{}')
        (self.collection/'latest_live.json').write_text('{}')
        (self.collection/'collection.json').write_text(json.dumps({
            'prompt_variants': ['baseline', 'compact_all'], 'task_set': str(self.tasks.resolve())}))
        (self.root/'tools').mkdir()
        self.reporter = self.root/'tools/refresh_live_artifacts.py'
        self.write_reporter()

    def write_reporter(self, missing=None, extra=False):
        # The outer reporter remains a real subprocess; only expensive analysis is fake.
        self.reporter.write_text("""import sys,json,hashlib
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=IMPORT_PATHS
from refresh_live_artifacts import refresh_collection
a=sys.argv
out=Path(a[a.index('--out-dir')+1])
v=a[a.index('--prompt-variant')+1]
collection=Path(a[a.index('--collection')+1])
source=collection/'latest_live.json'
missing=MISSING
extra=EXTRA
def runner(command, **kwargs):
 p=Path(command[command.index('--out')+1])
 assert p.name in ['task_set_audit.json','three_arm_report.json','cost_attribution.json','anomaly_audit.json','acceptance_power.json']
 if p.name != missing:
  p.write_text('{}', encoding='utf-8')
 if p.name in ['cost_attribution.json','anomaly_audit.json']:
  md=p.with_suffix('.md')
  if md.name != missing:
   md.write_text('# Offline report', encoding='utf-8')
 if extra:
  (out/'undeclared.json').write_text('{}')
 return SimpleNamespace(returncode=0)
rc=refresh_collection(collection,out,Path(a[a.index('--task-set')+1]),v,runner=runner)
if rc:sys.exit(rc)
""".replace('IMPORT_PATHS', repr([str(Path(refresh.__file__).parent), str(ROOT/'tools'),
                                  str(ROOT/'bench/aci/runners')]))
           .replace('MISSING', repr(missing)).replace('EXTRA', repr(extra)), encoding='utf-8')

    def launch(self, code=0, terminal=True):
        script = self.root/'child.py'
        script.write_text("""import json,os,sys,uuid
from pathlib import Path
code=int(sys.argv[2])
if sys.argv[3]=='yes':
 p=Path(sys.argv[1])/'round.status.json'
 p.write_text(json.dumps({'control_generation_id':os.environ['ACI_CONTROL_GENERATION_ID'],'generation_id':uuid.uuid4().hex,'pid':os.getpid(),'state':'completed' if code==0 else 'paused' if code==75 else 'failed','exit_code':code,'finished_at':'offline'}))
sys.exit(code)
""")
        return control.launch([sys.executable, str(script), str(self.collection), str(code), 'yes' if terminal else 'no'],
                              self.root, self.collection, self.collection/'control'/'offline-generation', {})

    def finalize(self, receipt):
        return control.finalize(receipt, self.root, self.collection, self.tasks)

    def test_real_process_codes_and_missing_terminal_fail_closed(self):
        for code, terminal, expected in [(0, True, 0), (7, True, 7), (75, True, 75), (0, False, 2)]:
            with self.subTest(code=code, terminal=terminal):
                with tempfile.TemporaryDirectory() as tmp:
                    c = Path(tmp)
                    script = [sys.executable, '-c', 'import sys;sys.exit(int(sys.argv[1]))', str(code)]
                    if terminal:
                        receipt = self.launch(code)
                        self.assertEqual(control.read_json(receipt)['resolved_exit_code'], expected)
                        # Separate test instances of the launch directory without deleting evidence.
                        (self.collection/'control'/'offline-generation').rename(self.collection/'control'/str(code))
                    else:
                        receipt = control.launch(script, self.root, c, c/'control', {})
                        self.assertEqual(control.read_json(receipt)['resolved_exit_code'], expected)

    def test_actual_round_status_binds_control_generation(self):
        script = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                  "import live_round as r;r.RESULTS=Path(sys.argv[2]);r._main=lambda:0;"
                  "sys.argv=['live_round','--tag','offline'];sys.exit(r.main())")
        receipt = control.launch([sys.executable, '-c', script, str(ROOT/'tools'), str(self.collection.parent)],
                                 self.root, self.collection, self.collection/'control'/'real-round', {})
        value = control.read_json(receipt)
        self.assertEqual(value['resolved_exit_code'], 0, value)
        self.assertEqual(value['terminal']['control_generation_id'], 'real-round')
        self.assertEqual(self.finalize(receipt), 0)

    def test_unknown_exit_requires_matching_terminal_pid_and_generation(self):
        receipt = control.read_json(self.launch())
        terminal = receipt['terminal']
        self.assertEqual(control.resolve_exit(None, terminal, receipt), (0, 'matching_terminal'))
        for bad in ({}, {**terminal, 'pid': -1}, {**terminal, 'control_generation_id': 'old'},
                    {**terminal, 'generation_id': 'old'}, {**terminal, 'state': 'running'},
                    {**terminal, 'exit_code': None}, {**terminal, 'exit_code': False}):
            self.assertEqual(control.resolve_exit(None, bad, receipt)[0], 2)
        self.assertEqual(control.resolve_exit(9, terminal, receipt)[0], 9)

    def test_both_variants_and_report_only_retry_keep_old_reports(self):
        receipt = self.launch()
        self.assertEqual(self.finalize(receipt), 0)
        old = {str(p): control.sha(p) for p in receipt.parent.rglob('*') if p.is_file()}
        self.assertEqual(self.finalize(receipt), 0)
        for p, digest in old.items():
            self.assertEqual(control.sha(p), digest)
        reports = list(receipt.parent.glob('reports-*/reports-status.json'))
        self.assertEqual(len(reports), 2)
        for report in reports:
            value = control.read_json(report)
            self.assertTrue(value['complete'])
            self.assertEqual(set(value['reports']), {'baseline', 'compact_all'})
            self.assertTrue(all(x['state'] == 'completed' and x['exit_code'] == 0 for x in value['reports'].values()))

    def assert_complete_bundle(self, receipt):
        status = next(receipt.parent.glob('reports-*/reports-status.json'))
        summary = control.read_json(status)
        self.assertTrue(summary['complete'], summary)
        self.assertEqual(set(summary['reports']), {'baseline', 'compact_all'})
        for variant, item in summary['reports'].items():
            self.assertEqual(item['state'], 'completed', item)
            self.assertEqual(item['exit_code'], 0)
            manifest_path = status.parent/variant/'refresh-status.json'
            manifest = control.read_json(manifest_path)
            self.assertTrue(manifest['complete'])
            self.assertEqual(manifest['prompt_variant'], variant)
            self.assertEqual(manifest['source_sha256'], control.sha(self.collection/'latest_live.json'))
            self.assertEqual(set(manifest['reports']), set(EXPECTED_REPORT_FILES))
            self.assertEqual(len(manifest['steps']), 5)
            self.assertTrue(all(step['exit_code'] == 0 for step in manifest['steps']))
            for name in EXPECTED_REPORT_FILES:
                self.assertEqual(manifest['reports'][name], control.sha(manifest_path.parent/name))

    def test_real_refresh_manifest_completes_both_variants(self):
        receipt = self.launch()
        self.assertEqual(self.finalize(receipt), 0)
        self.assert_complete_bundle(receipt)

    def test_real_refresh_excludes_undeclared_report_from_verified_inventory(self):
        self.write_reporter(extra=True)
        receipt = self.launch()
        self.assertEqual(self.finalize(receipt), 0)
        self.assert_complete_bundle(receipt)
        for path in receipt.parent.glob('reports-*/*/refresh-status.json'):
            self.assertTrue((path.parent/'undeclared.json').is_file())
            self.assertNotIn('undeclared.json', control.read_json(path)['reports'])

    def test_real_refresh_missing_required_outputs_fails_closed(self):
        receipt = self.launch()
        for name in EXPECTED_REPORT_FILES:
            with self.subTest(missing=name):
                self.write_reporter(missing=name)
                previous = set(receipt.parent.glob('reports-*'))
                self.assertEqual(self.finalize(receipt), 2)
                report_dir, = set(receipt.parent.glob('reports-*')) - previous
                summary = control.read_json(report_dir/'reports-status.json')
                self.assertFalse(summary['complete'])
                for variant, item in summary['reports'].items():
                    self.assertEqual(item['state'], 'failed')
                    self.assertNotEqual(item['exit_code'], 0)
                    self.assertFalse(control.read_json(report_dir/variant/'refresh-status.json')['complete'])

    @patch.object(control, 'pid_alive', return_value=False)
    def test_finalize_rejects_incomplete_tampered_and_extra_manifests(self, _pid_alive):
        # This case is about manifest validation, not owner liveness. Pinning
        # pid_alive keeps it independent of OS PID reuse by unrelated live
        # tests; the fail-closed owner contract stays covered by
        # test_new_generation_and_live_owner_cannot_finalize.
        receipt = self.launch()
        original = self.reporter.read_text()
        mutations = {
            'legacy-three': "manifest['reports']={k:v for k,v in manifest['reports'].items() if k in ['task_set_audit.json','three_arm_report.json','acceptance_power.json']}",
            'declared-extra': "(out/'undeclared.json').write_text('{}');manifest['reports']['undeclared.json']=hashlib.sha256((out/'undeclared.json').read_bytes()).hexdigest()",
        }
        for name in EXPECTED_REPORT_FILES:
            mutations['omit-'+name] = f"manifest['reports'].pop({name!r},None)"
            mutations['delete-'+name] = f"(out/{name!r}).unlink()"
            mutations['digest-'+name] = f"(out/{name!r}).write_text('tampered')"
        for fault, mutation in mutations.items():
            with self.subTest(fault=fault):
                self.reporter.write_text(original + "\nmanifest=json.loads((out/'refresh-status.json').read_text())\n"
                                         + mutation + "\n(out/'refresh-status.json').write_text(json.dumps(manifest))\n")
                previous = set(receipt.parent.glob('reports-*'))
                self.assertEqual(self.finalize(receipt), 2)
                report_dir, = set(receipt.parent.glob('reports-*')) - previous
                summary = control.read_json(report_dir/'reports-status.json')
                self.assertFalse(summary['complete'])
                self.assertEqual(set(summary['reports']), {'baseline', 'compact_all'})
                for item in summary['reports'].values():
                    self.assertEqual(item['exit_code'], 0, item)
                    self.assertEqual(item['state'], 'failed', item)
                    self.assertNotIn('manifest_sha256', item)

    def test_one_report_failure_keeps_both_terminal_and_retry_recovers(self):
        receipt = self.launch()
        original = self.reporter.read_text()
        self.reporter.write_text(original+"\nif v=='baseline':sys.exit(6)\n")
        self.assertEqual(self.finalize(receipt), 2)
        failed = next(receipt.parent.glob('reports-*/reports-status.json'))
        value = control.read_json(failed)
        self.assertFalse(value['complete'])
        self.assertEqual(value['reports']['baseline']['exit_code'], 6)
        self.assertEqual(value['reports']['compact_all']['state'], 'completed')
        digest = control.sha(failed)
        self.reporter.write_text(original)
        self.assertEqual(self.finalize(receipt), 0)
        self.assertEqual(control.sha(failed), digest)

    def test_new_generation_and_live_owner_cannot_finalize(self):
        receipt = self.launch()
        terminal = control.read_json(self.collection/'round.status.json')
        terminal['control_generation_id'] = 'different'
        control.atomic_json(self.collection/'round.status.json', terminal)
        self.assertEqual(self.finalize(receipt), 2)
        with patch.object(control, 'pid_alive', return_value=True):
            with self.assertRaisesRegex(ValueError, 'still alive'):
                self.finalize(receipt)
        self.assertFalse(list(receipt.parent.glob('reports-*')))

    def test_zero_exit_without_reports_and_source_mutation_are_not_complete(self):
        receipt = self.launch()
        original = self.reporter.read_text()
        for content in ('', original+"\nsource.write_text('changed')\n"):
            self.reporter.write_text(content)
            self.assertEqual(self.finalize(receipt), 2)
        self.assertTrue(all(not control.read_json(p)['complete'] for p in receipt.parent.glob('reports-*/reports-status.json')))

    def test_refresh_records_unknown_nonzero_and_exception(self):
        for failure in (None, 5, OSError(errno.ENOSPC, 'injected write failure')):
            with self.subTest(failure=failure):
                output = self.root/('report-'+str(len(list(self.root.glob('report-*')))))
                def run(*args, **kwargs):
                    if isinstance(failure, Exception):
                        raise failure
                    return SimpleNamespace(returncode=failure)
                if isinstance(failure, Exception):
                    with self.assertRaises(OSError):
                        refresh.refresh_collection(self.collection, output, self.tasks, runner=run)
                else:
                    self.assertEqual(refresh.refresh_collection(self.collection, output, self.tasks, runner=run), 2 if failure is None else failure)
                value = control.read_json(output/'refresh-status.json')
                self.assertEqual(value['state'], 'failed')
                self.assertFalse(value['complete'])
                self.assertEqual(value['steps'][0]['exit_code'], None if isinstance(failure, Exception) else failure)

    def test_disk_reserves_boundary_unknown_and_invalid_policy(self):
        policy = {'D:/': 15*1024**3, 'C:/': 2*1024**3}
        for low in (None, 'D:/', 'C:/'):
            with patch.object(storage.shutil, 'disk_usage', side_effect=lambda p: SimpleNamespace(free=policy[p]-(p == low))):
                self.assertEqual(storage.storage_check(policy)['ok'], low is None)
        with patch.object(storage.shutil, 'disk_usage', side_effect=OSError('injected unavailable drive')):
            result = storage.storage_check(policy)
            self.assertFalse(result['ok'])
            self.assertTrue(all(x['free_bytes'] is None for x in result['readings'].values()))
        for value in ('[]', '{"relative": 10}', '{"D:/": -1}', '{"D:/": true}'):
            with patch.dict(os.environ, ACI_STORAGE_RESERVES=value):
                with self.assertRaises(ValueError):
                    storage.storage_policy()

    def test_low_disk_report_retry_never_dispatches_or_clears_marker(self):
        receipt = self.launch()
        with patch.object(control, 'storage_check', return_value={'ok': False, 'readings': {}}), \
             patch.object(control, 'run_bounded') as run:
            self.assertEqual(self.finalize(receipt), 75)
        run.assert_not_called()
        value = control.read_json(next(receipt.parent.glob('reports-*/reports-status.json')))
        self.assertTrue(all(v['state'] == 'paused' for v in value['reports'].values()))
        self.assertTrue((self.collection/'STOP').exists())
        self.assertEqual(self.finalize(receipt), 0)
        self.assertTrue((self.collection/'STOP').exists())

    def test_storage_preflight_does_not_spawn_and_preserves_stop(self):
        with (patch.object(sys, 'argv', ['live_control', '--workspace', str(self.root), '--tag', 'offline']),
              patch.object(control, 'storage_check', return_value={'ok': False, 'readings': {}}),
              patch.object(control, 'launch') as launch):
            self.assertEqual(control.main(), 75)
        launch.assert_not_called()
        self.assertTrue((self.collection/'STOP').exists())
        self.assertEqual(control.read_json(self.collection/'control.status.json')['state'], 'paused')


if __name__ == '__main__':
    unittest.main()
