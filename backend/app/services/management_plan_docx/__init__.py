"""Management Plan DOCX export package.

Re-exports the main entry point for 10-year management plan generation.

See also:
    .plan_docx_builder — main assembler
    .plan_chapter_builders — per-chapter rendering
    .plan_narrative — narrative content generators
"""

from .plan_docx_builder import generate_10yr_management_plan_docx

__all__ = ["generate_10yr_management_plan_docx"]
