"""Explicit treatment selection: never silently pool description variants."""


def select_prompt_variant(payload, variant=None):
    if not payload.get('rows'):
        return payload
    cfg = payload.get('live_config') or {}
    variants = {r.get('prompt_variant', cfg.get('prompt_variant', 'baseline')) for r in payload['rows']}
    if len(variants) > 1 and variant is None:
        raise ValueError('mixed prompt variants: select --prompt-variant explicitly')
    selected = variant or next(iter(variants))
    if selected not in variants:
        raise ValueError(f'prompt variant not present: {selected}')
    return {**payload,
            'rows': [r for r in payload['rows'] if r.get('prompt_variant', cfg.get('prompt_variant', 'baseline')) == selected],
            'live_config': {**cfg, 'prompt_variant': selected},
            'input_selection': {'prompt_variant': selected}}
