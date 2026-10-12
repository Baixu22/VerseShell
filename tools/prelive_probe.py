"""Explicit two-request tool/Unicode/usage probe for a user-supplied endpoint.

No default model or endpoint. This is the first LIVE step after offline readiness;
its result is separate from scored benchmark cells and contains no API key.
"""
import argparse
import hashlib
import json
import math
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
import live_agent_loop as h
from live_journal import redact
from live_round import load_env


def probe(model,base,key,budget=60,max_tokens=16384):
    parsed=urlparse(base)
    if budget<=0 or max_tokens<=0:raise ValueError('positive probe budgets required')
    if not model or parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.query:
        raise ValueError('explicit model and clean HTTP(S) base URL required')
    nonce='就绪-'+uuid.uuid4().hex
    tools=[{'type':'function','function':{'name':'probe_echo','description':'Echo the exact supplied nonce.',
            'parameters':{'type':'object','properties':{'nonce':{'type':'string'}},'required':['nonce'],'additionalProperties':False}}}]
    messages=[{'role':'system','content':
               'The user message is a JSON object. Call probe_echo with its entire nonce value exactly, '
               'including every Unicode character and punctuation mark (the Chinese prefix and hyphen). '
               'Do not shorten or translate it. '
               'After the tool result, reply with only the same raw nonce, without quotes or any other characters.'},
              {'role':'user','content':json.dumps({'nonce':nonce},ensure_ascii=False)}]
    records=[]
    try:
        for turn in range(2):
            response=h.chat_completion(messages,tools,model=model,api_key=key,base_url=base,
                                       max_tokens=max_tokens,temperature=0,seed=42,request_budget=budget)
            usage=response.get('usage') or {}
            record={'turn':turn+1,'expected_nonce':nonce,'usage':usage,'returned_model':response.get('_returned_model'),
                    'request_id':response.get('_request_id'),'attempts':response.get('_transport_attempts',[])}
            records.append(record)
            choice=response['choices'][0];msg=choice['message']
            content=msg.get('content') or ''
            record.update(finish_reason=choice.get('finish_reason'),content_preview=content[:4096],
                          content_preview_truncated=len(content)>4096,
                          tool_calls=[{'name':c.get('function',{}).get('name'),
                                       'arguments':str(c.get('function',{}).get('arguments',''))[:4096]}
                                      for c in (msg.get('tool_calls') or [])[:4]])
            if any(type(usage.get(k)) not in (int,float) or not math.isfinite(usage[k]) or usage[k]<0
                   for k in ('prompt_tokens','completion_tokens')):
                raise ValueError('endpoint usage missing or invalid')
            if choice.get('finish_reason') in ('length','incomplete'):raise ValueError('probe completion truncated')
            if turn==0:
                calls=msg.get('tool_calls') or []
                if len(calls)!=1 or calls[0]['function']['name']!='probe_echo' or json.loads(calls[0]['function']['arguments'])!={'nonce':nonce}:
                    raise ValueError('tool call/schema/Unicode round-trip failed')
                messages.append({'role':'assistant','content':msg.get('content') or '', 'tool_calls':calls,
                                 **({'_responses_output':msg['_responses_output']} if '_responses_output' in msg else {})})
                messages.append({'role':'tool','tool_call_id':calls[0]['id'],'content':nonce})
            elif msg.get('content')!=nonce or msg.get('tool_calls'):
                raise ValueError('tool result was not returned in final response')
    except Exception as error:
        if len(records)<=turn:
            records.append({'turn':turn+1,'expected_nonce':nonce,'request_error':redact(str(error),(key,)),
                            'attempts':getattr(error,'attempts',[])})
        error.probe_records=records
        raise
    return {'schema':'verseshell.endpoint-readiness/v1','pass':True,'nonce':nonce,'requested_model':model,'api_base':base,
            'max_tokens':max_tokens,'request_budget':budget,
            'protocol':'responses' if base.rstrip('/').endswith('/responses') else 'chat_completions',
            'source_fingerprint':h.evidence_fingerprint(h.EVIDENCE_GLOBS),'records':records,
            'identity_scope':'requested alias and returned metadata; no inferred underlying model version',
            'purpose':'endpoint readiness only; not benchmark evidence'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',required=True)
    p.add_argument('--env-file',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--request-budget',type=int,default=60);p.add_argument('--max-tokens',type=int,default=16384)
    args=p.parse_args(argv);env=load_env(args.env_file);key=env.get('ACI_BENCH_API_KEY','')
    try:
        if not key:raise ValueError('API key missing')
        result=probe(args.model,env.get('ACI_BENCH_BASE_URL',''),key,args.request_budget,args.max_tokens)
    except Exception as error:
        result={'schema':'verseshell.endpoint-readiness/v1','pass':False,'error':redact(str(error),(key,)),
                'requested_model':args.model,'max_tokens':args.max_tokens,'request_budget':args.request_budget,
                'records':getattr(error,'probe_records',[])}
    result['probe_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['usage_complete']=bool(result.get('records')) and all(
        r.get('attempts') and all(a.get('usage_complete') is True for a in r['attempts']) for r in result['records'])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(redact(json.dumps(result,indent=2,ensure_ascii=False),(key,))+'\n',encoding='utf-8')
    print('endpoint probe PASS' if result['pass'] else 'endpoint probe FAILED; inspect redacted report')
    return 0 if result['pass'] else 2


if __name__=='__main__':raise SystemExit(main())
