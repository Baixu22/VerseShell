"""Opt-in description-only candidate; the tool contract stays fixed."""

DESCRIPTIONS = {
    'read_file':'Read a centered window; follow next_cursor; keep its hash.',
    'read_files':'Read up to 8 files/ranges; returns hashes and errors.',
    'write_file':'Create/overwrite a file; use replace_in_file for edits.',
    'run_command':'Build/test/install; returns output and recovery hints.',
    'read_result':'Read exact handle result://sha256/<64 hex>; no rerun.',
    'replace_in_file':'Replace one exact match; use its hash for safe edits.',
    'search_content':'Search text/regex; use read_file for matched content.',
    'list_files':'List workspace files, branch and dirty state.',
    'list_operations':'List available operations and schemas.',
    'task_complete':'Report completion or blocker once.',
}

# Separate variant: D-only compact and all-condition compact share current schemas.
# Shared operations have identical, truthful descriptions across both interfaces.
ALL_DESCRIPTIONS = {
    **DESCRIPTIONS,
    'run_command': 'Run a command in the workspace; inspect its output and exit status.',
    'task_complete': 'Report completion or blocker once.',
}
