"""No module in `app/` may write to the filesystem while being imported.

An import-time write makes importing a module a side effect on the machine.
Everything that merely *loads* the app performs it: uvicorn, the arq worker,
alembic, pytest collection, the router and handler gates, `python -c "import
app.main"`. And when it fails there is no graceful degradation available,
because the failure happens before any application code can run -- a directory
that cannot be created stops being a failed upload and becomes an application
that will not import.

That is not hypothetical. `compose-smoke` failed for days with "the backend
never became healthy": `translation_service.py` ran

    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)

at module scope, `main.py` imports it transitively, the container runs as
appuser (uid 10001, from H5.1) against a host-owned bind mount, and so uvicorn
died with a PermissionError twelve frames deep in an import chain. The
mechanism that should have made this obvious -- a startup that reports what it
could not do -- could not run, because the failure preceded it.

This is the same shape as `check_unmounted_routers.py` and the frontend's
`htmlSinks.test.ts`: the fix was one line, the guard is what stops it
recurring.

Creating the directory where it is USED is nearly always right. The code that
writes knows what it is writing and can report a failure usefully.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Calls that mutate the filesystem. Reads are fine at import time.
WRITE_CALLS = {
    "mkdir", "makedirs", "touch", "write_text", "write_bytes",
    "chmod", "rmtree", "unlink", "rename", "replace", "symlink_to",
}

# Deliberate exceptions, each with a reason. Keep this empty if you can.
#
# config.py is NOT here. It still creates the upload and export directories at
# import, but it no longer dies if it cannot: the call is wrapped and warns to
# stderr. That is a different thing from an unguarded write, and this test only
# catches the unguarded kind -- a `try`/`except OSError` around the call is
# what moves a module off this list.
ALLOWED: dict[str, str] = {}


def _module_level_writes(path: Path) -> list[tuple[int, str]]:
    """Unguarded filesystem writes that execute when `path` is imported."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    found: list[tuple[int, str]] = []

    def scan(body: list[ast.stmt], guarded: bool) -> None:
        """Walk statements that execute on import, tracking `try` nesting.

        Nesting has to be tracked rather than checked at the top level: the
        first version of this test looked only for a `Try` node directly in the
        module body, and missed config.py's guarded `makedirs` because it sits
        inside a `for` loop that contains the `try`. Reporting an already-fixed
        module is the failure mode that gets a guard deleted.
        """
        for node in body:
            # A def/class defines a body; it does not run it.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            if isinstance(node, ast.Try):
                # The `try` body is protected. Handlers and `finally` are not:
                # a write there still runs at import with nothing to catch it.
                scan(node.body, guarded=True)
                for handler in node.handlers:
                    scan(handler.body, guarded)
                scan(node.orelse, guarded=True)
                scan(node.finalbody, guarded)
                continue

            # Compound statements execute their bodies at import; recurse so
            # the guarded flag survives the nesting.
            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(node, attr, None)
                if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                    scan(inner, guarded)

            if guarded:
                continue

            # Only this statement's OWN expressions -- its nested bodies were
            # just handled above, and walking the whole node would re-enter
            # them, reporting a guarded write as unguarded because the outer
            # statement (a `for`, say) carries the outer flag.
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    continue
                for sub in ast.walk(child):
                    if not isinstance(sub, ast.Call):
                        continue
                    func = sub.func
                    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    if name in WRITE_CALLS:
                        found.append((sub.lineno, name))

    scan(tree.body, guarded=False)
    return sorted(set(found))


def test_no_module_level_filesystem_writes() -> None:
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP.parent).as_posix()
        if rel in ALLOWED:
            continue
        for lineno, call in _module_level_writes(path):
            offenders.append(f"{rel}:{lineno}  {call}()")

    assert not offenders, (
        "Filesystem writes that run at IMPORT time:\n  "
        + "\n  ".join(offenders)
        + "\n\nMove the call to the function that needs the path, or wrap it in "
        "try/except OSError so a failure degrades instead of making the "
        "application unimportable. See this module's docstring."
    )


def test_the_guard_actually_detects_the_original_defect(tmp_path: Path) -> None:
    """Anti-false-pass: the scanner must catch the exact line that broke CI."""
    sample = tmp_path / "offender.py"
    sample.write_text(
        "from pathlib import Path\n"
        "TRANSLATIONS_DIR = Path('uploads/translations')\n"
        "TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)\n",
        encoding="utf-8",
    )
    assert _module_level_writes(sample) == [(3, "mkdir")]


def test_guard_ignores_writes_inside_functions(tmp_path: Path) -> None:
    """The fix must read as clean, or the guard would just block the remedy."""
    sample = tmp_path / "fixed.py"
    sample.write_text(
        "from pathlib import Path\n"
        "TRANSLATIONS_DIR = Path('uploads/translations')\n"
        "def save(content):\n"
        "    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)\n",
        encoding="utf-8",
    )
    assert _module_level_writes(sample) == []


def test_guard_treats_a_try_wrapped_write_as_guarded(tmp_path: Path) -> None:
    """config.py's remaining makedirs is acceptable because it cannot kill the import."""
    sample = tmp_path / "guarded.py"
    sample.write_text(
        "import os\n"
        "try:\n"
        "    os.makedirs('uploads', exist_ok=True)\n"
        "except OSError:\n"
        "    pass\n",
        encoding="utf-8",
    )
    assert _module_level_writes(sample) == []


def test_guard_sees_a_try_nested_inside_a_loop(tmp_path: Path) -> None:
    """config.py's actual shape: `for` -> `try` -> makedirs.

    The first version of this scanner checked only for a `Try` directly in the
    module body, so it reported config.py as an offender after config.py had
    already been fixed. A guard that fails on correct code is a guard someone
    deletes, so the exact shape is pinned here.
    """
    sample = tmp_path / "loop_guarded.py"
    sample.write_text(
        "import os\n"
        "for d in ('uploads', 'exports'):\n"
        "    try:\n"
        "        os.makedirs(d, exist_ok=True)\n"
        "    except OSError as e:\n"
        "        print(e)\n",
        encoding="utf-8",
    )
    assert _module_level_writes(sample) == []


def test_guard_still_catches_an_unguarded_write_inside_a_loop(tmp_path: Path) -> None:
    """...but the loop itself must not become a hiding place."""
    sample = tmp_path / "loop_unguarded.py"
    sample.write_text(
        "import os\n"
        "for d in ('uploads', 'exports'):\n"
        "    os.makedirs(d, exist_ok=True)\n",
        encoding="utf-8",
    )
    assert _module_level_writes(sample) == [(3, "makedirs")]
