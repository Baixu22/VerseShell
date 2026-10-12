"""Exact future grading inputs without persisting sensitive frozen verifier bytes."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import final_workspace as snapshots
import final_workspace_audit as review
import live_agent_loop as harness
from grading_contract import freeze_verifiers
from live_journal import ObservationStore

# Public synthetic marker, never a working credential.
CHECK = (b"from pathlib import Path\nimport sys\n"
         b"HEADER = 'Bearer public-fixture-only'\n"
         b"sys.exit(0 if Path('answer.txt').read_text() == 'ok' else 1)\n")


class FinalWorkspaceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base/'source'; self.source.mkdir()
        self.artifacts = self.base/'artifacts'; self.artifacts.mkdir()
        self.frozen_source = self.base/'frozen-fixture'; self.frozen_source.mkdir()
        (self.source/'check.py').write_bytes(CHECK)
        (self.frozen_source/'check.py').write_bytes(CHECK)
        (self.source/'answer.txt').write_text('ok', encoding='utf-8')
        self.predicate = {'type': 'command_exit_0', 'argv': [sys.executable, 'check.py']}
        self.frozen = freeze_verifiers(self.predicate, self.source)
        self.store = snapshots.FinalWorkspaceStore(self.artifacts/'final-workspaces')

    def capture(self, cell='cell', success=True):
        reference = self.store.capture(self.source, cell_id=cell, task_id='task',
                                       predicate=self.predicate, protected_verifiers=self.frozen)
        return {'cell_id': cell, 'task_id': 'task', 'success': success,
                'protected_verifiers': self.frozen, 'final_workspace': reference}

    def forge(self, row, mutate):
        reference = row['final_workspace']
        manifest = json.loads((self.artifacts/reference['path']).read_bytes())
        mutate(manifest)
        body = json.dumps(manifest, sort_keys=True).encode()
        sha = snapshots.digest(body)
        name = 'final-workspaces/manifests/'+sha+'.json'
        (self.artifacts/name).write_bytes(body)
        return {**reference, 'path': name, 'sha256': sha}

    def test_frozen_reference_is_explicit_and_never_stores_sensitive_bytes(self):
        row = self.capture(); reference = row['final_workspace']
        self.assertEqual(reference['state'], 'requires_verifier_source')
        self.assertEqual(reference['protected_reference_count'], 1)
        self.assertFalse((self.store.directory/'blobs'/snapshots.digest(CHECK)).exists())
        for saved in self.store.directory.rglob('*'):
            if saved.is_file():self.assertNotIn(b'Bearer public-fixture-only', saved.read_bytes())
        with self.assertRaisesRegex(ValueError, 'explicit.*verifier source'):
            snapshots.load_manifest(self.artifacts, reference)
        manifest, _ = snapshots.load_manifest(self.artifacts, reference, verifier_source=self.frozen_source)
        self.assertEqual(manifest['schema'], 'verseshell.final-workspace/v2')
        entry = next(e for e in manifest['files'] if e['path'] == 'check.py')
        self.assertEqual(entry['storage'], 'protected_verifier')
        self.assertEqual(entry['sha256'], self.frozen['check.py'])
        restored = self.base/'restored'
        snapshots.restore(self.artifacts, reference, restored, verifier_source=self.frozen_source)
        self.assertEqual((restored/'check.py').read_bytes(), CHECK)
        self.assertEqual((restored/'answer.txt').read_text(), 'ok')

    def test_explicit_runtime_credential_is_rejected_even_if_frozen(self):
        secret = 'offline-runtime-credential'
        (self.source/'check.py').write_bytes(CHECK+('# '+secret).encode())
        self.frozen = freeze_verifiers(self.predicate, self.source)
        self.store = snapshots.FinalWorkspaceStore(self.artifacts/'explicit-secret', (secret,))
        with self.assertRaisesRegex(ValueError, 'credential'):self.capture()
        self.assertFalse((self.store.directory/'manifests').exists())
        self.assertTrue(all(secret.encode() not in p.read_bytes() for p in self.store.directory.rglob('*') if p.is_file()))

    def test_unfrozen_changed_or_sensitive_path_is_not_a_reference(self):
        for case in ('unfrozen', 'changed', 'path'):
            with self.subTest(case=case):
                self.store = snapshots.FinalWorkspaceStore(self.artifacts/case)
                self.frozen = freeze_verifiers(self.predicate, self.source)
                if case == 'unfrozen':self.frozen = {}
                if case == 'changed':(self.source/'check.py').write_bytes(CHECK+b'\n')
                if case == 'path':
                    name = 'Bearer private-fixture'
                    (self.source/name).write_bytes(b'public')
                    self.frozen[name] = snapshots.digest(b'public')
                with self.assertRaisesRegex(ValueError, 'credential'):self.capture()
                self.assertFalse((self.store.directory/'manifests').exists())

    def test_model_created_sensitive_file_still_rejects_capture(self):
        (self.source/'new-config.txt').write_bytes(b'Authorization: Bearer generated-private-material')
        with self.assertRaisesRegex(ValueError, 'credential'):self.capture()
        self.assertFalse((self.store.directory/'manifests').exists())

    def test_default_audit_and_historical_missing_remain_unknown(self):
        row = self.capture()
        old = {**row, 'cell_id': 'old', 'final_workspace': {'state': 'unavailable', 'reason': 'historical credential rejection'}}
        payload = {'rows': [row, old]}; before = copy.deepcopy(payload)
        with patch.object(review, 'check_success') as score:
            result = review.audit(payload, self.artifacts, tasks={'task': {'success': self.predicate}},
                                  rescore_ids=['cell', 'old'])
        score.assert_not_called()
        self.assertEqual(result['summary']['snapshots_verified'], 0)
        self.assertEqual(result['summary']['independently_scored'], 0)
        self.assertTrue(all(r['independent_success'] is None for r in result['rows']))
        self.assertIn('explicit', result['rows'][0]['reason'])
        with patch.object(review, 'check_success') as score:
            result = review.audit({'rows': [old]}, self.artifacts, tasks={'task': {'success': self.predicate}},
                                  rescore_ids=['old'], verifier_sources={'task': self.frozen_source})
        score.assert_not_called()
        self.assertIsNone(result['rows'][0]['independent_success'])
        self.assertEqual(payload, before)

    def test_missing_wrong_or_redirected_source_fails_before_creating_destination(self):
        row = self.capture(); reference = row['final_workspace']
        missing = self.base/'missing'; missing.mkdir()
        wrong = self.base/'wrong'; wrong.mkdir(); (wrong/'check.py').write_bytes(CHECK+b'\n')
        for source in (None, missing, wrong):
            with self.subTest(source=source):
                destination = self.base/'must-not-exist'
                with self.assertRaises((OSError, ValueError)):
                    snapshots.restore(self.artifacts, reference, destination, verifier_source=source)
                self.assertFalse(destination.exists())
                result = review.review_row(row, self.artifacts, task={'success': self.predicate},
                                           rescore=True, verifier_source=source)
                self.assertFalse(result['snapshot_verified'])
                self.assertFalse(result['rescore_attempted'])
                self.assertIsNone(result['independent_success'])
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda p: p == self.frozen_source/'check.py' or original(p)):
            with self.assertRaisesRegex(ValueError, 'redirected'):
                snapshots.restore(self.artifacts, reference, self.base/'redirected', verifier_source=self.frozen_source)
        self.assertFalse((self.base/'redirected').exists())

    def test_reference_requires_matching_protected_inventory_and_state(self):
        row = self.capture()
        def verifier_entry(manifest):return next(e for e in manifest['files'] if e['path'] == 'check.py')
        for mutate in (lambda m: m['protected_verifiers'].clear(),
                       lambda m: m['protected_verifiers'].update({'check.py': '0'*64}),
                       lambda m: verifier_entry(m).update(storage='unknown'),
                       lambda m: m.update(schema='verseshell.final-workspace/v1')):
            with self.subTest(mutate=mutate):
                reference = self.forge(row, mutate)
                with self.assertRaises(ValueError):
                    snapshots.load_manifest(self.artifacts, reference, verifier_source=self.frozen_source)
        for update in ({'state': 'available'}, {'protected_reference_count': 0}, {'protected_reference_count': True}):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    snapshots.load_manifest(self.artifacts, {**row['final_workspace'], **update}, verifier_source=self.frozen_source)

    def test_source_drift_between_verification_and_restore_is_rejected(self):
        row = self.capture()
        original = snapshots.load_manifest
        def drift(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.frozen_source/'check.py').write_bytes(CHECK+b'\n')
            return result
        with patch.object(snapshots, 'load_manifest', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'hash|size'):
                snapshots.restore(self.artifacts, row['final_workspace'], self.base/'drifted', verifier_source=self.frozen_source)
        if (self.base/'drifted/check.py').exists():
            self.fail('changed verifier bytes were restored')

    def test_explicit_source_recovers_pass_and_fail_without_guessing_student_code(self):
        passing = self.capture('pass', True)
        (self.source/'answer.txt').write_text('wrong', encoding='utf-8')
        failing = self.capture('fail', False)
        # The external source has no answer.txt: only frozen verifier bytes may come from it.
        result = review.audit({'rows': [passing, failing]}, self.artifacts,
                              tasks={'task': {'success': self.predicate}}, rescore_ids=['pass', 'fail'],
                              work_dir=self.base/'scores', verifier_sources={'task': self.frozen_source})
        self.assertEqual(result['summary']['snapshots_verified'], 2)
        self.assertEqual(result['summary']['independently_scored'], 2)
        self.assertEqual(result['summary']['matches_recorded'], 2)
        self.assertEqual([r['independent_success'] for r in result['rows']], [True, False])
        self.assertTrue(all(r['protected_reference_count'] == 1 for r in result['rows']))

    def test_live_row_after_cleanup_needs_explicit_frozen_source(self):
        task = {'id': 'task', 'workspace_fixture': 'offline', 'prompt': 'offline', 'success': self.predicate}
        response = {'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': 'done'}}]}
        with patch.object(harness, 'prepare_workspace', return_value=self.source), \
             patch.object(harness, 'chat_completion', return_value=response), contextlib.redirect_stdout(io.StringIO()):
            row = harness.run_agent_loop(task, 'raw_shell', model='offline', api_key='runtime-only-credential',
                                        base_url='http://offline', cell_id='cell',
                                        observation_store=ObservationStore(self.artifacts/'observations'))
        self.assertFalse(self.source.exists())
        self.assertTrue(row['success'])
        self.assertFalse(row['evidence_storage_fault'])
        self.assertEqual(row['final_workspace']['state'], 'requires_verifier_source')
        without = review.review_row(row, self.artifacts, task=task, rescore=True)
        self.assertIsNone(without['independent_success'])
        result = review.review_row(row, self.artifacts, task=task, rescore=True,
                                   verifier_source=self.frozen_source, work_dir=self.base/'scores')
        self.assertTrue(result['independent_success'])
        self.assertTrue(result['matches_recorded'])

    def test_cli_source_mapping_is_explicit_and_never_rewrites_input(self):
        row = self.capture()
        source = self.artifacts/'run.json'; source.write_text(json.dumps({'rows': [row]}), encoding='utf-8')
        before = source.read_bytes()
        output = self.base/'review.json'
        with contextlib.redirect_stdout(io.StringIO()), patch.object(review, 'load_tasks', return_value=({}, {'task': {'success': self.predicate}})):
            self.assertEqual(review.main(['--input', str(source), '--out', str(output), '--rescore', '--cell-id', 'cell',
                                          '--verifier-source', 'task='+str(self.frozen_source)]), 0)
        self.assertEqual(json.loads(output.read_text())['summary']['matches_recorded'], 1)
        self.assertEqual(source.read_bytes(), before)
        for mapping in (['task='+str(self.frozen_source)]*2, ['missing-separator'], ['task=']):
            with self.subTest(mapping=mapping), contextlib.redirect_stderr(io.StringIO()):
                argv = ['--input', str(source), '--out', str(self.base/'bad.json')]
                for item in mapping:argv += ['--verifier-source', item]
                with self.assertRaises(SystemExit):review.main(argv)

    def test_legacy_v1_plain_snapshot_remains_readable(self):
        (self.source/'check.py').write_text('public\n', encoding='utf-8')
        self.frozen = freeze_verifiers(self.predicate, self.source)
        row = self.capture()
        def legacy(manifest):
            manifest['schema'] = 'verseshell.final-workspace/v1'
            for entry in manifest['files']:entry.pop('storage', None)
        reference = self.forge(row, legacy)
        reference.pop('protected_reference_count', None)
        restored = self.base/'legacy'
        snapshots.restore(self.artifacts, reference, restored)
        self.assertEqual((restored/'check.py').read_text(), 'public\n')


if __name__ == '__main__':
    unittest.main()
