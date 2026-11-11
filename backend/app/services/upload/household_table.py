"""Find the household table inside a spreadsheet (UPLOAD_EXPERIENCE_PLAN.md, UP-3.2).

The reader used to assume a fixed layout: Nepali column names on row 1, their English names on row 2, households from row 3. A file with ONE header
row (or the header lower down, after a title) lost its first household silently, and a column it did not recognise was ignored without a word.

:func:`locate_table` looks at the first few rows, takes the first one that holds several known column names (Nepali or English) as the header,
skips an English-names row directly below it if there is one, and reports the columns it did not understand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

MAX_ROWS_SCANNED = 8

# Nepali header -> field name (the template's own names, plus the spellings people actually type)
HOUSEHOLD_HEADER_MAP: Dict[str, str] = {
    "घर नंवर": "house_no",
    "घर नंबर": "house_no",  # both spellings are in use
    "घर नम्बर": "house_no",
    "थर": "surname",
    "घरमुली पुरूष": "household_head_male",
    "घरमुली महिला": "household_head_female",
    "टोल ठेगाना": "address_tole",
    "अक्षाँस": "latitude",
    "अक्षांश": "latitude",
    "देशान्तर": "longitude",
    "महिला संख्या": "female_count",
    "पुरूष संख्या": "male_count",
    "जमिन (ropani)": "land_area",
    "जमिन (kaththa)": "land_area",
    "पेशा (वनमा आश्रीत)": "forest_based_occupation",
    "पेशा (अन्य)": "other_occupation",
    "गाइ गोरू": "cow_ox_count",
    "भैसी राँगा": "buffalo_count",
    "बाख्रा भेडा": "goat_sheep_count",
    "बन पैदाबारको माग (काठ क्यू.फि.)": "timber_demand_cft",
    "बन पैदाबारको माग (पोल)": "pole_demand",
    "बन पैदाबारको माग (दाउरा) भारी": "firewood_demand_bhari",
    "बन पैदाबारको माग (घाँस) भारी": "grass_demand_bhari",
    "बन पैदाबारको माग (सोत्तर) भारी": "bedding_demand_bhari",
    "जातिय वर्गिकरण": "caste_classification_ne",
    "अन्य समूहमा सदस्यता": "other_group_membership",
    "सम्पन्नताको स्तर": "prosperity_level",
    "कैफियत": "remarks"
}


@dataclass
class LocatedTable:
    header_index: int  # 0-based index of the header row in the sheet
    headers: List[str]  # one entry per column, '' for a blank header (positions are kept so data stays aligned)
    data_start_index: int  # 0-based index of the first household row
    unrecognised: List[str] = field(default_factory=list)

    @property
    def header_row_number(self) -> int:  # 1-based, as the user sees it in Excel
        return self.header_index + 1

    @property
    def first_data_row_number(self) -> int:
        return self.data_start_index + 1


def _cell(c: Any) -> str:
    return str(c).strip() if c is not None else ""


def locate_table(all_rows: Sequence[Sequence[Any]], header_map: Dict[str, str]) -> Optional[LocatedTable]:
    """The header row, where the households start, and the columns we did not understand; None when no row looks like a header."""
    from .column_synonyms import resolve_column

    english = set(header_map.values())
    known = set(header_map) | english

    def is_known(c: str) -> bool:
        # the template's own names, or any spelling/synonym the shared module knows (घर नंबर, पुरुष संख्या, House No ...)
        return c in known or resolve_column(c, "households") is not None

    for i, row in enumerate(all_rows[:MAX_ROWS_SCANNED]):
        cells = [_cell(c) for c in row]
        filled = [c for c in cells if c]
        recognised = [c for c in filled if is_known(c)]
        # a header row names several known columns; a very narrow sheet needs at least two
        if len(recognised) < (3 if len(filled) > 3 else 2):
            continue
        start = i + 1
        if i + 1 < len(all_rows):
            below = [_cell(c) for c in all_rows[i + 1]]
            below_filled = [c for c in below if c]
            # the template's second row holds the English field names: it is a header too, not a household
            if below_filled and sum(1 for c in below_filled if c in english or is_known(c)) >= max(2, len(below_filled) // 2):
                start = i + 2
        return LocatedTable(
            header_index=i,
            headers=cells,
            data_start_index=start,
            unrecognised=[c for c in filled if not is_known(c)],
        )
    return None
