"""Render YAML values from required environment variables without textual interpolation."""

import os
import re
import sys

import yaml


def render(value):
    if isinstance(value, dict):
        return {k: render(v) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v) for v in value]
    if isinstance(value, str) and re.fullmatch(r"\$\{[A-Z_]+\}", value):
        key = value[2:-1]
        if not os.environ.get(key):
            raise RuntimeError(f"Required configuration missing: {key}")
        return os.environ[key]
    return value


with open(sys.argv[1]) as source:
    config = render(yaml.safe_load(source))
with open(sys.argv[2], "w") as target:
    yaml.safe_dump(config, target)
os.chmod(sys.argv[2], 0o600)
