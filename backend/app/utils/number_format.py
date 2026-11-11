"""Arabic ↔ Devanagari number conversion and precision formatting."""

DEVANAGARI = "०१२३४५६७८९"
ARABIC = "0123456789"
_DEV_TO_ARABIC = str.maketrans(DEVANAGARI, ARABIC)
_ARABIC_TO_DEV = str.maketrans(ARABIC, DEVANAGARI)


def normalize_nepali_digits(value) -> str:
    """Convert Devanagari digits to Arabic. Used during upload/import.

    ``"१२३.४५"`` → ``"123.45"``
    ``"रु. १२३"`` → ``"रु. 123"``
    ``None`` → ``""``
    """
    if value is None:
        return ""
    return str(value).translate(_DEV_TO_ARABIC)


def format_devanagari(value, precision: int = 2) -> str:
    """Format a numeric value with given precision and convert to Devanagari digits.

    Rules:
      - ``None`` → ``"-"`` (dash)
      - Non-numeric → returned as-is (passthrough)
      - Rounds to *precision*, strips trailing zeros after decimal
      - Converts all Arabic digits in result to Devanagari

    Examples::

        125.00, 2  →  "१२५"
        0.0032, 4  →  "०.००३२"
        12.345, 1  →  "१२.३"
        None, 2    →  "-"
    """
    if value is None:
        return "-"
    try:
        num = float(value)
        s = f"{num:.{precision}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s == "" or s == "-0":
            s = "0"
        return s.translate(_ARABIC_TO_DEV)
    except (ValueError, TypeError):
        return str(value).translate(_ARABIC_TO_DEV)


def localize_digits(text, lang: str) -> str:
    """Write the digits of an already-formatted number, date or count in the language's own numerals.

    Nepali uses Devanagari digits (``412 ha`` -> ``४१२ ha``), English keeps Latin digits. Apply it to **formatted numbers only**,
    never to a whole sentence: a unit's name such as ``B3`` is user data and must keep its Latin characters.
    """
    if text is None:
        return ""
    text = str(text)
    return text.translate(_ARABIC_TO_DEV) if str(lang).lower().startswith("ne") else text
