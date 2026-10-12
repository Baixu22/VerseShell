"""Inspect live ownership/heartbeat, or request a safe stop after the current cell."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
from live_journal import read_status,atomic_json,utc_now


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path);parser.add_argument('--stop',action='store_true')
    args=parser.parse_args()
    paths=sorted(args.path.glob('*.status.json')) if args.path.is_dir() else [args.path]
    result=[]
    for path in paths:
        state=read_status(path);result.append({'path':str(path),**state})
        if args.stop:
            target=path.parent/'STOP' if path.name=='round.status.json' else path.with_name(path.name.removesuffix('.status.json')+'.stop')
            atomic_json(target,{'requested_at':utc_now(),'reason':'operator_stop'})
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
