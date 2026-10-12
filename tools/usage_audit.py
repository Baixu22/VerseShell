"""Read-only attempt/usage ledger and paired cost denominators; never queries billing APIs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

from live_uncertainty import attempt_usage, token_count, usage_exclusion_reasons

FIELDS = ('prompt_tokens', 'completion_tokens')


def audit_row(row):
    records = []
    received = {k: [] for k in FIELDS}
    missing_ledger_turns = 0
    unknown_turns = set()
    turns = row.get('turn_diagnostics') or []
    if not isinstance(turns, list):
        raise ValueError('invalid turn diagnostics')
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError('invalid turn record')
        attempts = turn.get('transport_attempts') or []
        if not isinstance(attempts, list) or any(not isinstance(a, dict) for a in attempts):
            raise ValueError('invalid attempt ledger')
        if not attempts:
            missing_ledger_turns += 1
            for key in FIELDS:
                if token_count(turn.get(key)):
                    received[key].append(turn[key])
            if any(not token_count(turn.get(k)) for k in FIELDS):
                unknown_turns.add(turn_index)
        for index, attempt in enumerate(attempts):
            usage = attempt_usage(turn, index)
            values = {k: usage.get(k) if token_count(usage.get(k)) else None for k in FIELDS}
            complete = attempt.get('usage_complete') is not False and all(v is not None for v in values.values())
            for key, value in values.items():
                if value is not None:
                    received[key].append(value)
            if not complete:
                unknown_turns.add(turn_index)
            last = index == len(attempts)-1
            records.append({'turn': turn.get('turn', turn_index+1), 'attempt': attempt.get('attempt', index+1),
                            'attempt_id': attempt.get('attempt_id'), 'status': attempt.get('status'),
                            'request_id': attempt.get('request_id') or (turn.get('request_id') if last else None),
                            'response_id': attempt.get('response_id') or (turn.get('response_id') if last else None),
                            'request_body_sha256': attempt.get('request_body_sha256') or turn.get('request_body_sha256'),
                            'usage': values, 'usage_status': 'received' if complete else 'unknown',
                            'usage_basis': 'attempt_receipt' if 'usage' in attempt else 'historical_returned_turn' if last and usage else 'absent',
                            'request_failed': bool(attempt.get('error'))})
    # Legacy row-only counters remain labelled as such, never fabricated attempt records.
    if not turns:
        for key in FIELDS:
            value = row.get('reported_llm_' + key, row.get('llm_' + key))
            if token_count(value):
                received[key].append(value)
    totals = {k: sum(v) if v else None for k, v in received.items()}
    reasons = usage_exclusion_reasons(row)
    return {**{k: row.get(k) for k in ('cell_id', 'task_id', 'model', 'condition', 'prompt_variant', 'seed', 'run_index')},
            'success': row.get('success'), 'usage_eligible': not reasons, 'exclusion_reasons': reasons,
            'received_usage': totals,
            'received_total_tokens': sum(v for v in totals.values() if v is not None) if any(v is not None for v in totals.values()) else None,
            'received_fields_complete': all(v is not None for v in totals.values()),
            'received_basis': 'attempt_or_turn_receipts' if turns else 'legacy_row_counters',
            'recorded_attempts': len(records), 'unknown_usage_attempts': sum(r['usage_status']=='unknown' for r in records),
            'turns_with_unknown_usage': len(unknown_turns), 'missing_attempt_ledger_turns': missing_ledger_turns,
            'attempt_ledger_complete': bool(turns) and not missing_ledger_turns,
            'attempts': records}


def paired_cells(rows):
    groups = defaultdict(dict)
    for index, row in enumerate(rows):
        key = tuple(row.get(k) for k in ('prompt_variant', 'model', 'task_id', 'seed', 'run_index'))
        if any(v is None for v in key):
            raise ValueError(f'row {index} lacks paired identity')
        condition = row['condition']
        if condition in groups[key]:
            raise ValueError(f'duplicate paired cell: {key}, {condition}')
        groups[key][condition] = row
    return groups


def paired_denominators(rows):
    groups = paired_cells(rows)
    result = []
    for variant in sorted({key[0] for key in groups}):
        selected = [cells for key, cells in groups.items() if key[0] == variant]
        for baseline in ('raw_shell', 'raw_shell_coached'):
            candidates = [c for c in selected if baseline in c or 'verseshell_aci' in c]
            matched = [c for c in candidates if baseline in c and 'verseshell_aci' in c]
            eligible = [c for c in matched if c[baseline]['usage_eligible'] and c['verseshell_aci']['usage_eligible']]
            result.append({'prompt_variant': variant, 'baseline': baseline,
                           'candidate_pair_keys': len(candidates), 'matched_pairs': len(matched),
                           'missing_partner_pairs': len(candidates)-len(matched),
                           'usage_eligible_pairs': len(eligible), 'excluded_usage_pairs': len(matched)-len(eligible),
                           'denominator': 'identical paired cells with valid usage in both arms; never zero-imputed'})
    return result


def audit(payload):
    cfg = payload.get('live_config') or {}
    rows = []
    for row in payload.get('rows', []):
        row = dict(row)
        for key in ('model', 'seed', 'prompt_variant'):
            row.setdefault(key, cfg.get(key, 'baseline' if key == 'prompt_variant' else None))
        row.setdefault('run_index', 0)
        rows.append(audit_row(row))
    reasons = Counter(r for row in rows for r in row['exclusion_reasons'])
    received = [r['received_total_tokens'] for r in rows if r['received_total_tokens'] is not None]
    return {'schema': 'verseshell.usage-audit/v1',
            'scope': 'received endpoint usage and cost-pair eligibility; not a reconciled invoice or formal acceptance',
            'billing': {'status': 'unknown', 'reconciled_billed_tokens': None,
                        'reason': 'no provider invoice evidence supplied; unknown attempts are not zero-cost'},
            'summary': {'rows': len(rows), 'usage_eligible_rows': sum(r['usage_eligible'] for r in rows),
                        'excluded_usage_rows': sum(not r['usage_eligible'] for r in rows),
                        'received_total_tokens': sum(received) if received else None,
                        'rows_missing_received_totals': len(rows)-len(received),
                        'rows_with_partial_received_fields': sum(not r['received_fields_complete'] for r in rows),
                        'recorded_attempts': sum(r['recorded_attempts'] for r in rows),
                        'unknown_usage_attempts': sum(r['unknown_usage_attempts'] for r in rows),
                        'turns_with_unknown_usage': sum(r['turns_with_unknown_usage'] for r in rows),
                        'rows_with_incomplete_attempt_ledger': sum(not r['attempt_ledger_complete'] for r in rows),
                        'exclusion_reasons': dict(reasons)},
            'pairs': paired_denominators(rows), 'rows': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.resolve().is_relative_to(args.input.parent.resolve()):
        parser.error('output must be a new file outside the historical input directory')
    raw = args.input.read_bytes()
    report = audit(json.loads(raw.decode('utf-8-sig')))
    report['source'] = {'path': str(args.input.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    report['analyzer_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name('live_uncertainty.py'))}
    if args.input.read_bytes() != raw:
        raise ValueError('historical input changed during audit')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'summary': report['summary'], 'pairs': report['pairs'], 'billing': report['billing']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
