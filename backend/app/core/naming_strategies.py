from __future__ import annotations

import re
import abc
from typing import Dict, Iterable, List, Optional, Set, Tuple

NEPALI_DIGITS: Dict[str, str] = {
    "0": "०", "1": "१", "2": "२", "3": "३", "4": "४",
    "5": "५", "6": "६", "7": "७", "8": "८", "9": "९",
}
ARABIC_DIGITS: Dict[str, str] = {v: k for k, v in NEPALI_DIGITS.items()}
NEPALI_NUMERAL_RE = re.compile(r"^[०१२३४५६७८९]+$")


def to_nepali_numeral(n: int) -> str:
    if n < 0:
        raise ValueError(f"Negative numbers not supported: {n}")
    return "".join(NEPALI_DIGITS.get(ch, ch) for ch in str(n))


def from_nepali_numeral(s: str) -> int:
    arabic = "".join(ARABIC_DIGITS.get(ch, ch) for ch in s)
    return int(arabic)


def is_nepali_numeral(s: str) -> bool:
    return bool(NEPALI_NUMERAL_RE.match(s))


class SequenceGenerator:
    def __init__(self, start_at: int = 1):
        self._current: int = start_at
        self._start_at: int = start_at

    def next(self) -> int:
        value = self._current
        self._current += 1
        return value

    def peek(self) -> int:
        return self._current

    def reset(self, start_at: Optional[int] = None) -> None:
        self._current = start_at if start_at is not None else self._start_at


class ValidationResult:
    def __init__(
        self,
        valid: bool,
        error_key: Optional[str] = None,
        error_params: Optional[Dict[str, str]] = None,
    ):
        self.valid = valid
        self.error_key = error_key
        self.error_params = error_params or {}

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, key: str, **params: str) -> "ValidationResult":
        return cls(valid=False, error_key=key, error_params=params)


NameValidator = callable


def validate_not_empty(name: str) -> ValidationResult:
    if not name or not name.strip():
        return ValidationResult.fail("geometry.edit.no_name_empty")
    return ValidationResult.ok()


def validate_max_length(max_len: int) -> NameValidator:
    def _validator(name: str) -> ValidationResult:
        if len(name) > max_len:
            return ValidationResult.fail("geometry.edit.name_too_long", max=str(max_len))
        return ValidationResult.ok()
    return _validator


def validate_not_duplicate(name: str, existing_names: Set[str]) -> ValidationResult:
    stripped = name.strip()
    if stripped in existing_names:
        return ValidationResult.fail("geometry.edit.duplicate_name", name=name)
    return ValidationResult.ok()


def validate_no_special_chars(name: str) -> ValidationResult:
    if not re.match(r"^[\w\s\-_\u0900-\u097F]+$", name):
        return ValidationResult.fail(
            "geometry.edit.invalid_name_format",
            pattern="Letters, numbers, spaces, hyphens, underscores, and Nepali characters only",
        )
    return ValidationResult.ok()


