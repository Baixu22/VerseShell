"""Frozen disk reserves, checked before dispatch rather than by a remote watcher."""
import json
import os
import shutil
from pathlib import Path


def storage_policy():
    policy = json.loads(os.environ.get('ACI_STORAGE_RESERVES', '{}'))
    if not isinstance(policy, dict) or any(not Path(p).is_absolute() or type(n) is not int or n < 0
                                          for p, n in policy.items()):
        raise ValueError('ACI_STORAGE_RESERVES must map absolute paths to nonnegative byte reserves')
    return policy


def storage_check(policy):
    readings = {}
    for path, reserve in policy.items():
        try:
            free = shutil.disk_usage(path).free
            readings[path] = {'free_bytes': free, 'reserve_bytes': reserve, 'ok': free >= reserve}
        except OSError as error:
            readings[path] = {'free_bytes': None, 'reserve_bytes': reserve, 'ok': False,
                              'error': str(error)}
    return {'ok': all(v['ok'] for v in readings.values()), 'readings': readings}
