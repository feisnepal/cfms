"""Every route back to `draft` must leave the map editable.

`dfo_reject` did not. Its docstring says "completed/**locked** -> draft", and
`locked -> draft` is a legal transition, so a DFO rejecting an approved map
returned it to `draft` with `structure_locked` still true. The owner was told
to rework the map and then refused every edit with a 423, and the Unlock button
was not rendered either -- `WorkspaceHeader` shows it only while the status is
`locked`, which it no longer was. The map ended up editable by nobody short of
a super admin who knew to look.

`super_admin_unlock` had always cleared the flag on the same transition. The
two paths simply did not agree, and nothing compared them.

`cf_db` held 0 calculations in that state when this was found, so the
reject-from-locked path had evidently never been exercised in anger.

The invariant test at the bottom is the point of this file. Testing `dfo_reject`
alone would fix today's bug and leave the next path back to `draft` free to
repeat it.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.api import calculation_lifecycle
from app.api.deps import ALLOWED_TRANSITIONS


def _endpoints_that_move_to_draft() -> dict[str, ast.FunctionDef]:
    """Every function in calculation_lifecycle that assigns DRAFT.

    Read from the AST rather than a hand-kept list, so a path added next month
    is included without anybody remembering to add it here.
    """
    source = Path(inspect.getfile(calculation_lifecycle)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            target = sub.targets[0]
            if (isinstance(target, ast.Attribute)
                    and target.attr == "map_lifecycle_status"
                    and "DRAFT" in ast.dump(sub.value)):
                found[node.name] = node
                break
    return found


def _clears_the_lock(func: ast.FunctionDef) -> bool:
    for sub in ast.walk(func):
        if not isinstance(sub, ast.Assign):
            continue
        target = sub.targets[0]
        if (isinstance(target, ast.Attribute)
                and target.attr == "structure_locked"
                and isinstance(sub.value, ast.Constant)
                and sub.value.value is False):
            return True
    return False


class TestTheTransitionIsReachable:
    """Establishes that this was not a theoretical concern."""

    def test_locked_may_go_back_to_draft(self):
        assert "draft" in ALLOWED_TRANSITIONS["locked"]

    def test_dfo_reject_targets_draft(self):
        assert "dfo_reject" in _endpoints_that_move_to_draft()


class TestEveryPathBackToDraftUnlocks:
    """The invariant, not the instance.

    Parametrised over whatever the module actually contains, so a third path
    added later is covered on the day it is written.
    """

    @pytest.mark.parametrize("name", sorted(_endpoints_that_move_to_draft()))
    def test_it_clears_structure_locked(self, name):
        func = _endpoints_that_move_to_draft()[name]
        assert _clears_the_lock(func), (
            f"{name}() sets map_lifecycle_status to DRAFT but never sets "
            "structure_locked = False. A map returned to draft while still "
            "locked is editable by nobody: the guards answer 423 and the "
            "Unlock button is not rendered, because it only appears while the "
            "status is 'locked'."
        )

    def test_both_known_paths_are_covered(self):
        """Guards the guard.

        If the AST scan stops matching -- a refactor to a helper, a different
        enum -- every parametrised case above silently disappears and the file
        passes while testing nothing.
        """
        names = set(_endpoints_that_move_to_draft())
        assert {"dfo_reject", "super_admin_unlock"} <= names, (
            f"the scan found {names or 'nothing'}; it is no longer finding the "
            "endpoints it exists to check"
        )
