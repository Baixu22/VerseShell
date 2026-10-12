"""Content-free accounting of the exact prepared JSON body, never token/billing attribution."""
import hashlib
import json

ROLES = ('system', 'user', 'assistant', 'tool', 'other')


def input_profile(payload, body):
    """Component byte counts add to body size; JSON separators stay in other_json_bytes.

    These are bytes PREPARED for one urlopen attempt, not proof of delivery, cache
    misses, model tokenization, or HTTP/TLS bytes. No request text is persisted.
    """
    size = lambda value: len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    by_role = dict.fromkeys(ROLES, 0)
    counts = dict.fromkeys(ROLES, 0)
    for item in payload.get('messages', payload.get('input', [])):
        role = item.get('role') if isinstance(item, dict) else None
        if isinstance(item, dict) and item.get('type') == 'function_call_output':
            role = 'tool'
        elif isinstance(item, dict) and item.get('type') in ('function_call', 'reasoning'):
            role = 'assistant'
        role = role if isinstance(role, str) and role in by_role else 'other'
        by_role[role] += size(item)
        counts[role] += 1
    tools = size(payload['tools']) if 'tools' in payload else 0
    return {'schema': 'verseshell.input-profile/v1',
            'body_sha256': hashlib.sha256(body).hexdigest(),
            'prepared_body_bytes': len(body), 'tool_schema_bytes': tools,
            'message_item_bytes_by_role': by_role, 'message_counts_by_role': counts,
            'other_json_bytes': len(body) - tools - sum(by_role.values())}


def valid_profile(profile, body_sha256):
    if not isinstance(profile, dict) or profile.get('schema') != 'verseshell.input-profile/v1':
        return False
    if not isinstance(body_sha256, str) or len(body_sha256) != 64 or profile.get('body_sha256') != body_sha256:
        return False
    roles = profile.get('message_item_bytes_by_role')
    counts = profile.get('message_counts_by_role')
    if not isinstance(roles, dict) or set(roles) != set(ROLES) or not isinstance(counts, dict) or set(counts) != set(ROLES):
        return False
    values = [profile.get(k) for k in ('prepared_body_bytes', 'tool_schema_bytes', 'other_json_bytes')]
    if any(type(v) is not int or v < 0 for v in [*values, *roles.values(), *counts.values()]):
        return False
    return values[0] == values[1] + values[2] + sum(roles.values())
