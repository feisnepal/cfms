"""Branch-aware unit labels (FS-4a.1).

The ONE place that knows the display term for a unit at any depth, on either branch, in
English and Nepali. Before this module, ``app/utils/forest_dimension.py``'s
``dimension_label_for_level`` already branched by depth for the compartment side
(``Compartment`` vs ``Sub-Compartment``) but not the block side (``Block`` at every
depth, including a sub-block) -- an easy miss while sub-blocks did not exist. This module
adds the missing branch; ``forest_dimension.py`` delegates to it rather than duplicating
the strings, so there is still exactly one place that decides them (I10's lesson applied
to labels, not just depth tests).
"""

from __future__ import annotations

from .model import DEPTH_SUB, Branch


def _is_sub(depth: int) -> bool:
    return depth >= DEPTH_SUB


def unit_label(branch: Branch, depth: int, *, nepali: bool = False) -> str:
    """The singular display term for a unit at ``depth`` on ``branch``."""
    if branch is Branch.COMPARTMENT:
        if _is_sub(depth):
            return "उप-कम्पार्टमेन्ट" if nepali else "Sub-Compartment"
        return "कम्पार्टमेन्ट" if nepali else "Compartment"
    if _is_sub(depth):
        return "उप-ब्लक" if nepali else "Sub-Block"
    return "ब्लक" if nepali else "Block"


def unit_label_plural(branch: Branch, depth: int, *, nepali: bool = False) -> str:
    if branch is Branch.COMPARTMENT:
        if _is_sub(depth):
            return "उप-कम्पार्टमेन्टहरू" if nepali else "Sub-Compartments"
        return "कम्पार्टमेन्टहरू" if nepali else "Compartments"
    if _is_sub(depth):
        return "उप-ब्लकहरू" if nepali else "Sub-Blocks"
    return "ब्लकहरू" if nepali else "Blocks"


def unit_name_header(branch: Branch, depth: int, *, nepali: bool = False) -> str:
    """e.g. "Sub-Block Name" / "उप-ब्लकको नाम"."""
    label = unit_label(branch, depth, nepali=nepali)
    return f"{label}को नाम" if nepali else f"{label} Name"


def unit_abbreviation(branch: Branch, depth: int) -> str:
    if branch is Branch.COMPARTMENT:
        return "SCmp" if _is_sub(depth) else "Cmp"
    return "SBlk" if _is_sub(depth) else "Blk"
