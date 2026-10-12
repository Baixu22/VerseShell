"""Offline character and independent-tokenizer counts; never endpoint usage."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench/aci/runners'))
import live_agent_loop as h
from token_proxy_calibration import resolve_tokenizer


def measure():
    counter,info=resolve_tokenizer(allow_download=False)
    rows=[]
    for condition in ('raw_shell','raw_shell_coached','verseshell_aci'):
        for variant in ('baseline','compact'):
            profile,template,tools=h.prompt_and_tools(condition,variant)
            for exclude in (False,True):
                selected=[t for t in tools if not exclude or t['function']['name']!='read_files']
                system=template.format(task_hint='Complete the given coding task.',max_turns=8,read_format=h.READ_TEXT_HELP)
                schema=json.dumps(selected,ensure_ascii=False)
                rows.append({'condition':condition,'variant':variant,'without_read_files':exclude,'profile':profile,
                    'system_chars':len(system),'schema_chars':len(schema),'total_chars':len(system)+len(schema),
                    'system_independent_tokens':counter(system),'schema_independent_tokens':counter(schema),
                    'total_independent_tokens':counter(system)+counter(schema)})
    return {'scope':'static system+schema; common task hint, excludes workspace listing/history; not endpoint usage',
            'tokenizer':info,'rows':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();report=measure();args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
