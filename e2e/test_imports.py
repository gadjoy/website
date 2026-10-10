"""The e2e suite must be installable from requirements-e2e.txt alone.

The CI job installs ONLY that file. A test importing something that happens to
be present on the dev box from requirements.txt passes locally and fails in CI
— which is how `import yaml` reached CI and broke the run (CON-VER-004).

This asserts every third-party module the e2e suite imports is declared.
"""
import ast
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
REQS = HERE.parent / "migration" / "requirements-e2e.txt"

STDLIB_OK = {
    "ast", "functools", "hashlib", "http", "json", "os", "pathlib", "platform",
    "re", "socket", "subprocess", "sys", "threading", "tempfile", "dataclasses",
    "shutil", "urllib", "io", "time", "contextlib",
}
# Declared by name in requirements-e2e.txt -> importable module name.
DISTRIBUTION_TO_MODULE = {
    "playwright": "playwright", "pytest": "pytest",
    "pillow": "PIL", "pyyaml": "yaml",
}


def declared_modules():
    out = set()
    for line in REQS.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        dist = re.split(r"[<>=!~\[]", line)[0].strip().lower()
        out.add(DISTRIBUTION_TO_MODULE.get(dist, dist))
    return out


def imported_modules():
    out = set()
    for f in HERE.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
    return out


def test_every_third_party_import_is_declared():
    local = {p.stem for p in HERE.glob("*.py")}
    undeclared = imported_modules() - declared_modules() - STDLIB_OK - local

    assert not undeclared, (
        f"these modules are imported by the e2e suite but not in "
        f"requirements-e2e.txt: {sorted(undeclared)}. The e2e CI job installs "
        f"only that file, so this passes locally and fails in CI."
    )
