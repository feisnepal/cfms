"""FS-4a.13 - sampling-mutex helper generalised (ONE neutral home).

Compartments and **block-level sampling** on the same forest are mutually
exclusive: the ``check_dimension_exclusivity()`` trigger on ``forest_blocks``
rejects any ``is_compartment`` insert (a top-level compartment OR a
sub-compartment) once a ``sampling_designs`` row exists for the calculation.
Left to the trigger, the user gets a bare database error (a 500) *after*
designing the whole split.

Before FS-4a.13 that guard lived as a small private query inside
``compartment_divide_service`` (``_check_sampling_mutex`` /
``ERR_SAMPLING_MUTEX``) and was re-imported into ``auto_block_service`` as a
*private cross-service* import (``from ..services.compartment_divide_service
import _check_sampling_mutex``), so the block stream and the equal-area stream
each called the "other stream's" helper to raise the same bilingual 400. This
task moved it to exactly this single, branch-neutral home that BOTH services
already share (``forest_units/operations``), re-exported the private name here
so neither service needs a cross-service private import any longer, and kept
the exact message + ``SAMPLING_MUTEX:`` prefix the API layer routes to the
bilingual ``compartments.sampling_mutex`` 400 (``editing.py``).

The guard is deliberately KEPT until FS-P2 replaces it with the downstream
"sampling detector": at that point both services drop this call and let the
trigger's own diagnostic answer instead (plan, P4a §11.2 / the FS-4a list).
Do not remove it before P2, and do not re-copy the query into another service
-modul meanwhile: if a third stream ever needs the mutex, import it from here.
"""
from typing import Any

from ....models.sampling import SamplingDesign

ERR_SAMPLING_MUTEX = (
    "SAMPLING_MUTEX: Cannot create compartments: this forest already has block-level sampling designs. "
    "Compartments are mutually exclusive with block-level sampling. "
    "Please delete existing sampling designs first if you want to switch to compartment mode."
)


def _check_sampling_mutex(db, calc_id: Any) -> None:
    """Refuse compartment creation on a forest that already has sampling.

    Raises ``ValueError`` (``ERR_SAMPLING_MUTEX`` - the ``SAMPLING_MUTEX:``
    prefix ``editing.py`` routes to the bilingual ``compartments.sampling_mutex``
    400) whenever a ``sampling_designs`` row already exists for ``calc_id``.
    Only the ``compartments`` layer is ever gated here: block level (and
    sub-blocks) is unaffected - creating blocks on a forest that has block-level
    sampling is the same stream, so the mutex never applies there (mirrors the
    trigger's ``is_compartment`` exclusivity exactly). Kept until FS-P2.
    """
    existing = (
        db.query(SamplingDesign)
        .filter(SamplingDesign.calculation_id == calc_id)
        .count()
    )
    if existing > 0:
        raise ValueError(ERR_SAMPLING_MUTEX)


def check_sampling_mutex(db, calc_id: Any) -> None:
    """Public neutral entry point for the sampling mutex.

    ``_check_sampling_mutex`` under its branch-neutral public name. Both the
    equal-area compartment stream (``compartment_divide_service._guard``) and
    the auto-block stream (``auto_block_service``, which only gates it behind
    ``level == "compartments"``) call THIS shared function - neither service
    keeps a copy of the query any longer. Kept until FS-P2 replaces it with the
    downstream detector.
    """
    _check_sampling_mutex(db, calc_id)