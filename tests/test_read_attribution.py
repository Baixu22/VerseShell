"""Attribution must account for the digest actually projected, without altering payloads."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from read_path_breakdown import attribute, project, variant_no_digest
from live_agent_loop import parse_aci_result


class ReadAttributionTests(unittest.TestCase):
    def test_both_digest_forms_are_removed_at_top_level_and_in_batch(self):
        entry = {'hash': '0123456789abcdef', 'content_hash': 'sha256:' + 'a' * 64,
                 'total_lines': 1, 'lines': [{'line': 1, 'text': 'unchanged text'}]}
        for data in (entry, {'files': [{'path': 'a.py', **entry}]}):
            for compact in (False, True):
                with self.subTest(batch='files' in data, compact=compact):
                    envelope = {'ok': True, 'data': copy.deepcopy(data)}
                    original = copy.deepcopy(envelope)
                    stripped = variant_no_digest(envelope)
                    raw = project(envelope, compact=compact)
                    no_digest = project(stripped, compact=compact)
                    self.assertNotIn('content_hash', no_digest)
                    self.assertEqual(envelope, original)
                    expected = dict(parse_aci_result(raw))
                    if 'files' in expected:
                        expected['files'][0].pop('content_hash')
                    else:
                        expected.pop('content_hash')
                    self.assertEqual(parse_aci_result(no_digest), expected)
                    self.assertGreater(attribute(envelope, compact=compact)['parts']['digest'], 0)
                    self.assertEqual(attribute(envelope, compact=compact)['parts']['digest'], len(raw) - len(no_digest))

    def test_full_digest_fallback_and_absent_digest(self):
        for data, expected in [({'content_hash': 'sha256:'+'a'*64}, True), ({}, False)]:
            result = attribute({'ok': True, 'data': data}, compact=True)
            self.assertEqual(result['parts']['digest'] > 0, expected)
            self.assertEqual(sum(result['parts'].values()), result['total_chars'])


if __name__ == '__main__':
    unittest.main()
