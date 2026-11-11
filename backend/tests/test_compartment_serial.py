"""A compartment the system names is C1, C2, C3 - never C-1 and never Compartment-1.

Three previews (MMU, slope, aspect/canopy), the coverage-invariant remainder and draw-new
each used to build their own serial, in two different formats. They now all call
`naming_strategies.compartment_serial`, and this pins both the format and that no path
goes back to formatting its own.
"""

import re
from pathlib import Path

from app.core.naming_strategies import compartment_serial, get_naming_strategy

APP = Path(__file__).resolve().parent.parent / "app"


def test_the_serial_is_C_then_the_number():
    assert [compartment_serial(i) for i in (1, 2, 3, 12)] == ["C1", "C2", "C3", "C12"]


def test_the_serial_round_trips_through_the_strategy_parser():
    strategy = get_naming_strategy("compartment")
    assert strategy.parse_name(compartment_serial(7)) == ("C", 7)
    assert (
        strategy.next_available_index([compartment_serial(1), compartment_serial(4)])
        == 5
    )


def test_no_module_formats_its_own_compartment_serial():
    """`f"C-{n}"`, `f"Compartment-{n}"` or `f"{prefix}-{n}"` next to a compartment level."""
    offenders = []
    bad = re.compile(r"""f["'](?:C|Compartment)-\{""")
    for path in APP.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                offenders.append(f"{path.relative_to(APP)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "build compartment serials with naming_strategies.compartment_serial:\n  "
        + "\n  ".join(offenders)
    )
