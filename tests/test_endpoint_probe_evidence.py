"""Probe failures retain receipts; these controls never contact an endpoint."""
import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prelive_probe as probe

class ProbeEvidenceTests(unittest.TestCase):
    def response(self,finish='stop',message=None):
        return {'choices':[{'finish_reason':finish,'message':message or {'content':'wrong'}}],
                'usage':{'prompt_tokens':12,'completion_tokens':7},
                '_transport_attempts':[{'status':200,'usage_complete':True,'usage':{'prompt_tokens':12,'completion_tokens':7}}]}

    def test_bad_nonce_retains_received_usage(self):
        with patch.object(probe.h,'chat_completion',return_value=self.response()):
            with self.assertRaises(ValueError) as failure:probe.probe('offline','https://offline.invalid','test-secret')
        records=failure.exception.probe_records
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['usage']['completion_tokens'],7)
        self.assertEqual(records[0]['content_preview'],'wrong')

    def test_truncation_keeps_the_reply_receipt(self):
        with patch.object(probe.h,'chat_completion',return_value=self.response('length')):
            with self.assertRaisesRegex(ValueError,'truncated') as failure:probe.probe('offline','https://offline.invalid','test-secret')
        self.assertEqual(failure.exception.probe_records[0]['finish_reason'],'length')
        self.assertEqual(failure.exception.probe_records[0]['usage']['prompt_tokens'],12)

    def test_second_transport_failure_keeps_first_turn_and_unknown_attempt(self):
        count=0
        def call(messages,*args,**kw):
            nonlocal count
            count+=1
            if count==1:
                return self.response('tool_calls',{'tool_calls':[{'id':'one','function':{'name':'probe_echo',
                    'arguments':json.dumps({'nonce':json.loads(messages[1]['content'])['nonce']})}}]})
            error=RuntimeError('transport failure');error.attempts=[{'status':502,'usage_complete':False}];raise error
        with patch.object(probe.h,'chat_completion',side_effect=call):
            with self.assertRaises(RuntimeError) as failure:probe.probe('offline','https://offline.invalid','test-secret')
        records=failure.exception.probe_records
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['usage']['prompt_tokens'],12)
        self.assertFalse(records[1]['attempts'][0]['usage_complete'])

    def test_cli_failure_receipt_is_redacted_and_not_zero_imputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env=root/'endpoint.env';target=root/'report.json';secret='unit-secret-value'
            env.write_text('ACI_BENCH_API_KEY='+secret+'\nACI_BENCH_BASE_URL=https://offline.invalid\n')
            error=RuntimeError('error '+secret);error.attempts=[{'status':None,'error':secret,'usage_complete':False}]
            with patch.object(probe.h,'chat_completion',side_effect=error),patch('sys.stdout',new_callable=io.StringIO):
                code=probe.main(['--model','offline','--env-file',str(env),'--out',str(target),'--max-tokens','1024'])
            text=target.read_text(encoding='utf-8');result=json.loads(text)
            self.assertEqual(code,2);self.assertNotIn(secret,text)
            self.assertFalse(result['pass']);self.assertFalse(result['usage_complete'])
            self.assertEqual(len(result['records']),1)
            self.assertNotIn('usage',result['records'][0])

class TokenizerCacheTests(unittest.TestCase):
    def test_explicit_cache_target_takes_precedence_over_temp(self):
        import os
        import token_proxy_calibration as cal
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TIKTOKEN_CACHE_DIR':tmp,'DATA_GYM_CACHE_DIR':tmp+'/other'}):
            self.assertEqual(cal.cl100k_cache_path().parent,Path(tmp))

    def test_verified_download_is_written_to_the_configured_cache(self):
        import os,types
        import token_proxy_calibration as cal
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TIKTOKEN_CACHE_DIR':tmp}), \
             patch.dict(sys.modules,{'tiktoken':types.SimpleNamespace(get_encoding=lambda _: (_ for _ in ()).throw(ValueError('cold')))}), \
             patch.object(cal,'tiktoken_cache_dirs',return_value=[Path(tmp)]), \
             patch.object(cal,'download_cl100k',return_value=b'verified-by-downloader') as download, \
             patch.object(cal,'_build_cl100k',return_value=types.SimpleNamespace(n_vocab=100277,encode=lambda text:[1])):
            counter,info=cal.resolve_tokenizer(allow_download=True)
            self.assertEqual(info['tier'],3)
            self.assertEqual(cal.cl100k_cache_path().read_bytes(),b'verified-by-downloader')
            self.assertEqual(Path(info['cache_path']).parent,Path(tmp))
            download.assert_called_once_with()

if __name__=='__main__':unittest.main()
