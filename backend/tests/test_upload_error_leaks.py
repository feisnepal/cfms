"""Gate (UPLOAD_EXPERIENCE_PLAN.md, UP-2.4): an upload handler never shows the user an exception's text, SQL or a library message.

A user cannot act on "File is not a zip file" or on a database error with the SQL in it, and the SQL is a schema disclosure. Upload handlers raise
``upload_error(...)`` / ``i18n_error(...)`` (a coded, bilingual finding) and LOG the exception. This test reads the source of each upload handler
and fails if it builds an ``HTTPException`` whose ``detail`` is an f-string or ``str(...)`` call that includes an exception variable.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# module -> the handlers that receive a user's file (the first thing a wrong file reaches)
UPLOAD_HANDLERS = {
    "api/user_group.py": ["upload_extent_boundary", "import_extent_boundary"],
    "api/household_info.py": ["upload_household_data"],
    "api/field_inventory.py": ["upload_field_inventory"],
    "api/inventory.py": ["preview_column_mapping", "confirm_and_upload_with_mapping"],
}


def _exception_names(fn: ast.AST) -> set[str]:
    names = {"e", "exc", "err", "error", "ex"}
    for node in ast.walk(fn):
        if isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _mentions(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(node))


def leaks(path: str, handler: str) -> list[str]:
    return _scan(ast.parse((APP / path).read_text(encoding="utf8")), path, handler)


def _scan(tree: ast.AST, path: str, handler: str) -> list[str]:
    fn = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == handler), None)
    assert fn is not None, f"{path}: handler {handler} not found (renamed? update UPLOAD_HANDLERS)"
    caught = _exception_names(fn)
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "HTTPException":
            for kw in node.keywords:
                if kw.arg == "detail" and not isinstance(kw.value, ast.Constant) and _mentions(kw.value, caught):
                    found.append(f"{path}:{node.lineno} {handler}: HTTPException detail built from an exception")
    return found


@pytest.mark.parametrize("path,handler", [(p, h) for p, hs in UPLOAD_HANDLERS.items() for h in hs])
def test_an_upload_handler_never_puts_exception_text_in_an_error_response(path, handler):
    assert leaks(path, handler) == []


def test_the_scanner_really_catches_a_leak_and_lets_a_coded_error_through():
    leaky = """
async def upload(file):
    try:
        read(file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
"""
    clean = """
async def upload(file):
    try:
        read(file)
    except Exception as e:
        logger.exception("failed")
        raise upload_error(500, finding("file.unreadable"))
"""
    constant = """
async def upload(file):
    try:
        read(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail="File must be a CSV")
"""
    assert len(_scan(ast.parse(leaky), "x.py", "upload")) == 1
    assert _scan(ast.parse(clean), "x.py", "upload") == []
    assert _scan(ast.parse(constant), "x.py", "upload") == []
