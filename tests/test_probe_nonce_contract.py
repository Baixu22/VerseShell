"""Strict nonce protocol regression with fixed UUID and mocked transport only."""
import contextlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'bench/aci/runners')]
import prelive_probe as probe

HEX = '0123456789abcdef0123456789abcdef'
NONCE = '就绪-' + HEX


class ProbeNonceContractTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(probe.uuid, 'uuid4', return_value=SimpleNamespace(hex=HEX)))
        self.chat = stack.enter_context(patch.object(probe.h, 'chat_completion'))

    @staticmethod
    def response(nonce, final=False):
        message = {'role': 'assistant', 'content': nonce if final else ''}
        if not final:
            message['tool_calls'] = [{'id': 'offline-call', 'type': 'function', 'function': {
                'name': 'probe_echo', 'arguments': json.dumps({'nonce': nonce}, ensure_ascii=False)}}]
        return {'choices': [{'message': message, 'finish_reason': 'stop' if final else 'tool_calls'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 7},
                '_returned_model': 'offline', '_request_id': 'offline',
                '_transport_attempts': [{'attempt': 1, 'status': 200, 'usage_complete': True}]}

    def invoke(self):
        return probe.probe('offline', 'http://offline.invalid/v1/responses', 'offline-test',
                           budget=60, max_tokens=1024)

    def test_complete_two_turn_roundtrip_records_exact_nonce(self):
        self.chat.side_effect = [self.response(NONCE), self.response(NONCE, final=True)]
        result = self.invoke()
        self.assertTrue(result['pass'])
        self.assertEqual(self.chat.call_count, 2)
        with self.subTest(field='successful report nonce'):
            self.assertEqual(result.get('nonce'), NONCE)
        for record in result['records']:
            with self.subTest(turn=record['turn']):
                self.assertEqual(record.get('expected_nonce'), NONCE)

    def test_first_user_turn_is_json_and_system_requires_unicode_and_punctuation(self):
        self.chat.side_effect = [self.response(NONCE), self.response(NONCE, final=True)]
        self.invoke()
        messages = self.chat.call_args_list[0].args[0]
        try:
            first_input = json.loads(messages[1]['content'])
        except json.JSONDecodeError:
            self.fail('first user turn must encode the nonce as a JSON object, not a bare string')
        self.assertEqual(first_input, {'nonce': NONCE})
        system = messages[0]['content'].casefold()
        self.assertIn('unicode', system)
        self.assertRegex(system, r'punctuation|标点')
        self.assertRegex(system, r'exact|verbatim|完整|原样')

    def test_tool_nonce_without_chinese_prefix_is_rejected_and_recorded(self):
        self.chat.side_effect = [self.response(HEX)]
        with self.assertRaises(ValueError) as caught:
            self.invoke()
        self.assertEqual(self.chat.call_count, 1)
        records = caught.exception.probe_records
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].get('expected_nonce'), NONCE)

    def test_final_prefix_or_suffix_is_rejected_not_substring_matched(self):
        for content in ('prefix ' + NONCE, NONCE + ' suffix'):
            with self.subTest(content=content):
                self.chat.reset_mock()
                self.chat.side_effect = [self.response(NONCE), self.response(content, final=True)]
                with self.assertRaises(ValueError) as caught:
                    self.invoke()
                self.assertEqual(self.chat.call_count, 2)
                self.assertEqual(len(caught.exception.probe_records), 2)
                for record in caught.exception.probe_records:
                    self.assertEqual(record.get('expected_nonce'), NONCE)

    def test_transport_failure_still_records_expected_nonce(self):
        self.chat.side_effect = OSError('offline transport failure')
        with self.assertRaises(OSError) as caught:
            self.invoke()
        self.assertEqual(self.chat.call_count, 1)
        self.assertEqual(caught.exception.probe_records[0].get('expected_nonce'), NONCE)


if __name__ == '__main__':
    unittest.main()
