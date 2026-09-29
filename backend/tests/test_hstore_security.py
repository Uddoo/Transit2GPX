from __future__ import annotations

import subprocess
import sys

from app.rail.importer import parse_hstore


def test_hstore_preserves_unicode_escapes_empty_and_duplicate_tags() -> None:
    raw = r'"name"=>"上海","alt"=>"a\"b","path"=>"a\\b","empty"=>"","name"=>"虹桥"'
    assert parse_hstore(raw) == {
        "name": "虹桥",
        "alt": 'a"b',
        "path": "a\\b",
        "empty": "",
    }
    assert parse_hstore(None) == {}
    assert parse_hstore('"ok"=>"kept","unfinished') == {"ok": "kept"}


def test_hstore_malformed_backslash_input_finishes_in_bounded_time() -> None:
    # Execute in a child so restoring the vulnerable regex cannot hang pytest.
    code = """
from app.rail.importer import parse_hstore
for prefix in ['"', '"key"=>"']:
    assert parse_hstore(prefix + '\\\\!' * 100000) == {}
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)
