"""Shared collection identity and exact-grid checks for live runs and merges."""
import itertools

CONFIG_KEYS = ('model', 'api_base', 'protocol', 'caps', 'max_turns', 'max_tokens',
               'temperature', 'exclude_tools', 'tasks', 'conditions', 'repeat', 'collection_id')


def validate_repeat_call_limit(value):
    if type(value) is not int or value < 0 or value == 1:
        raise ValueError('repeat_call_limit must be 0 (off) or an integer >= 2')
    return value


def cell_key(row, *, variants=False):
    base = (row.get('task_id'), row.get('condition'), row.get('seed'), row.get('run_index'))
    return (*base, row.get('prompt_variant')) if variants else base


def expected_cells(identity):
    for field in ('tasks', 'conditions', 'seeds'):
        values = identity.get(field)
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ValueError(f'invalid identity {field}')
    if type(identity.get('repeat')) is not int or identity['repeat'] < 1:
        raise ValueError('invalid repeat count')
    axes = [identity['tasks'], identity['conditions'], identity['seeds'], range(identity['repeat'])]
    if 'prompt_variants' in identity:
        variants = identity['prompt_variants']
        if not variants or len(variants) != len(set(variants)):
            raise ValueError('empty/duplicate prompt variants')
        axes.append(variants)
    return set(itertools.product(*axes))


def validate_rows(rows, identity, *, complete):
    expected = expected_cells(identity)
    repeat_limit = validate_repeat_call_limit(identity.get('repeat_call_limit', 0))
    seen = set()
    for row in rows:
        key = cell_key(row, variants='prompt_variants' in identity)
        if key in seen or key not in expected:
            raise ValueError(f'duplicate or unexpected cell: {key}')
        if validate_repeat_call_limit(row.get('repeat_call_limit', 0)) != repeat_limit:
            raise ValueError(f'row repeat_call_limit mismatch: {key}')
        if row.get('stop_reason') == 'repeat_call_limit' and not repeat_limit:
            raise ValueError(f'repeat stop without an enabled limit: {key}')
        if row.get('model') != identity['model']:
            raise ValueError(f'row model mismatch: {key}')
        if ('prompt_variants' not in identity and 'prompt_variant' in identity
                and row.get('prompt_variant', identity['prompt_variant']) != identity['prompt_variant']):
            raise ValueError(f'row prompt variant mismatch: {key}')
        seen.add(key)
    if complete and seen != expected:
        raise ValueError(f'incomplete grid: missing {len(expected-seen)} cells')


def validate_run(payload, *, complete=True):
    identity = payload.get('run_identity') or {}
    required = (*CONFIG_KEYS, 'seeds', 'task_set_version', 'evidence', 'binary_sha256')
    if any(k not in identity for k in required) or not identity.get('collection_id'):
        raise ValueError('missing frozen run identity; historical inputs cannot be recertified')
    evidence = identity['evidence']
    if not isinstance(evidence, dict) or not evidence.get('globs') or not evidence.get('fingerprint'):
        raise ValueError('missing acquisition evidence')
    if payload.get('evidence') != evidence or payload.get('task_set_version') != identity['task_set_version']:
        raise ValueError('acquisition identity/evidence mismatch')
    cfg = payload.get('live_config') or {}
    if validate_repeat_call_limit(cfg.get('repeat_call_limit', 0)) != validate_repeat_call_limit(identity.get('repeat_call_limit', 0)):
        raise ValueError('repeat_call_limit differs from frozen identity')
    if any(cfg.get(k) != identity[k] for k in CONFIG_KEYS):
        raise ValueError('live configuration differs from frozen identity')
    if any(cfg.get(k)!=identity[k] for k in ('task_set','prompt_variant','retry_policy',
                                          'prompt_variants','schedule_sha256','analysis_plan_sha256','storage_reserves') if k in identity):
        raise ValueError('runtime profile differs from frozen identity')
    if cfg.get('seeds', [cfg.get('seed')]) != identity['seeds']:
        raise ValueError('seed configuration differs from frozen identity')
    validate_rows(payload.get('rows') or [], identity, complete=complete)
    return identity


def collection_signature(identity):
    # Seeds may be separate shards of one collection; everything else is fixed.
    return {k: v for k, v in identity.items() if k != 'seeds'}
