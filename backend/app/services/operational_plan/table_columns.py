"""Column order for list-of-dict table variables.

Why this exists: collected data is cached in a JSONB column (``op_data_cache``), and JSONB does not keep the
key order of an object - it stores keys by (length, bytes). A table whose columns come from
``rows[0].keys()`` therefore changes column order on the first cache hit. Variables whose column order
matters declare it here; ``ordered_headers`` is what the renderers call instead of ``rows[0].keys()``.
"""

from typing import Any, Callable, Dict, List, Sequence, Union

Order = Union[List[str], Callable[[Sequence[str]], List[str]]]


def _registry() -> Dict[str, Order]:
    from app.services.operational_plan import plan_extras, species_regulation_tables, species_stage_tables

    return {
        **species_stage_tables.COLUMN_ORDER,
        **species_regulation_tables.COLUMN_ORDER,
        **plan_extras.COLUMN_ORDER,
    }


def ordered_headers(var_name: str, rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Headers for ``rows`` (a non-empty list of dicts): the declared order when there is one, any keys
    that are not declared are appended, and keys starting with ``_`` are never shown."""
    keys = [k for k in rows[0].keys() if not str(k).startswith("_")]
    order = _registry().get(var_name)
    if order is None:
        return keys
    declared = order(keys) if callable(order) else order
    head = [k for k in declared if k in keys]
    return head + [k for k in keys if k not in head]


def has_declared_order(var_name: str) -> bool:
    """True for the tables whose layout (columns, caption) the template owns: the renderer then prints no
    title of its own above them, so the template's caption line is the only caption."""
    return var_name in _registry()
