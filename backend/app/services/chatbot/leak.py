"""Data-leak guards in both directions (CHATBOT_PLAN C1.8, owner decision D1: household and coordinate data stay out of the assistant).

In:  a message that carries a phone number or a coordinate pair is refused before any model sees it, and is not stored.
Out: whatever a tool or a passage returns goes through a per-tool allow-list (an unexpected field is dropped) and a redactor
     (coordinate pairs, phone numbers, e-mail addresses) before it reaches the model, and the model's reply is redacted too.
The patterns are best effort: they catch the usual shapes, not every way of writing a number.
"""
from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Optional

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_PHONE = re.compile(r"(?<![\d.])(?:\+?977[-\s]?)?9[678]\d{8}(?!\d)")
_LATLON = re.compile(r"(?<![\d.])(-?\d{1,3}\.\d{3,})\s*[,;/\s]\s*(-?\d{1,3}\.\d{3,})(?![\d])")
_UTM = re.compile(r"(?<![\d.])(\d{6}(?:\.\d+)?)(?:\s*[,;/]\s*[Nn]?\s*|\s+[Nn]?\s*)(\d{7}(?:\.\d+)?)(?![\d])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _ascii_digits(text: str) -> str:
    return (text or "").translate(_DEVANAGARI_DIGITS)


def _is_latlon(m: "re.Match[str]") -> bool:
    return abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180


def private_data_in(text: str) -> Optional[str]:
    """What kind of private data the message carries ('phone number' or 'coordinates'), or None. Never returns the data itself."""
    flat = _ascii_digits(text)
    if _PHONE.search(flat):
        return "phone number"
    if any(_is_latlon(m) for m in _LATLON.finditer(flat)) or _UTM.search(flat):
        return "coordinates"
    return None


def redact(text: str) -> str:
    """Replace phone numbers, coordinate pairs and e-mail addresses with fixed markers (Devanagari digits are read as digits)."""
    out = _ascii_digits(text)
    out = _PHONE.sub("[phone removed]", out)
    out = _LATLON.sub(lambda m: "[coordinates removed]" if _is_latlon(m) else m.group(0), out)
    out = _UTM.sub("[coordinates removed]", out)
    out = _EMAIL.sub("[email removed]", out)
    # hand back the ASCII-digit version only when something was removed, so ordinary Nepali numerals stay as written
    return out if "removed]" in out else (text or "")


# What each tool may hand to the model. A field not listed is dropped, so a tool that starts returning more cannot leak it by accident.
ALLOWED_FIELDS: Dict[str, FrozenSet[str]] = {
    "search_help": frozenset({"reference", "note"}),
}


def filter_tool_result(tool: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the allowed top-level fields of a tool result and redact every string in them. An unknown tool yields only its error."""
    allowed = ALLOWED_FIELDS.get(tool)
    if allowed is None:
        return {"error": "unknown_tool"}
    return {k: _redact_value(v) for k, v in result.items() if k in allowed}


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    return value
