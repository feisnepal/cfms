"""A block's state decides whether it can have a forest type (owner, 2026-10-06)."""
from app.core.constants import SFM_MIN_PLOTS_PER_BLOCK
from app.services.sustainable_fm.block_status import (
    CLASSIFIED, INVENTORY_MISSING, NON_FOREST, PROVISIONAL, block_state,
)


def test_the_plot_threshold_is_five():
    assert SFM_MIN_PLOTS_PER_BLOCK == 5


def test_forest_land_follows_its_own_plot_count():
    assert block_state("forest", 0) == INVENTORY_MISSING
    assert block_state("forest", 1) == PROVISIONAL
    assert block_state("forest", 4) == PROVISIONAL
    assert block_state("forest", 5) == CLASSIFIED
    assert block_state("forest", 40) == CLASSIFIED


def test_non_forest_land_never_needs_plots_whatever_their_count():
    for land in ("grassland", "rangeland", "river", "water", "snow", "other_nonforest"):
        assert block_state(land, 0) == NON_FOREST
        assert block_state(land, 12) == NON_FOREST  # a mislabelled block still has no forest type
