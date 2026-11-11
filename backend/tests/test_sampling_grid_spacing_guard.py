"""A zero grid spacing never advances the lattice, so the grid loops ran forever (a sliver unit whose target spacing rounded to 0 m)."""
import pytest

from app.services.sampling import generate_systematic_grid

SQUARE = "POLYGON((85.5 27.4, 85.501 27.4, 85.501 27.401, 85.5 27.401, 85.5 27.4))"


@pytest.mark.timeout(20)
@pytest.mark.parametrize("spacing", [0, -5, None])
def test_a_non_positive_spacing_is_refused_instead_of_looping_forever(spacing):
    with pytest.raises(ValueError):
        generate_systematic_grid(85.5, 27.4, 85.501, 27.401, spacing, SQUARE, 0.0)


@pytest.mark.timeout(20)
def test_a_small_positive_spacing_still_makes_a_grid():
    pts = generate_systematic_grid(85.5, 27.4, 85.501, 27.401, 25, SQUARE, 0.0)
    assert len(pts) > 0
