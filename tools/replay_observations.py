"""Verify saved model-visible observations, including generated files; no live calls."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
from live_journal import load_observation
from live_agent_loop import format_aci_result
from tf45_envelope_replay import strip_compact_digest


def replay(path):
    path=Path(path);body=path.read_bytes()
    if path.name.endswith('.jsonl'):
        rows=[r for r in (json.loads(x) for x in body.decode('utf-8').splitlines() if x.strip()) if '_config' not in r]
    else:rows=json.loads(body)['rows']
    checked=reads=matched=0;old14=old16=current=0;failures=[];missing=redacted=0
    for row in rows:
        for index,step in enumerate(row.get('trajectory',[])):
            is_read=step.get('op') in ('file.view','file.read_many','file.read_range')
            reads+=is_read
            ref=step.get('observation')
            if not ref:
                missing+=1;continue
            try:
                data=load_observation(path.parent,ref);checked+=1
                if data.get('redacted'):
                    redacted+=1;continue
                if not is_read:continue
                envelope=data.get('envelope')
                if not isinstance(envelope,dict):raise ValueError('read envelope missing')
                text=format_aci_result(envelope)
                if text!=data['text']:raise ValueError('model-visible text differs from current projection')
                current+=len(text)//4
                old16+=len(format_aci_result(envelope,compact=False))//4
                old14+=len(format_aci_result(strip_compact_digest(envelope)))//4
                matched+=1
            except (ValueError,KeyError,FileNotFoundError) as exc:
                failures.append({'task_id':row.get('task_id'),'step':index,'reason':str(exc)})
    return {'source':str(path),'source_sha256':hashlib.sha256(body).hexdigest(),
            'records_checked':checked,'read_calls':reads,'read_calls_matched':matched,
            'missing_records':missing,'redacted_records':redacted,'failures':failures,
            'exact_replay_ok':not failures and not missing and not redacted and matched==reads,
            'C14_saving':1-current/old14 if old14 else None,
            'C16_saving':1-current/old16 if old16 else None,
            'scope':'recorded-observation mechanism only; not model performance or formal acceptance'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    report=replay(args.input);args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
    return 0 if report['exact_replay_ok'] else 1


if __name__=='__main__':raise SystemExit(main())
