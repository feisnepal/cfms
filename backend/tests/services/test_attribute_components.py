"""Update attribute: the order components run in, and what each state allows (owner rule 2026-10-10)."""
from app.services import attribute_components as ac


def test_inventory_runs_before_the_components_that_read_it():
    order = list(ac.ORDER)
    assert order.index("raster") < order.index("classification") < order.index("inventory")
    assert order.index("inventory") < order.index("sfm") < order.index("hazard")


def test_a_runnable_item_has_no_open_step_and_an_unavailable_one_cannot_run():
    ok = ac._item("inventory", "Inventory analysis", "x", "up_to_date")
    assert ok["can_run"] is True and ok["available"] is True and ok["open_step"] == ""
    missing = ac._item("inventory", "Inventory analysis", "x", "unavailable", "Upload it.", "x", can_run=False, open_step="fieldinventory")
    assert missing["can_run"] is False and missing["available"] is False and missing["open_step"] == "fieldinventory"
