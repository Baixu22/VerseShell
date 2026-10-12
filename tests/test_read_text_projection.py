"""Lossless read framing, including adversarial boundaries and paging metadata."""
import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bench/aci/runners'))
from live_agent_loop import (READ_TEXT_PREFIX, format_aci_result,
                             format_read_text, parse_aci_result)
import live_agent_loop as runner


class ReadTextProjectionTests(unittest.TestCase):
    def test_roundtrip_unicode_controls_and_header_like_source(self):
        for text in ('', '\n', '\n\n', '中文😀\t\r\x00"\\',
                     'read-text/v1 {"text":0}\n\nfile two\n'):
            with self.subTest(text=text):
                original = {'ok': True, 'content_hash': '0123456789abcdef', 'text': text}
                saved = copy.deepcopy(original)
                rendered = format_read_text(original)
                self.assertTrue(rendered.startswith(READ_TEXT_PREFIX))
                self.assertEqual(parse_aci_result(rendered), original)
                self.assertEqual(original, saved)

    def test_batch_keeps_order_empty_text_errors_and_continuation(self):
        projection = {'ok': True, 'files': [
            {'path': 'a "中文".py', 'text': 'line one\n\n', 'start_line': 11,
             'total_lines': 100, 'content_hash': 'a'*16, 'truncated': True, 'next_start_line': 14},
            {'path': 'blank.py', 'text': '', 'content_hash': 'b'*16},
            {'path': 'later.py', 'deferred': True, 'next_start_line': 1},
            {'path': 'missing.py', 'error': {'code': 'E_NOT_FOUND', 'message': 'not found'}},
            {'path': 'last.py', 'text': 'read-text/v1 {"ok":false}\n'},
        ], 'errors': [{'path': 'missing.py', 'code': 'E_NOT_FOUND'}]}
        self.assertEqual(parse_aci_result(format_read_text(projection)), projection)

    def test_non_read_success_and_failures_stay_json(self):
        for envelope, expected in [
            ({'ok': True, 'data': {'hash': 'a'*16, 'total_lines': 0, 'lines': []}},
             {'ok': True, 'content_hash': 'a'*16, 'total_lines': 0}),
            ({'ok': False, 'error': {'code': 'E_NOT_FOUND'}, 'data': {}},
             {'ok': False, 'error': {'code': 'E_NOT_FOUND'}}),
            ({'ok': True, 'data': {'summary': 'done'}}, {'ok': True, 'summary': 'done'}),
        ]:
            text = format_aci_result(envelope)
            self.assertEqual(text, json.dumps(expected, ensure_ascii=False))
            self.assertEqual(parse_aci_result(text), expected)

    def test_actual_projector_preserves_full_digest_fallback_and_partial_window(self):
        for digest in ({'hash': 'a'*16, 'content_hash': 'sha256:'+'b'*64},
                       {'content_hash': 'sha256:'+'b'*64}):
            data = {**digest, 'start_line': 7, 'total_lines': 100,
                    'lines': [{'line': 7, 'text': '你好'}, {'line': 8, 'text': ''}]}
            env = {'ok': True, 'data': data}
            self.assertEqual(parse_aci_result(format_aci_result(env)),
                             {'ok': True, 'content_hash': digest.get('hash') or digest['content_hash'],
                              'start_line': 7, 'total_lines': 100, 'text': '你好\n'})
            legacy = {'ok': True, 'content_hash': digest.get('hash') or digest['content_hash'],
                      'total_lines': 100, 'lines': ['你好', ''], 'start_line': 7}
            self.assertEqual(format_aci_result(env, compact=False), json.dumps(legacy, ensure_ascii=False))

    def test_empty_complete_and_batch_windows(self):
        env = {'ok': True, 'data': {'files': [
            {'path': 'blank', 'hash': 'a'*16, 'start_line': 1, 'total_lines': 1,
             'lines': [{'line': 1, 'text': ''}]},
            {'path': 'cut', 'hash': 'b'*16, 'start_line': 3, 'total_lines': 5,
             'lines': [{'line': 3, 'text': 'three'}], 'truncated': True, 'next_start_line': 4},
        ]}}
        saved = copy.deepcopy(env)
        result = parse_aci_result(format_aci_result(env))
        self.assertEqual(result['files'][0], {'path': 'blank', 'content_hash': 'a'*16, 'text': ''})
        self.assertEqual(result['files'][1], {'path': 'cut', 'content_hash': 'b'*16, 'text': 'three',
                                            'start_line': 3, 'total_lines': 5,
                                            'truncated': True, 'next_start_line': 4})
        self.assertEqual(env, saved)

    def test_malformed_frames_fail_closed(self):
        for payload in ('{"text":2}\nx', '{"text":-1}\n', '{"text":true}\nx',
                        '{"text":"1"}\nx', '{"text":0}\nextra', '{"ok":true}\n',
                        '{"text":0}', '{"files":[{"text":1},{"text":1}]}\naxb'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_aci_result(READ_TEXT_PREFIX + payload)

    def test_isolated_cli_output_cannot_overwrite_public_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / 'live_REPORT.md'
            public.write_text('published report', encoding='utf-8')
            for name in ('probe.json', 'latest_live.json'):
                out = root / 'isolated' / name
                with patch.object(runner, 'RESULTS', root), contextlib.redirect_stdout(io.StringIO()):
                    # An empty grid exercises the real CLI writer without endpoint requests.
                    code = runner.main(['--api-key', 'test', '--tasks', 'rust_fix_compile_error',
                                        '--repeat', '0', '--out', str(out)])
                self.assertEqual(code, 0)
                self.assertTrue(out.exists())
                self.assertTrue(out.with_suffix('.md').exists())
                self.assertEqual(public.read_text(), 'published report')


if __name__ == '__main__':
    unittest.main()