class NamingStrategy(abc.ABC):
    @property
    @abc.abstractmethod
    def id(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def label(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def label_np(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def is_compartment(self) -> bool:
        ...

    @abc.abstractmethod
    def generate_default_name(self, index: int, use_nepali: bool = False) -> str:
        ...

    @abc.abstractmethod
    def generate_name(self, prefix: str, index: int, use_nepali: bool = False) -> str:
        ...

    @abc.abstractmethod
    def parse_name(self, name: str) -> Optional[Tuple[str, int]]:
        ...

    @abc.abstractmethod
    def next_available_index(self, existing_names: Iterable[str]) -> int:
        ...

    @abc.abstractmethod
    def validate(self, name: str, existing_names: Set[str]) -> ValidationResult:
        ...

    @property
    @abc.abstractmethod
    def pattern(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def pattern_np(self) -> str:
        ...


class BlockNamingStrategy(NamingStrategy):
    _PREFIX_EN = "Block "
    _PREFIX_NP = "ब्लक "

    @property
    def id(self) -> str:
        return "block"

    @property
    def label(self) -> str:
        return "Block"

    @property
    def label_np(self) -> str:
        return "ब्लक"

    @property
    def is_compartment(self) -> bool:
        return False

    @property
    def pattern(self) -> str:
        return "Block {N}"

    @property
    def pattern_np(self) -> str:
        return "ब्लक {N}"

    def generate_default_name(self, index: int, use_nepali: bool = False) -> str:
        if use_nepali:
            return f"{self._PREFIX_NP}{to_nepali_numeral(index)}"
        return f"B{index}"  # owner 2026-10-11: B1, B2 ... (the forest is already named; no "Block 1", no forest name)

    def generate_name(self, prefix: str, index: int, use_nepali: bool = False) -> str:
        if use_nepali:
            return f"{prefix} {to_nepali_numeral(index)}"
        return f"{prefix} {index}"

    _EN_NAME_RE = re.compile(r"^(Block\s+)(\d+)$", re.IGNORECASE)
    _NP_NAME_RE = re.compile(r"^(ब्लक\s+)([०१२३४५६७८९]+)$")
    _GENERIC_NAME_RE = re.compile(r"^(.+?)\s+(\d+)$")
    _SERIAL_RE = re.compile(r"^(B)(\d+)$")

    def parse_name(self, name: str) -> Optional[Tuple[str, int]]:
        m = self._SERIAL_RE.match(name)
        if m:
            return (m.group(1), int(m.group(2)))
        m = self._EN_NAME_RE.match(name)
        if m:
            return (m.group(1).strip(), int(m.group(2)))
        m = self._NP_NAME_RE.match(name)
        if m:
            return (m.group(1).strip(), from_nepali_numeral(m.group(2)))
        m = self._GENERIC_NAME_RE.match(name)
        if m:
            return (m.group(1), int(m.group(2)))
        return None

    def next_available_index(self, existing_names: Iterable[str]) -> int:
        max_num = 0
        for name in existing_names:
            parsed = self.parse_name(name)
            if parsed and parsed[1] > max_num:
                max_num = parsed[1]
        return max_num + 1

    def validate(self, name: str, existing_names: Set[str]) -> ValidationResult:
        r = validate_not_empty(name)
        if not r.valid:
            return r
        r = validate_max_length(100)(name)
        if not r.valid:
            return r
        r = validate_not_duplicate(name, existing_names)
        if not r.valid:
            return r
        r = validate_no_special_chars(name)
        if not r.valid:
            return r
        return ValidationResult.ok()


class CompartmentNamingStrategy(NamingStrategy):
    @property
    def id(self) -> str:
        return "compartment"

    @property
    def label(self) -> str:
        return "Compartment"

    @property
    def label_np(self) -> str:
        return "कम्पार्टमेन्ट"

    @property
    def is_compartment(self) -> bool:
        return True

    @property
    def pattern(self) -> str:
        return "C{N}"

    @property
    def pattern_np(self) -> str:
        return "कम्पार्टमेन्ट {N}"

    def generate_default_name(self, index: int, use_nepali: bool = False) -> str:
        if use_nepali:
            return f"{self.label_np} {to_nepali_numeral(index)}"
        return f"C{index}"

    def generate_name(self, prefix: str, index: int, use_nepali: bool = False) -> str:
        if use_nepali:
            return f"{prefix} {to_nepali_numeral(index)}"
        return f"{prefix}{index}"

    _SHORT_RE = re.compile(r"^C\s*(\d+)$", re.IGNORECASE)
    _LONG_EN_RE = re.compile(r"^Compartment\s+(\d+)$", re.IGNORECASE)
    _LONG_NP_RE = re.compile(r"^कम्पार्टमेन्ट\s+([०१२३४५६७८९]+)$")
    _SUB_RE = re.compile(r"^SC\s*(\d+)$", re.IGNORECASE)

    def parse_name(self, name: str) -> Optional[Tuple[str, int]]:
        m = self._SHORT_RE.match(name)
        if m:
            return ("C", int(m.group(1)))
        m = self._LONG_EN_RE.match(name)
        if m:
            return ("Compartment", int(m.group(1)))
        m = self._LONG_NP_RE.match(name)
        if m:
            return ("कम्पार्टमेन्ट", from_nepali_numeral(m.group(1)))
        m = self._SUB_RE.match(name)
        if m:
            return ("SC", int(m.group(1)))
        return None

    def next_available_index(self, existing_names: Iterable[str]) -> int:
        max_num = 0
        for name in existing_names:
            parsed = self.parse_name(name)
            if parsed and parsed[1] > max_num:
                max_num = parsed[1]
        return max_num + 1

    def validate(self, name: str, existing_names: Set[str]) -> ValidationResult:
        r = validate_not_empty(name)
        if not r.valid:
            return r
        r = validate_max_length(100)(name)
        if not r.valid:
            return r
        r = validate_not_duplicate(name, existing_names)
        if not r.valid:
            return r
        if not re.match(r"^[A-Za-z\u0900-\u097F][\w\s\-_\u0900-\u097F]*\d+$", name):
            return ValidationResult.fail(
                "geometry.edit.invalid_name_format",
                pattern="Letter or Nepali char followed by alphanumeric, ending with number",
            )
        return ValidationResult.ok()


_STRATEGIES: Dict[str, NamingStrategy] = {
    "block": BlockNamingStrategy(),
    "compartment": CompartmentNamingStrategy(),
}


def get_naming_strategy(strategy_id: str) -> NamingStrategy:
    if strategy_id not in _STRATEGIES:
        raise KeyError(f"Unknown naming strategy: {strategy_id}")
    return _STRATEGIES[strategy_id]


def resolve_naming_strategy(*, is_compartment: bool) -> NamingStrategy:
    return _STRATEGIES["compartment"] if is_compartment else _STRATEGIES["block"]


def compartment_serial(index: int) -> str:
    """The one serial a compartment gets when the system names it: C1, C2, C3.

    Never `C-1` or `Compartment-1`. Every code path that mints a compartment name
    (auto-block previews, the coverage-invariant remainder, draw-new) goes through here,
    so the CompartmentNamingStrategy pattern `C{N}` and its parser stay the only format.
    """
    return _STRATEGIES["compartment"].generate_default_name(index)


def register_naming_strategy(strategy: NamingStrategy) -> None:
    _STRATEGIES[strategy.id] = strategy


def block_serial(index: int) -> str:
    """``B1``, ``B2`` ... -- the one name format for a system-named block."""
    return _STRATEGIES["block"].generate_default_name(index)


def unit_serial(*, is_compartment: bool, index: int) -> str:
    """The name the system gives a top-level unit: ``C1`` for a compartment, ``B1`` for a block."""
    return _STRATEGIES["compartment" if is_compartment else "block"].generate_default_name(index)


def sub_unit_naming_pattern(*, compartment: bool) -> str:
    """The default pattern a sub-unit divide uses when the caller specifies none
    (FS-4a.2): ``{parent_name}-SC{index}`` for a sub-compartment,
    ``{parent_name}-SB{index}`` for a sub-block. Both use the same
    ``{parent_name}`` / ``{index}`` placeholders ``compartment_divide_service``'s
    ``_apply_naming_pattern`` already recognises, so a sub-block divide (FS-4a.5+)
    needs no new templating syntax, only this new default."""
    return "{parent_name}-SC{index}" if compartment else "{parent_name}-SB{index}"


_SUB_SUFFIX_RE = re.compile(r"-S[BC]\d+.*$")


def top_unit_name(name: str) -> str:
    """The top-level unit a name belongs to: ``C1-SC3`` -> ``C1``, ``B2-SB1`` -> ``B2``. A division always names its pieces from this, so a
    piece of a sub-unit is ``C1-SC4`` and never ``C1-SC3-SC4`` (two levels only: unit and sub-unit)."""
    return _SUB_SUFFIX_RE.sub("", name or "") or (name or "")


def sub_unit_serial(*, compartment: bool, parent_name: str, index: int) -> str:
    """Render the pattern above for one child without the caller knowing the
    template syntax -- e.g. ``sub_unit_serial(compartment=False, parent_name="B1",
    index=1)`` -> ``"B1-SB1"``."""
    pattern = sub_unit_naming_pattern(compartment=compartment)
    return pattern.replace("{parent_name}", parent_name).replace("{index}", str(index))
