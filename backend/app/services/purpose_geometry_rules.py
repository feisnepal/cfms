"""
Purpose → allowed geometry matrix — backend SSOT for on-screen digitizing.

This matrix drives the digitize UI draw modes (which toolbar buttons show per
purpose). It is a *curated subset* of what `process_geometry_list()`
(`file_processor.py:914-1068`) can accept: every geometry type listed here is
guaranteed to pass finalize validation as a complete drawn feature, but the
processor may be more permissive (e.g. it can auto-buffer points or close lines
for polygon purposes — those are file-import conveniences, not digitize modes).

| Purpose               | Draw modes offered                 | Why                                                                 |
|-----------------------|------------------------------------|---------------------------------------------------------------------|
| inventory             | point                              | STRICT_POINT — lines/polygons rejected                              |
| sample_plot           | point                              | STRICT_POINT — lines/polygons rejected                              |
| user_group_boundary   | polygon                            | polygon purpose (finalize polygonises/buffers points+lines)         |
| boundary              | polygon                            | polygon purpose                                                     |
| blocks                | polygon                            | polygon purpose                                                     |
| roads                 | line                               | polygons rejected; point→line is an import convenience, not a mode  |
| water                 | polygon, line                      | all preserved as-is                                                 |
| other                 | point, line, polygon               | all preserved as-is                                                 |

NOTE: the plan (v4, Task 1.1.2) listed `sample_plot→{Point,Polygon}` — this is
incorrect per `process_geometry_list` (sample_plot is in `IMPORT_PURPOSE_STRICT_POINT`
and rejects polygons). Code is canonical; the matrix below reflects actual behaviour.
"""
from typing import Dict, Set

from ..core.constants import (
    IMPORT_PURPOSE_ALL,
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_INVENTORY,
    IMPORT_PURPOSE_OTHER,
    IMPORT_PURPOSE_POLYGON_AUTO_BUFFER,
    IMPORT_PURPOSE_ROADS,
    IMPORT_PURPOSE_SAMPLE_PLOT,
    IMPORT_PURPOSE_STRICT_POINT,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_WATER,
)

# Geometry type identifiers (GeoJSON geometry types)
POINT = "Point"
LINE_STRING = "LineString"
POLYGON = "Polygon"

_ALL_TYPES = frozenset({POINT, LINE_STRING, POLYGON})
_POINT_ONLY = frozenset({POINT})
_LINE_ONLY = frozenset({LINE_STRING})
_POLYGON_ONLY = frozenset({POLYGON})
_LINE_OR_POLYGON = frozenset({LINE_STRING, POLYGON})


def _build_matrix() -> Dict[str, frozenset]:
    matrix: Dict[str, frozenset] = {}
    for purpose in IMPORT_PURPOSE_STRICT_POINT:
        matrix[purpose] = _POINT_ONLY
    matrix[IMPORT_PURPOSE_ROADS] = _LINE_ONLY
    for purpose in IMPORT_PURPOSE_POLYGON_AUTO_BUFFER:
        matrix[purpose] = _POLYGON_ONLY
    matrix[IMPORT_PURPOSE_WATER] = _LINE_OR_POLYGON
    matrix[IMPORT_PURPOSE_OTHER] = _ALL_TYPES
    return matrix


# Single source of truth — never edit the dict below directly; edit `_build_matrix`.
PURPOSE_ALLOWED_GEOMETRY_TYPES: Dict[str, frozenset] = _build_matrix()


def allowed_geometry_types(purpose: str) -> Set[str]:
    """Return the GeoJSON geometry types a purpose accepts for digitizing.

    Args:
        purpose: One of the import purposes defined in `constants.py`.

    Returns:
        Set of geometry type strings, e.g. {"Point"} or {"Polygon"}.

    Raises:
        ValueError: If purpose is not a known import purpose.
    """
    if purpose not in IMPORT_PURPOSE_ALL:
        raise ValueError(f"Unknown import purpose: {purpose!r}")
    return set(PURPOSE_ALLOWED_GEOMETRY_TYPES[purpose])
