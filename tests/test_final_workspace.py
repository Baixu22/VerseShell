"""Offline grading-input capture, integrity and reconstruction boundaries."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import final_workspace as snapshots
import final_workspace_audit as review
import live_agent_loop as harness
from grading_contract import freeze_verifiers, guarded_success
from live_journal import ObservationStore
import test_live_recovery as recovery


class FinalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base/'source'; self.source.mkdir()
        self.artifacts = self.base/'artifacts'; self.artifacts.mkdir()
        self.store = snapshots.FinalWorkspaceStore(self.artifacts/'final-workspaces')
        self.predicate = {'type': 'file_equals', 'path': 'answer.txt', 'equals': 'ok'}
        (self.source/'answer.txt').write_text('ok', encoding='utf-8')

    def capture(self, cell='cell', success=True):
        contract = freeze_verifiers(self.predicate, self.source)
        reference = self.store.capture(self.source, cell_id=cell, task_id=cell,
                                       predicate=self.predicate, protected_verifiers=contract)
        return {'cell_id': cell, 'task_id': cell, 'success': success,
                'protected_verifiers': contract, 'final_workspace': reference}

    def forged_reference(self, row, mutate):
        manifest, _ = snapshots.load_manifest(self.artifacts, row['final_workspace'])
        mutate(manifest)
        body = json.dumps(manifest, sort_keys=True).encode()
        sha = snapshots.digest(body)
        target = self.store.directory/'manifests'/(sha+'.json')
        target.write_bytes(body)
        return {**row['final_workspace'], 'path': 'final-workspaces/manifests/'+sha+'.json', 'sha256': sha}

    def test_roundtrip_bytes_empty_directories_and_shared_ignored_scope(self):
        (self.source/'binary.bin').write_bytes(b'\x00\xff\x81')
        (self.source/'empty').mkdir()
        (self.source/'target').mkdir(); (self.source/'target/cache').write_text('excluded')
        row = self.capture()
        restored = self.base/'restored'
        manifest = snapshots.restore(self.artifacts, row['final_workspace'], restored)
        self.assertEqual((restored/'answer.txt').read_bytes(), b'ok')
        self.assertEqual((restored/'binary.bin').read_bytes(), b'\x00\xff\x81')
        self.assertTrue((restored/'empty').is_dir())
        self.assertFalse((restored/'target').exists())
        self.assertEqual(manifest['stage'], 'before_grading_evaluator')
        with self.assertRaisesRegex(ValueError, 'new destination'):
            snapshots.restore(self.artifacts, row['final_workspace'], restored)

    def test_identical_content_is_deduplicated_without_overwrite(self):
        first = self.capture('first')
        before = {p.name: p.read_bytes() for p in (self.store.directory/'blobs').iterdir()}
        second = self.capture('second')
        self.assertNotEqual(first['final_workspace']['sha256'], second['final_workspace']['sha256'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.store.directory/'blobs').iterdir()})

    def test_manifest_and_blob_tampering_fail_before_restore(self):
        row = self.capture()
        manifest, store = snapshots.load_manifest(self.artifacts, row['final_workspace'])
        blob = store/'blobs'/manifest['files'][0]['sha256']
        blob.write_bytes(b'NO')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            snapshots.restore(self.artifacts, row['final_workspace'], self.base/'must-not-exist')
        self.assertFalse((self.base/'must-not-exist').exists())
        reference = {**row['final_workspace'], 'sha256': '0'*64}
        with self.assertRaisesRegex(ValueError, 'manifest hash'):
            snapshots.load_manifest(self.artifacts, reference)

    def test_traversal_reserved_redirected_and_incomplete_paths_fail_closed(self):
        row = self.capture()
        for path in ('.', '../escape', '/absolute', 'C:/escape', 'bad\\path', 'NUL', 'nested/answer.txt'):
            with self.subTest(path=path):
                reference = self.forged_reference(row, lambda m: m['files'][0].update(path=path))
                with self.assertRaises(ValueError):snapshots.restore(self.artifacts, reference, self.base/'escape-target')
                self.assertFalse((self.base/'escape-target').exists())
        real = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda p: p == self.source/'answer.txt' or real(p)):
            with self.assertRaisesRegex(ValueError, 'redirected'):self.capture()

    def test_malformed_manifest_is_an_unknown_row_not_an_aborted_audit(self):
        good = self.capture()
        for invalid in (None, [], 'invalid', 1):
            with self.subTest(manifest=invalid):
                body = json.dumps(invalid).encode()
                sha = snapshots.digest(body)
                (self.store.directory/'manifests'/(sha+'.json')).write_bytes(body)
                bad = {**good, 'final_workspace': {**good['final_workspace'],
                       'path': 'final-workspaces/manifests/'+sha+'.json', 'sha256': sha}}
                result = review.audit({'rows': [bad, good]}, self.artifacts)
                self.assertEqual(result['summary']['snapshots_verified'], 1)
                self.assertEqual(result['rows'][0]['status'], 'invalid_snapshot')
                self.assertIsNone(result['rows'][0]['independent_success'])
        for frozen in (None, [], {'test.py': 'not-a-digest'}):
            with self.subTest(protected_verifiers=frozen):
                reference = self.forged_reference(good, lambda m: m.update(protected_verifiers=frozen))
                bad = {**good, 'protected_verifiers': frozen, 'final_workspace': reference}
                with patch.object(review, 'check_success') as evaluator:
                    result = review.review_row(bad, self.artifacts, task={'success': self.predicate}, rescore=True)
                self.assertEqual(result['status'], 'invalid_snapshot')
                self.assertIsNone(result['independent_success'])
                self.assertFalse(result['rescore_attempted'])
                evaluator.assert_not_called()

    def test_limits_and_credentials_never_publish_available_manifest(self):
        for kwargs in ({'max_files': 0}, {'max_bytes': 1}):
            store = snapshots.FinalWorkspaceStore(self.artifacts/'bounded', **kwargs)
            with self.assertRaisesRegex(ValueError, 'limit'):
                store.capture(self.source, cell_id='x', task_id='x', predicate={}, protected_verifiers={})
            self.assertFalse((store.directory/'manifests').exists())
        secret = 'offline-credential-do-not-persist'
        (self.source/'answer.txt').write_text(secret)
        store = snapshots.FinalWorkspaceStore(self.artifacts/'secret', (secret,))
        with self.assertRaisesRegex(ValueError, 'credential'):
            store.capture(self.source, cell_id='x', task_id='x', predicate={}, protected_verifiers={})
        self.assertFalse((store.directory/'manifests').exists())
        self.assertTrue(all(secret.encode() not in p.read_bytes() for p in store.directory.rglob('*') if p.is_file()))

    def test_files_changing_during_capture_are_not_published(self):
        scan = self.store._scan
        def changing(workspace, save, protected_verifiers):
            result = scan(workspace, save, protected_verifiers)
            if save:(self.source/'answer.txt').write_text('changed')
            return result
        with patch.object(self.store, '_scan', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed during capture'):self.capture()
        self.assertFalse((self.store.directory/'manifests').exists())

    def test_capture_is_of_pre_evaluation_copy_not_after_effects(self):
        captured = []
        def before(workspace):
            captured.append(self.store.capture(workspace, cell_id='cell', task_id='cell',
                                               predicate=self.predicate, protected_verifiers={}))
        def evaluate(predicate, workspace):
            self.assertNotEqual(workspace, self.source)
            (workspace/'answer.txt').write_text('after evaluation')
            return True, 'offline side effect'
        self.assertEqual(guarded_success(self.predicate, self.source, {}, evaluate, before_evaluate=before)[0], True)
        restored = self.base/'restored'
        snapshots.restore(self.artifacts, captured[0], restored)
        self.assertEqual((restored/'answer.txt').read_text(), 'ok')
        self.assertEqual((self.source/'answer.txt').read_text(), 'ok')

    def test_protected_verifier_failure_does_not_capture_or_evaluate(self):
        (self.source/'test_check.py').write_text('original')
        contract = freeze_verifiers(self.predicate, self.source)
        (self.source/'test_check.py').write_text('changed')
        with patch('builtins.print'), patch.object(harness, 'check_success') as evaluator:
            callback = unittest.mock.Mock()
            result = guarded_success(self.predicate, self.source, contract, evaluator, before_evaluate=callback)
        self.assertFalse(result[0]); evaluator.assert_not_called(); callback.assert_not_called()

    def test_independent_rescore_matches_pass_and_fail_with_coverage_denominator(self):
        passing = self.capture('pass', True)
        (self.source/'answer.txt').write_text('wrong')
        failing = self.capture('fail', False)
        missing = {'cell_id': 'missing', 'task_id': 'missing', 'success': True}
        payload = {'rows': [passing, failing, missing]}; original = copy.deepcopy(payload)
        result = review.audit(payload, self.artifacts,
                              tasks={key: {'success': self.predicate} for key in ('pass', 'fail')},
                              rescore_ids=['pass', 'fail'], work_dir=self.base/'score-copies')
        self.assertEqual(result['summary']['rows'], 3)
        self.assertEqual(result['summary']['snapshots_verified'], 2)
        self.assertEqual(result['summary']['independently_scored'], 2)
        self.assertEqual(result['summary']['matches_recorded'], 2)
        self.assertIsNone(result['rows'][2]['independent_success'])
        self.assertEqual(payload, original)

    def test_default_audit_never_executes_and_legacy_missing_is_not_failure(self):
        row = self.capture()
        with patch.object(review, 'check_success') as evaluator:
            result = review.audit({'rows': [row, {'success': False}]}, self.artifacts)
        evaluator.assert_not_called()
        self.assertEqual(result['summary']['rescore_attempted'], 0)
        self.assertIsNone(result['rows'][1]['independent_success'])
        self.assertFalse(result['rows'][1]['recorded_success'])

    def test_unavailable_evaluator_is_not_a_failed_or_matching_rescore(self):
        row = self.capture(success=False)
        with patch.object(review, 'check_success', return_value=(None, 'unverified: missing offline toolchain')):
            result = review.audit({'rows': [row]}, self.artifacts,
                                  tasks={'cell': {'success': self.predicate}}, rescore_ids=['cell'])
        self.assertEqual(result['summary']['snapshots_verified'], 1)
        self.assertEqual(result['summary']['rescore_attempted'], 1)
        self.assertEqual(result['summary']['independently_scored'], 0)
        self.assertEqual(result['summary']['matches_recorded'], 0)
        self.assertEqual(result['summary']['disagrees_with_recorded'], 0)
        self.assertEqual(result['rows'][0]['status'], 'unverified')
        self.assertIsNone(result['rows'][0]['independent_success'])

    def test_wrong_identity_predicate_or_grader_cannot_be_recertified(self):
        row = self.capture()
        wrong = {**row, 'cell_id': 'other'}
        self.assertEqual(review.review_row(wrong, self.artifacts)['status'], 'invalid_snapshot')
        result = review.review_row(row, self.artifacts, task={'success': {}}, rescore=True)
        self.assertEqual(result['status'], 'not_comparable')
        with patch.object(review, 'grader_hashes', return_value={}):
            result = review.review_row(row, self.artifacts, task={'success': self.predicate}, rescore=True)
        self.assertEqual(result['status'], 'not_comparable')
        self.assertFalse(result['rescore_attempted'])

    def model_row(self, capture_error=None):
        response = {'usage': {'prompt_tokens': 2, 'completion_tokens': 1},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': 'done'}}]}
        task = {'id': 'cell', 'workspace_fixture': 'offline', 'prompt': 'x', 'success': self.predicate}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(harness, 'prepare_workspace', return_value=self.source))
            stack.enter_context(patch.object(harness, 'chat_completion', return_value=response))
            if capture_error:stack.enter_context(patch.object(harness.FinalWorkspaceStore, 'capture', side_effect=capture_error))
            return harness.run_agent_loop(task, 'raw_shell', model='offline', api_key='not-a-real-credential-000',
                                          base_url='http://offline', cell_id='cell',
                                          observation_store=ObservationStore(self.artifacts/'observations'))

    def test_live_row_retains_replayable_input_after_workspace_cleanup(self):
        row = self.model_row()
        self.assertTrue(row['success'])
        self.assertFalse(self.source.exists())
        self.assertEqual(row['final_workspace']['state'], 'available')
        result = review.review_row(row, self.artifacts, task={'success': self.predicate},
                                   rescore=True, work_dir=self.base/'score-copies')
        self.assertTrue(result['independent_success'])
        self.assertTrue(result['matches_recorded'])

    def test_verifier_rejection_explains_why_grading_input_was_not_captured(self):
        verifier = self.source/'test_check.py'
        verifier.write_text('original')
        def freeze_then_tamper(*args):
            frozen = freeze_verifiers(*args)
            verifier.write_text('changed')
            return frozen
        with patch.object(harness, 'freeze_verifiers', side_effect=freeze_then_tamper):
            row = self.model_row()
        self.assertFalse(row['success'])
        self.assertEqual(row['final_workspace']['state'], 'unavailable')
        self.assertIn('protected verifier changed', row['final_workspace']['reason'])
        self.assertFalse(row['evidence_storage_fault'])

    def test_capture_write_failure_preserves_original_score_but_signals_pause(self):
        row = self.model_row(OSError(28, 'injected full disk'))
        self.assertTrue(row['success'])
        self.assertEqual(row['final_workspace']['state'], 'unavailable')
        self.assertTrue(row['evidence_storage_fault'])
        self.assertIsNone(row['harness_fault'])

    def test_collection_commits_storage_fault_row_and_stops_before_next_cell(self):
        out = self.base/'run.json'
        args = ['--model','offline','--api-key','test','--tasks','rust_fix_compile_error,rust_add_unit_test',
                '--conditions','raw_shell','--seed','42','--out',str(out)]
        def result(task, condition, **kwargs):
            return {**recovery.RecoveryTests.row(task, condition, **kwargs), 'evidence_storage_fault': True,
                    'final_workspace': {'state': 'unavailable', 'reason': 'injected disk failure'}}
        with patch.object(harness, 'run_agent_loop', side_effect=result) as model, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(args), 75)
        self.assertEqual(model.call_count, 1)
        records = [json.loads(line) for line in Path(str(out)+'.rows.jsonl').read_text().splitlines()]
        self.assertTrue(records[1]['success'])
        self.assertEqual(json.loads(Path(str(out)+'.pause.json').read_text())['reason'], 'evidence_storage_fault')
        self.assertFalse(out.exists())

    def test_cli_is_readonly_and_requires_explicit_rescore_selection(self):
        source = self.artifacts/'run.json'; source.write_text(json.dumps({'rows': [{'success': True}]}))
        output = self.base/'review.json'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(['--input', str(source), '--out', str(output)]), 0)
            for extra in ([], ['--rescore']):
                with self.assertRaises(SystemExit):review.main(['--input', str(source), '--out', str(output), *extra])
            with self.assertRaises(SystemExit):
                review.main(['--input', str(source), '--out', str(self.base/'new.json'), '--rescore'])
        self.assertEqual(json.loads(source.read_text())['rows'][0]['success'], True)


if __name__ == '__main__':
    unittest.main()
