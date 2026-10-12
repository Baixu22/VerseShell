"""Regressions for the Step 5 file, command-output and Windows contracts."""
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bench/aci/runners'))
import live_agent_loop as h
from live_journal import ObservationStore, load_observation


class ToolContractTests(unittest.TestCase):
    def test_centered_window_bounds_and_next_cursor_reach_both_renderings(self):
        for data in (
            {'start_line': 95, 'end_line': 104, 'total_lines': 106, 'next_cursor': 110,
             'lines': [{'line': n, 'text': str(n)} for n in range(95, 105)]},
            {'start_line': 0, 'end_line': 0, 'total_lines': 0, 'next_cursor': None, 'lines': []},
            {'start_line': 1, 'end_line': 1, 'total_lines': 1, 'next_cursor': None,
             'lines': [{'line': 1, 'text': 'only'}]},
        ):
            for compact in (False, True):
                result = h.parse_aci_result(h.format_aci_result({'ok': True, 'data': data}, compact=compact))
                for key in ('start_line', 'end_line', 'total_lines', 'next_cursor'):
                    self.assertEqual(result[key], data[key])

    def test_success_failure_full_reduced_empty_and_truncated_streams(self):
        body = 'x' * (2662 - len('18 passed\n')) + '18 passed\n'
        for success in (False, True):
            for status in ('full', 'reduced', 'truncated', 'empty'):
                text = '' if status == 'empty' else body
                stream = {'status': status, 'text': text, 'raw_bytes': len(text),
                          'returned_bytes': len(text), 'omitted_bytes': 0,
                          'raw_complete': True, 'encoding': 'utf-8', 'decoding_lossy': False}
                if status in ('truncated', 'reduced'):
                    stream.update(artifact='result://sha256/' + 'a' * 64, omitted_bytes=500)
                envelope = {'ok': success, 'data': {'stdout': stream, 'stderr': stream,
                    'exit_code': 0 if success else 7, 'timed_out': False, 'stats': {'passed': 18}}}
                for compact in (False, True):
                    result = h.parse_aci_result(h.format_aci_result(envelope, compact=compact))
                    self.assertEqual(result['exit_code'], 0 if success else 7)
                    self.assertFalse(result['timed_out'])
                    self.assertEqual(result['stats']['passed'], 18)
                    for name in ('stdout', 'stderr'):
                        self.assertEqual(result[name + '_text'], text)
                        self.assertEqual(result[name]['status'], status)
                        self.assertEqual(result[name]['omitted_bytes'], stream['omitted_bytes'])
                        self.assertEqual(result[name].get('artifact'), stream.get('artifact'))

    def test_existing_result_query_is_callable_and_keeps_content(self):
        self.assertEqual(h.ACI_OP_MAP['read_result'], 'result.query')
        data = {'handle': 'result://sha256/' + 'a' * 64, 'mode': 'tail',
                'text': 'test conclusion\n' * 200, 'lines': 200, 'truncated': True,
                'encoding': 'utf-8', 'decoding_lossy': False}
        result = h.parse_aci_result(h.format_aci_result({'ok': True, 'op': 'result.query', 'data': data}))
        self.assertEqual(result, {'ok': True, **data})

    def test_shell_guided_variant_only_changes_raw_shell_prompt(self):
        guided_profile, guided_prompt, guided_tools = h.prompt_and_tools('raw_shell', 'shell_guided')
        base_profile, base_prompt, base_tools = h.prompt_and_tools('raw_shell', 'baseline')
        self.assertEqual(guided_profile, 'shell_guided')
        self.assertNotEqual(guided_prompt, base_prompt)
        self.assertIn('cmd /C', guided_prompt)
        self.assertIn('python file.py', guided_prompt)
        self.assertEqual(guided_tools, base_tools)
        # Both shell arms get the cmd-safe guidance; ACI must be untouched.
        for condition in ('raw_shell', 'raw_shell_coached'):
            guided = h.prompt_and_tools(condition, 'shell_guided')
            base = h.prompt_and_tools(condition, 'baseline')
            self.assertEqual(guided[0], 'shell_guided')
            self.assertNotEqual(guided[1], base[1])
            self.assertEqual(guided[2], base[2])
        self.assertEqual(h.prompt_and_tools('verseshell_aci', 'baseline'),
                         h.prompt_and_tools('verseshell_aci', 'shell_guided'))

    def test_all_briefings_keep_actual_command_dialect_and_argv_contract(self):
        for variant in ('baseline', 'compact_all', 'compact'):
            for condition in h.PROMPT_BY_CONDITION:
                _, prompt, tools = h.prompt_and_tools(condition, variant)
                tools = {t['function']['name']: t['function'] for t in tools}
                parameter = 'argv' if condition == 'verseshell_aci' else 'command'
                description = tools['run_command']['parameters']['properties'][parameter]['description']
                self.assertIn('cmd', description)
                self.assertIn('PowerShell', description)
                if condition == 'verseshell_aci':
                    self.assertIn('literal', description)
                    self.assertIn('Center line', tools['read_file']['parameters']['properties']['cursor']['description'])
                    self.assertIn('result://sha256/<64 hex>', tools['read_result']['description'])
                    self.assertIn('read_result', tools)
                self.assertNotIn('`more`/`head`', prompt)

    def test_raw_output_keeps_both_streams_exit_and_tail_when_cut_or_timed_out(self):
        out = ('中文\n' + 'x' * 200 + '\n18 passed').encode('utf-8')
        err = '错误'.encode('utf-8')
        for timed_out in (False, True):
            capture = {}
            with patch.object(h, 'run_bounded', return_value=(7, out, err, timed_out)), \
                    patch.object(h, 'MAX_OUTPUT_CHARS', 60):
                text = h.execute_shell_cmd('synthetic', '.', capture=capture)
            self.assertIn('中文', text)
            self.assertIn('18 passed', text)
            self.assertIn('错误', text)
            self.assertIn('TRUNCATED', text)
            self.assertTrue(text.endswith('[EXIT: 7]'))
            self.assertEqual(capture, {'stdout': out, 'stderr': err})
            self.assertEqual('TIMEOUT' in text, timed_out)

    @unittest.skipUnless(os.name == 'nt', 'Windows OEM fallback')
    def test_oem_fallback_is_recorded_and_invalid_bytes_do_not_crash(self):
        with patch('ctypes.windll.kernel32.GetOEMCP', return_value=936):
            self.assertEqual(h.decode_shell_output('中文'.encode('gbk')), ('中文', 'windows-oem-936', False))
            text, encoding, lossy = h.decode_shell_output(b'\xff')
            self.assertIn('\ufffd', text)
            self.assertEqual(encoding, 'windows-oem-936-lossy')
            self.assertTrue(lossy)
        self.assertEqual(h.decode_shell_output('中文\ufffd'.encode('utf-8')), ('中文\ufffd', 'utf-8', False))

    def test_raw_evidence_is_bounded_hashed_and_redacted_before_base64(self):
        secret = 'sk-abcdefghijklmnopqrst'
        raw = b'\xff\xd6\xd0' + secret.encode() + b'x' * 70000
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservationStore(Path(tmp) / 'observations', secrets=(secret,))
            ref = store.save('diagnostic', raw_streams={'stdout': raw, 'stderr': b'\xff'})
            saved = load_observation(tmp, ref)
            stdout = saved['raw_streams']['stdout']
            prefix = base64.b64decode(stdout['base64'], validate=True)
            self.assertEqual(stdout['captured_bytes'], 65536)
            self.assertEqual(stdout['source_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(stdout['captured_sha256'], hashlib.sha256(prefix).hexdigest())
            self.assertNotIn(secret.encode(), prefix)
            self.assertFalse(stdout['capture_complete'])
            self.assertTrue(stdout['redacted'])
            self.assertTrue(saved['redacted'])
            self.assertEqual(base64.b64decode(saved['raw_streams']['stderr']['base64']), b'\xff')
            self.assertTrue(saved['raw_streams']['stderr']['capture_complete'])


@unittest.skipUnless(os.environ.get('ACI_TEST_AE'), 'set ACI_TEST_AE to the candidate binary for native checks')
class NativeToolContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tool-contract-中文-')
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        patcher = patch.object(h, 'AE', Path(os.environ['ACI_TEST_AE']))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_op(self, name, args, capture=None):
        response = h.execute_aci_op(name, args, str(self.workspace), capture=capture)
        return response, h.parse_aci_result(h.format_aci_result(response))

    def test_native_cursor_tail_and_output_artifact_retrieval(self):
        (self.workspace / '106.txt').write_text(''.join(f'line {n}\n' for n in range(1, 107)), encoding='utf-8')
        _, page = self.run_op('file.view', {'path': '106.txt', 'cursor': 100, 'window': 10})
        self.assertEqual((page['start_line'], page['end_line'], page['total_lines']), (95, 104, 106))
        self.assertEqual(page['next_cursor'], 110)
        _, tail = self.run_op('file.view', {'path': '106.txt', 'cursor': page['next_cursor'], 'window': 10})
        self.assertEqual(tail['text'].splitlines(), ['line 105', 'line 106'])
        self.assertIsNone(tail['next_cursor'])

        script = self.workspace / 'long output.py'
        script.write_text("import sys\nprint('line\\n' * 10000 + '18 passed')\nprint('error tail', file=sys.stderr)\n", encoding='utf-8')
        raw = {}
        response, output = self.run_op('exec.run', {'argv': [sys.executable, '-X', 'utf8', str(script)], 'profile': 'none'}, capture=raw)
        self.assertEqual(output['exit_code'], 0, response)
        self.assertEqual(output['stdout']['status'], 'truncated')
        self.assertGreater(output['stdout']['omitted_bytes'], 0)
        self.assertIn('18 passed', output['stdout_text'])
        self.assertIn('error tail', output['stderr_text'])
        handle = output['stdout']['artifact']
        _, query = self.run_op('result.query', {'handle': handle, 'mode': 'tail', 'lines': 2})
        self.assertIn('18 passed', query['text'])
        self.assertTrue(query['truncated'])
        alias = handle.replace('result://sha256/', 'result://sha256:', 1)
        _, alias_query = self.run_op('result.query', {'handle': alias, 'mode': 'tail', 'lines': 2})
        self.assertIn('18 passed', alias_query['text'])
        _, head = self.run_op('result.query', {'handle': handle, 'mode': 'slice', 'start_line': 1, 'end_line': 2})
        self.assertEqual(head['text'], 'line\nline')
        self.assertEqual(hashlib.sha256(raw['stdout']).hexdigest(), handle.rsplit('/', 1)[1])

    @unittest.skipUnless(os.name == 'nt', 'Windows cmd/PowerShell contracts')
    def test_native_argv_literals_and_explicit_shell_quotes_pipes_and_redirection(self):
        argv = [sys.executable, '-c', 'import json,sys;print(json.dumps(sys.argv[1:]))',
                'a b', '>', 'literal.txt', '|', 'say "hi"']
        response, output = self.run_op('exec.run', {'argv': argv, 'profile': 'none'})
        self.assertEqual(output.get('exit_code'), 0, response)
        self.assertEqual(json.loads(output['stdout_text']), argv[3:])
        self.assertFalse((self.workspace / 'literal.txt').exists())
        command = f'"{sys.executable}" -c "print(12345)" > "带 空格.txt"'
        self.assertIn('[EXIT: 0]', h.execute_shell_cmd(command, str(self.workspace)))
        self.assertEqual((self.workspace / '带 空格.txt').read_text().strip(), '12345')
        response, output = self.run_op('exec.run', {'argv': ['cmd', '/d', '/s', '/c',
            'type "带 空格.txt" | findstr 12345 > "result with spaces.txt"'], 'profile': 'none'})
        self.assertEqual(output.get('exit_code'), 0, response)
        self.assertEqual((self.workspace / 'result with spaces.txt').read_text().strip(), '12345')
        response, output = self.run_op('exec.run', {'argv': ['powershell', '-NoProfile', '-Command',
            "Get-Content -LiteralPath '带 空格.txt' | Set-Content -Encoding UTF8 -LiteralPath 'ps result.txt'"], 'profile': 'none'})
        self.assertEqual(output.get('exit_code'), 0, response)
        self.assertEqual((self.workspace / 'ps result.txt').read_text(encoding='utf-8-sig').strip(), '12345')

    @unittest.skipUnless(os.name == 'nt', 'Windows OEM output')
    def test_native_encoding_and_saved_bytes_match_raw_and_aci(self):
        for raw in ('中文'.encode('utf-8'), '中文'.encode('gbk'), b'\xff'):
            with self.subTest(raw=raw):
                script = self.workspace / '字节 输出.py'
                script.write_text(f'import os\nos.write(1, {raw!r})\nos.write(2, {raw!r})\n', encoding='utf-8')
                expected, encoding, lossy = h.decode_shell_output(raw)
                captured = {}
                text = h.execute_shell_cmd(f'"{sys.executable}" -X utf8 "{script}"', str(self.workspace), capture=captured)
                self.assertIn(expected, text)
                self.assertEqual(captured, {'stdout': raw, 'stderr': raw})
                captured = {}
                response, output = self.run_op('exec.run', {'argv': [sys.executable, '-X', 'utf8', str(script)], 'profile': 'none'}, capture=captured)
                self.assertEqual(output.get('exit_code'), 0, response)
                self.assertEqual(captured, {'stdout': raw, 'stderr': raw})
                for name in ('stdout', 'stderr'):
                    self.assertEqual(output[name + '_text'], expected)
                    self.assertEqual(output[name]['encoding'], encoding)
                    self.assertEqual(output[name]['decoding_lossy'], lossy)
                    _, queried = self.run_op('result.query', {'handle': output[name]['artifact'], 'mode': 'raw'})
                    self.assertEqual(queried['text'], expected)
                    self.assertEqual(queried['decoding_lossy'], lossy)


if __name__ == '__main__':
    unittest.main()
