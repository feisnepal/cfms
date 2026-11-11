"""Download the bundled Devanagari fonts. Run from ``backend/``:

    python -m app.assets.fonts.fetch_fonts

Idempotent — overwrites the two .ttf files in this directory. See README.md.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_NOTO_BASE = (
    "https://github.com/notofonts/notofonts.github.io/raw/main/"
    "fonts/NotoSansDevanagari/hinted/ttf/"
)
_MUKTA_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/mukta/"

# local filename -> url
_FILES = {
    "Mukta-Regular.ttf": _MUKTA_BASE + "Mukta-Regular.ttf",
    "Mukta-Bold.ttf": _MUKTA_BASE + "Mukta-Bold.ttf",
    "Mukta-OFL.txt": _MUKTA_BASE + "OFL.txt",
    "NotoSansDevanagari-Regular.ttf": _NOTO_BASE + "NotoSansDevanagari-Regular.ttf",
    "NotoSansDevanagari-Bold.ttf": _NOTO_BASE + "NotoSansDevanagari-Bold.ttf",
}


def main() -> int:
    for name, url in _FILES.items():
        dest = _HERE / name
        print(f"→ {url}")
        try:
            with urllib.request.urlopen(
                url, timeout=30
            ) as resp:  # noqa: S310 -- fixed https URL
                data = resp.read()
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- surface any download failure to the operator
            print(f"  FAILED: {exc}", file=sys.stderr)
            return 1
        dest.write_bytes(data)
        print(f"  wrote {dest.name} ({len(data) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
