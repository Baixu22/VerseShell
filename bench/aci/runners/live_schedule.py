"""Frozen, position-balanced condition/description blocks; no endpoint calls."""
import hashlib
import itertools
import json
import random

VARIANTS = ('baseline', 'compact', 'compact_all', 'shell_guided', 'shell_safe')


def make_schedule(tasks, conditions, seeds, variants, *, order_seed=42, repeat=1):
    for label, values in [('tasks', tasks), ('conditions', conditions), ('seeds', seeds), ('variants', variants)]:
        if not values or len(values) != len(set(values)):
            raise ValueError(f'empty/duplicate schedule {label}')
    if set(variants) - set(VARIANTS) or set(conditions) - {'raw_shell', 'raw_shell_coached', 'verseshell_aci'}:
        raise ValueError('unsupported condition/variant')
    if type(repeat) is not int or repeat < 1:
        raise ValueError('invalid repeat')
    rng = random.Random(order_seed)
    treatments = list(itertools.product(conditions, variants))
    rng.shuffle(treatments)
    cells = []
    # Seeds remain separate resumable shards. Rotate over blocks so every
    # treatment occupies every position equally (within one at a boundary).
    block = 0
    for seed in seeds:
        task_order = list(tasks)
        rng.shuffle(task_order)
        for task, index in itertools.product(task_order, range(repeat)):
            offset = block % len(treatments)
            for condition, variant in treatments[offset:] + treatments[:offset]:
                cells.append([task, condition, seed, index, variant])
            block += 1
    return {'schema': 'verseshell.block-schedule/v1', 'tasks': list(tasks),
            'conditions': list(conditions), 'seeds': list(seeds), 'variants': list(variants),
            'repeat': repeat, 'order_seed': order_seed, 'cells': cells}


def validate_schedule(schedule):
    expected = make_schedule(schedule['tasks'], schedule['conditions'], schedule['seeds'],
                             schedule['variants'], order_seed=schedule['order_seed'], repeat=schedule['repeat'])
    if schedule != expected:
        raise ValueError('schedule differs from frozen generation rule/grid')
    return schedule


def digest(schedule):
    return hashlib.sha256(json.dumps(schedule, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
