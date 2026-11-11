"""Sustainable Forest Management (दिगो वन व्यवस्थापन) subsystem.

Implements the Bagmati Province *दिगो वन व्यवस्थापन कार्यविधि, २०७९* — classify
each block / compartment into one of the guideline's 14 forest types, derive the
statutory prescription (silvicultural system, felling / rotation cycle,
regeneration method, mother-tree retention, felling-series structuring) and a
growing-stock-based allowable harvest (trees >= 40 cm DBH, per अनुसूची 4 & 5),
computed **per felling series**.

Plan: ``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md``.
Research: ``SUSTAINABLE_FOREST_MANAGEMENT_RESEARCH.md``.

P0 ships declaration only: :mod:`app.services.sustainable_fm.sfm_config`
(``SfmParams`` + the three-layer resolver) and the two models
(``SfmForestTypePrescription``, ``SfmProfile``). The classification / yield maths
land in later phases.
"""
