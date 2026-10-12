"""configreader: minimal reader for simple ``key = value`` config files."""

import os

__all__ = ["read_setting", "read_settings"]

_ENCODING = "utf-8"


def _parse(lines, path):
    """Parse config lines into a dict, skipping blanks and # comments."""
    settings = {}
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{number}: malformed line {raw!r}")
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip()
    return settings


def read_setting(path, key):
    """Return the value stored under *key* in the config file at *path*."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"config file not found: {path}")
    with open(path, "r", encoding=_ENCODING) as handle:
        settings = _parse(handle, path)
    try:
        return settings[key]
    except KeyError:
        # The file exists but does not define this key; that is a distinct
        # failure from a missing file, so let KeyError propagate.
        raise KeyError(f"no setting {key!r} in {path}") from None


def read_settings(path):
    """Return every setting in the config file at *path* as a dict."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"config file not found: {path}")
    with open(path, "r", encoding=_ENCODING) as handle:
        return _parse(handle, path)
