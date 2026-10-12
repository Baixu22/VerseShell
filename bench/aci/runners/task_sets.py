"""Explicit versioned task overrides over an unchanged, hash-pinned base."""
import hashlib
import json
from pathlib import Path


def load_tasks(task_dir, task_set=None):
    task_dir=Path(task_dir)
    manifest=json.loads((task_dir/'manifest.json').read_text(encoding='utf-8-sig'))
    tasks={name:json.loads((task_dir/(name+'.json')).read_text(encoding='utf-8-sig')) for name in manifest['tasks']}
    if task_set is not None:
        spec=json.loads(Path(task_set).read_text(encoding='utf-8-sig'))
        for name, digest in spec['base_sha256'].items():
            if hashlib.sha256((task_dir/name).read_bytes()).hexdigest()!=digest:
                raise ValueError(f'base task source changed: {name}')
        for name, override in spec['overrides'].items():
            if name not in tasks:
                raise ValueError(f'unknown override task: {name}')
            tasks[name]={**tasks[name], **override}
        manifest={**manifest, 'task_set_version':spec['task_set_version']}
    # Deprecated source metadata, never an execution filter. Preserve pinned
    # source bytes; conditions are selected explicitly by the collection plan.
    for task in tasks.values():
        task.pop('modes', None)
    return manifest,tasks
