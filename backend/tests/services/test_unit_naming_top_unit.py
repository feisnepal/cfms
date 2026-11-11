"""Names of units and sub-units (owner, 2026-10-11): C1 / C1-SC1, B1 / B1-SB1. No forest name; two levels only."""
from app.core.naming_strategies import block_serial, compartment_serial, sub_unit_serial, top_unit_name
from app.services.compartment_divide_service import _child_name


class _P:
    def __init__(self, name):
        self.name = name
        self.block_name = name


def test_the_four_formats():
    assert compartment_serial(2) == "C2" and block_serial(2) == "B2"
    assert sub_unit_serial(compartment=True, parent_name="C1", index=3) == "C1-SC3"
    assert sub_unit_serial(compartment=False, parent_name="B1", index=3) == "B1-SB3"


def test_a_piece_of_a_sub_unit_is_named_from_the_top_unit_never_nested():
    assert top_unit_name("C1-SC3") == "C1" and top_unit_name("B2-SB1") == "B2" and top_unit_name("C7") == "C7"
    assert _child_name(_P("C1"), "sub_compartments", "", 4) == "C1-SC4"
    assert _child_name(_P("C1-SC3"), "sub_compartments", "", 4) == "C1-SC4"  # was C1-SC3-SC4
    assert _child_name(_P("B2-SB1"), "sub_blocks", "", 2) == "B2-SB2"
    assert _child_name(None, "compartments", "", 3) == "C3"
