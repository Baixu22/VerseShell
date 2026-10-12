"""Read-only TF-0138 attribution: identical pairs, distinct estimands, explicit unknowns."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bench/aci/runners'))
from input_profile import ROLES, valid_profile
from live_uncertainty import attempt_usage, token_count, usage_exclusion_reasons, single_collection_verdict
from usage_audit import paired_cells

IDENTITY = ('prompt_variant', 'model', 'task_id', 'seed', 'run_index')
BASELINES = ('raw_shell', 'raw_shell_coached')


def quantiles(values):
    """Linear interpolation (type 7), including endpoints; empty is unknown."""
    values = sorted(values)
    def at(p):
        if not values: return None
        i = (len(values)-1)*p
        lo, hi = math.floor(i), math.ceil(i)
        return values[lo] + (values[hi]-values[lo])*(i-lo)
    return {str(p): at(p/100) for p in (0, 10, 25, 50, 75, 90, 95, 99, 100)}


def estimands(pairs):
    if not pairs: return {'available': False, 'n_pairs': 0, 'reason': 'no valid positive-baseline pairs'}
    a = sum(p['baseline_total_tokens'] for p in pairs)
    d = sum(p['aci_total_tokens'] for p in pairs)
    tasks = defaultdict(list)
    for p in pairs: tasks[p['identity']['task_id']].append(p)
    task_stats = []
    for task, cells in sorted(tasks.items()):
        ta = sum(p['baseline_total_tokens'] for p in cells)
        td = sum(p['aci_total_tokens'] for p in cells)
        task_stats.append({'task_id': task, 'n_pairs': len(cells),
                           'baseline_mean_tokens': ta/len(cells), 'aci_mean_tokens': td/len(cells),
                           'ratio_of_sums': td/ta,
                           'mean_of_ratios': statistics.fmean(p['ratio'] for p in cells)})
    mean = statistics.fmean(p['ratio'] for p in pairs)
    task_mean = statistics.fmean(t['mean_of_ratios'] for t in task_stats)
    task_total = math.fsum(t['aci_mean_tokens'] for t in task_stats)/math.fsum(t['baseline_mean_tokens'] for t in task_stats)
    return {'available': True, 'n_pairs': len(pairs), 'n_tasks': len(tasks),
            'baseline_total_tokens': a, 'aci_total_tokens': d,
            'ratio_of_sums': d/a, 'cell_equal_mean_of_ratios': mean,
            'task_equal_mean_of_ratios': task_mean, 'task_equal_ratio_of_mean_costs': task_total,
            'baseline_cost_weighted_mean_of_ratios': math.fsum(p['baseline_total_tokens']*p['ratio'] for p in pairs)/a,
            'weighting_shift_total_minus_cell_mean': d/a - mean,
            'total_and_cell_direction_disagree': (d/a - 1)*(mean - 1) < 0,
            'aci_cheaper_pairs': sum(p['ratio'] < 1 for p in pairs),
            'aci_equal_pairs': sum(p['ratio'] == 1 for p in pairs),
            'ratio_quantiles': quantiles([p['ratio'] for p in pairs]), 'tasks': task_stats}


def contributions(pairs):
    total_a = sum(p['baseline_total_tokens'] for p in pairs)
    total_d = sum(p['aci_total_tokens'] for p in pairs)
    def group(cells):
        a = sum(p['baseline_total_tokens'] for p in cells)
        d = sum(p['aci_total_tokens'] for p in cells)
        return {'n_pairs': len(cells), 'baseline_tokens': a, 'aci_tokens': d,
                'baseline_token_share': a/total_a if total_a else None,
                'aci_token_share': d/total_d if total_d else None,
                'token_reduction_A_minus_D': a-d,
                'signed_net_reduction_share': (a-d)/(total_a-total_d) if total_a != total_d else None}
    ordered = sorted(pairs, key=lambda p: (-p['baseline_total_tokens'], str(p['identity'])))
    top = ordered[:math.ceil(len(pairs)*.1)]
    return {'baseline_turn_cap_partition': {
                'at_cap': group([p for p in pairs if p['baseline_at_turn_cap'] is True]),
                'below_cap': group([p for p in pairs if p['baseline_at_turn_cap'] is False]),
                'unknown': group([p for p in pairs if p['baseline_at_turn_cap'] is None])},
            'baseline_cost_top_decile': {**group(top), 'identities': [p['identity'] for p in top]},
            'interpretation': 'turn cap uses the frozen max_turns; top decile is descriptive concentration, not a tuned optimization. '
                              'Groups overlap across views. Signed contributions may exceed 1 because other cells offset savings.'}


def overhead(rows):
    def measure(values):
        known = [v for v in values if token_count(v)]
        return {'expected_rows': len(values), 'observed_rows': len(known),
                'sum_observed': sum(known), 'complete_total': sum(known) if len(known) == len(values) else None}
    first_prompt = []
    later_prompt = []
    profile_totals = {k: 0 for k in ('prepared_body_bytes', 'tool_schema_bytes', 'other_json_bytes', *ROLES)}
    by_phase = {'first_turn': dict(profile_totals), 'later_turns': dict(profile_totals)}
    known_attempts = profiled = missing_ledgers = missing_turn_rows = 0
    for row in rows:
        turns = row.get('turn_diagnostics') or []
        if not isinstance(turns, list): turns = []
        complete_turns = bool(turns) and len(turns) == row.get('turns')
        first = turns[0] if complete_turns and turns[0].get('turn') == 1 else None
        value = None
        if first:
            attempts = first.get('transport_attempts') or []
            amounts = [attempt_usage(first, i).get('prompt_tokens') for i in range(len(attempts))] if attempts else [first.get('prompt_tokens')]
            if all(token_count(v) for v in amounts): value = sum(amounts)
        first_prompt.append(value)
        later_prompt.append(row['llm_prompt_tokens']-value if value is not None and value <= row['llm_prompt_tokens'] else None)
        if not complete_turns: missing_turn_rows += 1
        for i, turn in enumerate(turns):
            attempts = turn.get('transport_attempts') or []
            if not attempts: missing_ledgers += 1
            for attempt in attempts:
                known_attempts += 1
                profile = attempt.get('input_profile')
                if not valid_profile(profile, attempt.get('request_body_sha256')): continue
                profiled += 1
                values = {k: profile[k] for k in ('prepared_body_bytes', 'tool_schema_bytes', 'other_json_bytes')}
                values.update(profile['message_item_bytes_by_role'])
                for key, count in values.items():
                    profile_totals[key] += count
                    by_phase['first_turn' if i == 0 else 'later_turns'][key] += count
    complete = bool(known_attempts) and profiled == known_attempts and not missing_ledgers and not missing_turn_rows
    return {'rows': len(rows), 'endpoint_prompt_tokens': measure([r['llm_prompt_tokens'] for r in rows]),
            'endpoint_completion_tokens': measure([r['llm_completion_tokens'] for r in rows]),
            'first_turn_prompt_tokens': measure(first_prompt), 'later_turn_prompt_tokens': measure(later_prompt),
            'turns': measure([r.get('turns') for r in rows]),
            'tool_calls': measure([r.get('tool_calls') for r in rows]),
            'tool_output_observation_proxy': measure([r.get('observation_tokens') for r in rows]),
            'request_input_profiles': {'known_attempts': known_attempts, 'profiled_attempts': profiled,
                'missing_or_invalid_profiles': known_attempts-profiled, 'missing_attempt_ledger_turns': missing_ledgers,
                'missing_turn_rows': missing_turn_rows, 'coverage_complete': complete,
                'observed_prepared_bytes': profile_totals,
                'complete_prepared_bytes': profile_totals if complete else None,
                'observed_prepared_bytes_by_phase': by_phase},
            'caliber': 'First/later prompt counts are endpoint receipts, not component attribution. '
                       'Profiles count prepared JSON bytes per attempt, not delivered wire bytes or model tokens. '
                       'assistant/tool message bytes describe re-submitted history; the observation proxy is len//4, not endpoint usage. '
                       'No reasoning-token split, cache accounting, reconciled bill or currency is inferred.'}


def analyse(payload, variant=None):
    rows = payload.get('rows') or []
    if variant is not None:
        rows = [r for r in rows if r.get('prompt_variant') == variant]
        if not rows: raise ValueError('prompt variant not present')
    groups = paired_cells(rows)
    results = []
    cap = (payload.get('live_config') or {}).get('max_turns')
    for variant, model in sorted({key[:2] for key in groups}):
        selected = [(key, cells) for key, cells in groups.items() if key[:2] == (variant, model)]
        available = {c for _, cells in selected for c in cells}
        for baseline in BASELINES:
            if baseline not in available: continue
            pairs, excluded, raw_a, raw_d = [], [], [], []
            matched = eligible = 0
            candidates = [(key, cells) for key, cells in selected if baseline in cells or 'verseshell_aci' in cells]
            for key, cells in candidates:
                identity = dict(zip(IDENTITY, key))
                a, d = cells.get(baseline), cells.get('verseshell_aci')
                reasons = []
                if a is None: reasons.append('missing_baseline')
                if d is None: reasons.append('missing_aci')
                if a is not None and d is not None:
                    matched += 1
                    for label, row in (('baseline', a), ('aci', d)):
                        reasons += [label + ':' + reason for reason in usage_exclusion_reasons(row)]
                    if not reasons:
                        eligible += 1
                        av = a['llm_prompt_tokens'] + a['llm_completion_tokens']
                        dv = d['llm_prompt_tokens'] + d['llm_completion_tokens']
                        if av == 0: reasons.append('zero_baseline_undefined_cell_ratio')
                if reasons:
                    excluded.append({'identity': identity, 'reasons': reasons})
                    continue
                def at_cap(row):
                    return row['turns'] >= cap if type(cap) is int and cap > 0 and token_count(row.get('turns')) else None
                pairs.append({'identity': identity, 'baseline_cell_id': a.get('cell_id'), 'aci_cell_id': d.get('cell_id'),
                              'baseline_total_tokens': av, 'aci_total_tokens': dv, 'ratio': dv/av,
                              'baseline_turns': a.get('turns'), 'aci_turns': d.get('turns'),
                              'baseline_at_turn_cap': at_cap(a), 'aci_at_turn_cap': at_cap(d)})
                raw_a.append(a); raw_d.append(d)
            comparison_rows = [row for _, cells in selected for c, row in cells.items() if c in (baseline, 'verseshell_aci')]
            results.append({'prompt_variant': variant, 'model': model, 'baseline': baseline,
                'candidate_pair_keys': len(candidates), 'matched_pairs': matched, 'usage_eligible_pairs': eligible,
                'valid_pairs': len(pairs), 'excluded_pairs': excluded,
                'estimands': estimands(pairs), 'contributions': contributions(pairs),
                'overhead_on_identical_pairs': {'baseline': overhead(raw_a), 'aci': overhead(raw_d)},
                'pairs': pairs, 'acceptance': single_collection_verdict(comparison_rows, baseline, cap,
                    partial=bool(payload.get('partial')), synthetic=bool(payload.get('synthetic_test_only')))})
    return {'schema': 'verseshell.cost-attribution/v1', 'claimable': False, 'max_turns': cap,
        'generated_at': datetime.now(timezone.utc).isoformat(), 'comparisons': results,
        'estimand_definitions': {
            'ratio_of_sums': 'sum(D)/sum(A): baseline-cost weighted mean of cell ratios',
            'cell_equal_mean_of_ratios': 'mean(D/A): every valid (task, seed, run_index) cell has equal weight',
            'task_equal_mean_of_ratios': 'mean over tasks of each task mean(D/A); same valid cells, equal task weights',
            'task_equal_ratio_of_mean_costs': 'sum over tasks mean(D) / sum over tasks mean(A); same valid cells, equal task weights'},
        'limits': ['All estimands in a comparison use the identical positive-baseline, complete-usage pair set.',
                   'Excluded cells are listed, not zero-imputed; failures/capped cells with usable cost remain in this descriptive view.',
                   'Models and prompt variants are never pooled. No statistical significance or causal explanation is claimed.',
                   'Historical missing input profiles remain unknown; current source templates cannot reconstruct historical requests.',
                   'Optimizations require independent development tasks; prospective confirmation must retain both total and cell-equal estimands.']}


def markdown(report):
    lines = ['# Cost attribution — diagnostic only', '', 'Formal claimable: false', '',
             '| variant | model | baseline | valid / candidate | ratio of sums | cell equal | task equal ratios | task equal cost ratio |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for c in report['comparisons']:
        e = c['estimands']
        values = [e.get(k) for k in ('ratio_of_sums', 'cell_equal_mean_of_ratios', 'task_equal_mean_of_ratios', 'task_equal_ratio_of_mean_costs')]
        lines.append(f"| {c['prompt_variant']} | {c['model']} | {c['baseline']} | {c['valid_pairs']} / {c['candidate_pair_keys']} | " + ' | '.join('unknown' if v is None else f'{v:.6f}' for v in values) + ' |')
    lines += ['', *['- ' + s for s in report['limits']]]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--with-arm', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--prompt-variant')
    args = p.parse_args(argv)
    try:
        source, output = args.with_arm.resolve(), args.out.resolve()
        text_output = output.with_suffix('.md')
        if output.parent == source.parent or text_output.parent == source.parent:
            raise ValueError('output must be in a separate derived-report directory')
        if output == text_output or output.exists() or text_output.exists():
            raise ValueError('choose new JSON and Markdown output files')
        data = source.read_bytes()
        report = analyse(json.loads(data.decode('utf-8-sig')), args.prompt_variant)
        report['source'] = str(source)
        report['source_sha256'] = hashlib.sha256(data).hexdigest()
        report['analysis_source_sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'tools/cost_attribution.py', 'tools/usage_audit.py', 'tools/live_uncertainty.py', 'bench/aci/runners/input_profile.py')}
        if hashlib.sha256(source.read_bytes()).hexdigest() != report['source_sha256']:
            raise ValueError('input changed during analysis')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as f: f.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        with text_output.open('x', encoding='utf-8') as f: f.write(markdown(report))
        print(markdown(report))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__': raise SystemExit(main())
