"""Shared test helper: read the named constants of templates/editor.html (v5.70).

Coding Standard (CLAUDE.md): tests read the same constant the editor uses instead of re-typing
the value.  The editor keeps its constants in one block delimited by the BEGIN / END marker
comments; `prelude()` returns that block (pure JS -- constants and tiny helpers) so node-run
extracted functions can be given the same definitions, and `value(name)` evaluates one
constant with node and returns it as a Python object.
"""
import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

EDITOR_PATH = Path(__file__).parent.parent / "templates" / "editor.html"
BEGIN_MARK = "// ═══ EDITOR CONSTANTS — BEGIN"
END_MARK = "// ═══ EDITOR CONSTANTS — END"
NODE = shutil.which("node")


@lru_cache(maxsize=1)
def prelude() -> str:
    src = EDITOR_PATH.read_text()
    i = src.index(BEGIN_MARK)
    j = src.index(END_MARK)
    return src[i:j] + "\n"


@lru_cache(maxsize=None)
def value(name: str):
    """Evaluate constant `name` from the editor constants block (needs node)."""
    assert NODE, "node is required to evaluate editor constants"
    js = prelude() + "\nconsole.log(JSON.stringify(%s));" % name
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)
