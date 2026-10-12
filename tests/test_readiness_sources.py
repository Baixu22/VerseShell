"""Readiness source coverage and manifest completeness; no endpoint calls.

Three gaps are guarded here:

1. ``prelive_check.source_hashes`` must cover the report/acceptance CLI in
   ``bench/aci/scorers/score.py``. It gates claims from collection reports;
   independent task scoring remains in the runner. An untracked CLI edit
   would otherwise leave an obsolete readiness receipt usable.
2. ``live_round.verify_readiness`` must require the recorded dict to equal
   ``source_hashes(ROOT)`` exactly -- it used to only re-hash the entries the receipt
   listed, so a receipt could omit whole files and still pass. Now a missing entry or
   an undeclared extra entry is refused.
3. Endpoint probe receipts must match the probe-source digest already bound by
   readiness; a runner fingerprint alone cannot validate a changed probe contract.

``verify_readiness`` does ``from prelive_check import source_hashes`` inside the
function body, so the seam patched here is ``prelive_check.source_hashes``.

Every readiness is built in a temporary root with a mocked toolchain, AE binary,
analysis plan and endpoint probe, so the strict entry gate is exercised end to end
instead of only testing rejections. No endpoint, no model call.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'bench/aci/runners')]
import live_round as round_
import prelive_check as prelive

SCORER = 'bench/aci/scorers/score.py'
TOOLCHAIN = ('python', 'node', 'cargo', 'rustc', 'npm')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SourceCoverageTests(unittest.TestCase):
    """source_hashes must include the scorer and notice it changing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/SCORER).parent.mkdir(parents=True)
        (self.root/'tools').mkdir()
        (self.root/'tools'/'live_round.py').write_text('# runner\n', encoding='utf-8')
        self.scorer = self.root/SCORER
        self.scorer.write_text('def score(rows):\n    return 1.0\n', encoding='utf-8')
        self.real_source_hashes = prelive.source_hashes

    def current_sources(self):
        return self.real_source_hashes(self.root)

    def test_scorer_is_included(self):
        digests = self.current_sources()
        self.assertIn(SCORER, digests, 'scorer is graded code but is not covered by source_hashes')
        self.assertEqual(digests[SCORER], sha(self.scorer))

    def test_editing_the_scorer_changes_its_hash(self):
        before = self.current_sources()[SCORER]
        self.scorer.write_text('def score(rows):\n    return 0.0\n', encoding='utf-8')
        after = self.current_sources()
        self.assertNotEqual(after[SCORER], before)
        self.assertEqual(after[SCORER], sha(self.scorer))

    def test_adding_a_second_scorer_is_covered(self):
        extra = self.root/'bench/aci/scorers/extra.py'
        extra.write_text('# second scorer\n', encoding='utf-8')
        self.assertIn('bench/aci/scorers/extra.py', self.current_sources())


