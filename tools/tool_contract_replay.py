"""Audit selected historical tool loops and re-project saved envelopes, without executing calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bench/aci/runners'))
from live_agent_loop import format_aci_result, parse_aci_result
from live_journal import load_observation


def audit_cell(row, root):
    turns = row.get('turn_diagnostics', [])
    call_turns = [turn['turn'] for turn in turns for _ in range(turn['tool_call_count'])]
    steps = row.get('trajectory', [])
    if len(call_turns) != len(steps):
        raise ValueError(f"{row['cell_id']}: recorded turn/call counts do not agree")
    calls = Counter()
    texts = Counter()
    records = []
    previous = None
    streak = longest = 0
    for index, step in enumerate(steps):
        observed = load_observation(root, step['observation'])
        if observed.get('cell_id') != row['cell_id']:
            raise ValueError('observation cell identity mismatch')
        signature = json.dumps([step['op'], step['args']], sort_keys=True, ensure_ascii=False)
        calls[signature] += 1
        texts[step['observation']['text_sha256']] += 1
        streak = streak + 1 if signature == previous else 1
        longest = max(longest, streak)
        previous = signature
        envelope = observed.get('envelope') or {}
        data = envelope.get('data') or {}
        projected = format_aci_result(envelope) if envelope else None
        record = {'index': index, 'turn': call_turns[index], 'op': step['op'], 'args': step['args'],
                  'observation': step['observation'], 'redacted': observed.get('redacted', False),
                  'historical_text_chars': len(observed['text']),
                  'current_projection_chars': len(projected) if projected is not None else None,
                  'same_call_streak': streak, 'ok': envelope.get('ok')}
        for key in ('content_hash', 'start_line', 'end_line', 'total_lines', 'exit_code', 'timed_out', 'summary', 'stats'):
            if key in data:
                record[key] = data[key]
        if projected is not None and step['op'] == 'exec.run':
            visible = parse_aci_result(projected)
            record['streams'] = {name: {
                'raw_bytes': data.get(name, {}).get('raw_bytes'),
                'status': data.get(name, {}).get('status'),
                'current_text_chars': len(visible.get(name + '_text', '')),
                'current_text_tail': visible.get(name + '_text', '')[-300:],
            } for name in ('stdout', 'stderr')}
        records.append(record)
    return {**{key: row.get(key) for key in ('cell_id', 'task_id', 'seed', 'condition', 'prompt_variant',
             'success', 'success_reason', 'stop_reason', 'turns', 'agent_declared_success')},
            'turns_recorded': [{key: turn.get(key) for key in ('turn', 'tool_call_count', 'finish_reason',
                                'completion_truncated')} for turn in turns],
            'longest_identical_call_streak': longest,
            'max_identical_visible_observations': max(texts.values(), default=0),
            'most_repeated_calls': [{'count': n, 'call': json.loads(k)} for k, n in calls.most_common(3)],
            'steps': records}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--cell-id', action='append', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    if args.out.exists() or args.out.resolve().is_relative_to(args.input.parent.resolve()):
        ap.error('write a new report outside the preserved input directory')
    body = args.input.read_bytes()
    rows = json.loads(body)['rows']
    selected = [row for row in rows if row.get('cell_id') in args.cell_id]
    if len(selected) != len(set(args.cell_id)):
        ap.error('requested cells missing or duplicated')
    cases = [audit_cell(row, args.input.parent) for row in selected]
    if hashlib.sha256(args.input.read_bytes()).digest() != hashlib.sha256(body).digest():
        raise ValueError('input changed during replay')
    report = {'input': str(args.input.resolve()), 'input_sha256': hashlib.sha256(body).hexdigest(),
              'cells': cases, 'verified_observations': sum(len(c['steps']) for c in cases),
              'scope': 'historical observation audit and current projection only; no model calls, no regrading',
              'limitations': ['Identical calls or observations do not prove unchanged hidden workspace state.',
                              'Re-projecting old envelopes does not measure model behavior after repairs.',
                              'Historical scores, budgets, turn limits and missing bytes remain unchanged.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cells': len(cases), 'verified_observations': report['verified_observations'], 'out': str(args.out)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
