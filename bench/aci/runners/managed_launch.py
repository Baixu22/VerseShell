"""Trusted launch barrier. Parent assigns our Job before sending the permit byte.

Run with Python -I so workspace modules cannot replace our imports. The helper
never launches workload code after EOF or before the permit, and descendants
inherit the assigned Windows Job. Remaining stdin belongs to the workload.
"""
import json
import os
import subprocess
import sys


def main():
    if os.read(0, 1) != b'\x01':
        return 125
    command, shell = json.loads(sys.argv[1])
    return subprocess.call(command, shell=shell,
                           stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


if __name__ == '__main__':
    sys.exit(main())