class VerifyReadinessTests(unittest.TestCase):
    """verify_readiness: exact manifest equality plus every gate that follows it."""

    FINGERPRINT = 'fingerprint-abc'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tool = self.root/'fake-interpreter'
        self.tool.write_bytes(b'fake interpreter bytes')
        self.binary = self.root/'ae-binary'
        self.binary.write_bytes(b'fake AE binary')
        self.plan = self.root/'plan.json'
        self.plan.write_text('{"minimum_seeds": 5, "minimum_tasks": 30}\n', encoding='utf-8')
        (self.root/SCORER).parent.mkdir(parents=True)
        self.scorer = self.root/SCORER
        self.scorer.write_text('# scorer under readiness\n', encoding='utf-8')
        (self.root/'tools').mkdir()
        self.runner = self.root/'tools'/'live_round.py'
        self.runner.write_text('# runner under readiness\n', encoding='utf-8')
        self.probe_source = self.root/'tools'/'prelive_probe.py'
        self.probe_source.write_text('# probe under readiness\n', encoding='utf-8')
        (self.root/'bench/aci/runners').mkdir(parents=True)
        (self.root/'bench/aci/runners'/'live_agent_loop.py').write_text('# runner module\n', encoding='utf-8')
        # Bind the real function now: current_sources() must not re-enter the patch below.
        self.real_source_hashes = prelive.source_hashes

    def current_sources(self):
        """Exactly what the fixed source_hashes() reports for this temporary root."""
        return self.real_source_hashes(self.root)

    def run_verify(self, recorded, expected=None, probe_overrides=None, readiness_overrides=None,
                   probe_source_missing=False):
        """Drive verify_readiness with a mocked toolchain, binary, plan and probe.

        `expected` is what source_hashes(ROOT) returns during the call, which is the
        value the strict gate compares the receipt against.
        """
        probe = {'schema': 'verseshell.endpoint-readiness/v1', 'pass': True,
                 'requested_model': 'model-x', 'api_base': 'https://example.invalid',
                 'max_tokens': 4096, 'source_fingerprint': self.FINGERPRINT,
                 'probe_source_sha256': sha(self.probe_source)}
        probe.update(probe_overrides or {})
        if probe_source_missing:
            probe.pop('probe_source_sha256')
        readiness = {
            'schema': 'verseshell.prelive-readiness/v1',
            'ready_for_live': True,
            'source_sha256': recorded,
            'toolchain': {name: {'path': str(self.tool.resolve()), 'sha256': sha(self.tool)}
                          for name in TOOLCHAIN},
            'binary_sha256': sha(self.binary),
            'analysis_plan_sha256': sha(self.plan),
        }
        readiness.update(readiness_overrides or {})
        rpath = self.root/'readiness.json'
        ppath = self.root/'probe.json'
        rpath.write_text(json.dumps(readiness), encoding='utf-8')
        ppath.write_text(json.dumps(probe), encoding='utf-8')

        harness = mock.Mock()
        harness.AE = self.binary
        harness.evidence_fingerprint = lambda globs: self.FINGERPRINT
        harness.EVIDENCE_GLOBS = ['bench/aci/runners/*.py']
        with mock.patch.object(round_, 'ROOT', self.root), \
             mock.patch.object(round_, 'harness', harness), \
             mock.patch.object(prelive, 'source_hashes',
                               lambda root=None: self.current_sources() if expected is None else expected), \
             mock.patch.object(round_.shutil, 'which', lambda name: str(self.tool)), \
             mock.patch.object(round_.sys, 'executable', str(self.tool)):
            return round_.verify_readiness(rpath, ppath, 'model-x',
                                           'https://example.invalid', 4096, self.plan)

    def test_complete_receipt_passes_every_gate(self):
        """Success case: all checks must actually run, not just the entry gate."""
        sources = self.current_sources()
        self.assertIn(SCORER, sources, 'precondition: scorer must be inventoried')
        self.run_verify(dict(sources))

    def test_current_probe_source_digest_passes(self):
        sources = self.current_sources()
        self.assertEqual(sources['tools/prelive_probe.py'], sha(self.probe_source))
        self.run_verify(dict(sources),
                        probe_overrides={'probe_source_sha256': sources['tools/prelive_probe.py']})

    def test_missing_probe_source_digest_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_verify(self.current_sources(), probe_source_missing=True)

    def test_wrong_probe_source_digest_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_verify(self.current_sources(), probe_overrides={'probe_source_sha256': '0' * 64})

    def test_empty_probe_source_digest_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_verify(self.current_sources(), probe_overrides={'probe_source_sha256': ''})

    def test_scorer_alone_is_not_enough(self):
        """A receipt carrying only the scorer omits other inventoried files."""
        sources = self.current_sources()
        self.assertGreater(len(sources), 1, 'precondition: the temporary root has several sources')
        with self.assertRaises(ValueError):
            self.run_verify({SCORER: sources[SCORER]})

    def test_omitted_scorer_is_refused(self):
        """Gap 2 proper: every listed file still matches, the scorer is simply absent.

        The old per-entry loop accepted this, because it only re-hashed what the
        receipt happened to contain and never noticed the missing scorer.
        """
        recorded = {name: digest for name, digest in self.current_sources().items()
                    if name != SCORER}
        self.assertNotEqual(recorded, {}, 'precondition: the receipt must stay non-empty')
        self.assertNotIn(SCORER, recorded)
        with self.assertRaises(ValueError):
            self.run_verify(recorded)

    def test_undeclared_extra_entry_is_refused(self):
        sources = dict(self.current_sources())
        sources['src/ghost.rs'] = '0' * 64
        with self.assertRaises(ValueError):
            self.run_verify(sources)

    def test_wrong_digest_is_refused(self):
        sources = dict(self.current_sources())
        sources[SCORER] = '0' * 64
        with self.assertRaises(ValueError):
            self.run_verify(sources)

    def test_scorer_code_change_invalidates_an_old_receipt(self):
        """The regression this guards: grading code changed, receipt still claims ready."""
        recorded = dict(self.current_sources())
        self.scorer.write_text('# scorer CHANGED after readiness\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_verify(recorded)

    def test_gate_failure_after_the_entry_check_is_still_reported(self):
        """Proves the run reaches the later gates instead of short-circuiting on entry."""
        sources = self.current_sources()
        recorded_binary = sha(self.binary)
        self.binary.write_bytes(b'changed AE binary after the receipt was written')
        with self.assertRaises(ValueError) as caught:
            self.run_verify(dict(sources),
                            readiness_overrides={'binary_sha256': recorded_binary})
        self.assertIn('ae binary changed since readiness', str(caught.exception))


if __name__ == '__main__':
    unittest.main()