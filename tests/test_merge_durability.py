"""Offline durability regressions for bench/aci/runners/merge_live_runs.py.

Scope (TF-0122 evidence integrity, no network, no real disk pressure):

* recorded ``sources[].sha256`` must equal the sha256 of the exact input bytes
  that were parsed (BOM / CRLF included), and must be rechecked before commit;
* a source that changes or disappears while summaries are computed must abort
  with exit code 2 and leave the previous output untouched;
* ``--out`` may not alias an input by path or by file identity (hard link);
* the output must be committed through ``live_journal.atomic_json`` so a failing
  write/replace (ENOSPC) keeps the previous output and removes the temp file;
* an input that cannot be read must be refused without touching the output.

The ``payload()`` builder mirrors ``tests/test_live_preflight.py``; it is copied
instead of imported so this module stays independent of that TestCase.
"""
import contextlib
import codecs
import copy
import errno
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'bench/aci/runners'))
sys.path.insert(0, str(REPO / 'tools'))
import live_journal
import merge_live_runs as merger
from live_identity import validate_run

SENTINEL = b'sentinel-output-must-survive\n'


def payload(seed=42):
    cfg = dict(model='offline', api_base='http://offline.invalid/v1/responses', protocol='responses',
               caps='file.read', max_turns=8, max_tokens=16384, temperature=0, exclude_tools=[],
               tasks=['task'], conditions=['verseshell_aci'], repeat=1, collection_id='test-study', seed=seed)
    evidence = dict(globs=['test'], fingerprint='original-acquisition')
    identity = {k: v for k, v in cfg.items() if k != 'seed'}
    identity.update(seeds=[seed], task_set_version='test', evidence=evidence, binary_sha256='binary')
    row = dict(task_id='task', condition='verseshell_aci', model='offline', seed=seed, run_index=0,
               success=True, tool_calls=1, observation_tokens=10, elapsed_ms=1, turns=1, trajectory=[])
    return dict(schema='test', mode='live', task_set_version='test', git_rev='original-revision',
                evidence=evidence, run_identity=identity, live_config=cfg, rows=[row])


def write_source(path, seed):
    """Write a source as BOM-prefixed CRLF JSON and return the exact bytes."""
    body = json.dumps(payload(seed), indent=1, ensure_ascii=False).replace('\n', '\r\n') + '\r\n'
    raw = codecs.BOM_UTF8 + body.encode('utf-8')
    path.write_bytes(raw)
    return raw


class MergeDurabilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / 'out.json'
        self.out.write_bytes(SENTINEL)
        self.addCleanup(self._tmp.cleanup)

    def sources(self, seeds=(42, 43)):
        raws = []
        for index, seed in enumerate(seeds):
            path = self.root / f'with_seed{seed}.json'
            raws.append(write_source(path, seed))
        return [str(self.root / f'with_seed{seed}.json') for seed in seeds], raws

    def run_merge(self, inputs, out=None, hook=None):
        """Run the CLI offline; optionally wrap the summary hook with ``hook``."""
        target = Path(out) if out is not None else self.out
        with contextlib.ExitStack() as stack:
            if hook is not None:
                real = merger.refresh_summaries
                stack.enter_context(patch.object(merger, 'refresh_summaries',
                                                 side_effect=lambda *a, **k: hook(real, *a, **k)))
            stdout = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            rc = merger.main([*inputs, '--out', str(target)])
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_normal_merge_records_exact_input_bytes_for_bom_crlf_sources(self):
        inputs, raws = self.sources()
        rc, _out, _err = self.run_merge(inputs)
        self.assertEqual(rc, 0)
        merged = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual([s['sha256'] for s in merged['sources']],
                         [hashlib.sha256(raw).hexdigest() for raw in raws])
        self.assertEqual(merged['live_config']['seeds'], [42, 43])
        self.assertEqual([s['path'] for s in merged['sources']], inputs)
        # real aggregation, not a stub
        self.assertEqual(merged['aggregate']['n_rows'], 2)
        self.assertIn('comparison', merged)
        validate_run(merged)

    def test_source_changed_during_summaries_is_refused_with_output_preserved(self):
        inputs, _raws = self.sources()
        target = Path(inputs[0])

        def mutate(original, *a, **k):
            result = original(*a, **k)
            write_source(target, 99)
            return result

        rc, _out, err = self.run_merge(inputs, hook=mutate)
        self.assertEqual(rc, 2)
        self.assertIn('source changed during merge', err)
        self.assertIn('previous output preserved', err)
        self.assertEqual(self.out.read_bytes(), SENTINEL)

    def test_source_deleted_during_summaries_is_refused_with_output_preserved(self):
        inputs, _raws = self.sources()
        victim = Path(inputs[1])

        def drop(original, *a, **k):
            result = original(*a, **k)
            victim.unlink()
            return result

        rc, _out, _err = self.run_merge(inputs, hook=drop)
        self.assertEqual(rc, 2)
        self.assertEqual(self.out.read_bytes(), SENTINEL)
        self.assertFalse(victim.exists())

    def test_out_equal_to_input_path_is_refused_and_source_bytes_survive(self):
        inputs, raws = self.sources()
        rc, _out, err = self.run_merge(inputs, out=inputs[0])
        self.assertEqual(rc, 2)
        self.assertIn('output aliases an input artifact', err)
        self.assertIn('output preserved', err)
        self.assertEqual(Path(inputs[0]).read_bytes(), raws[0])
        self.assertEqual(self.out.read_bytes(), SENTINEL)

    def test_out_hardlinked_to_input_is_refused_and_source_bytes_survive(self):
        inputs, raws = self.sources()
        alias = self.root / 'alias.json'
        try:
            os.link(inputs[0], alias)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest(f'hard links unavailable here: {exc}')
        rc, _out, err = self.run_merge(inputs, out=str(alias))
        self.assertEqual(rc, 2)
        self.assertIn('output aliases an input artifact', err)
        self.assertIn('output preserved', err)
        self.assertEqual(Path(inputs[0]).read_bytes(), raws[0])
        self.assertEqual(alias.read_bytes(), raws[0])
        self.assertEqual(self.out.read_bytes(), SENTINEL)

    def test_commit_replace_failure_keeps_previous_output_and_cleans_temp(self):
        inputs, _raws = self.sources()
        error = OSError(errno.ENOSPC, 'No space left on device')
        with patch.object(os, 'replace', side_effect=error):
            rc, _out, err = self.run_merge(inputs)
        self.assertEqual(rc, 2)
        self.assertIn('previous output preserved', err)
        self.assertEqual(self.out.read_bytes(), SENTINEL)
        leftovers = [p.name for p in self.root.iterdir() if p.suffix == '.tmp']
        self.assertEqual(leftovers, [])

    def test_unreadable_or_missing_input_is_refused_without_touching_output(self):
        inputs, raws = self.sources()
        unreadable = self.root / 'not-a-file.json'
        unreadable.mkdir()
        missing = self.root / 'gone.json'
        for bad in (str(unreadable), str(missing)):
            with self.subTest(input=bad):
                rc, _out, _err = self.run_merge([inputs[0], bad])
                self.assertEqual(rc, 2)
                self.assertEqual(self.out.read_bytes(), SENTINEL)
                self.assertEqual(Path(inputs[0]).read_bytes(), raws[0])


if __name__ == '__main__':
    unittest.main()