"""NTFP sample-plot map (unit__ntfp_plots): the spec, the status of each plot, and the legend the print renderer draws."""
from types import SimpleNamespace
from uuid import uuid4

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from geoalchemy2.shape import from_shape  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from app.services import ntfp_records_service as svc  # noqa: E402
from app.services.operational_plan import prereq_check  # noqa: E402
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS  # noqa: E402
from app.services.operational_plan.thematic_overlay import _draw_point_surface  # noqa: E402


class _Db:
    """db.query(...).filter(...).all() answers the (plot_id,) rows of the stored records."""

    def __init__(self, observed):
        self._rows = [(pid,) for pid in observed]

    def query(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def all(self):
        return self._rows


def _plot(n, species, x, y):
    return SimpleNamespace(id=uuid4(), species_keys=species, location=from_shape(Point(x, y), srid=4326))


def test_the_spec_is_a_categorical_dot_map_that_needs_a_design():
    s = SPECS["unit__ntfp_plots"]
    assert (s.layer, s.viz, s.measure, s.requires) == ("ntfp_plot", "dotcat", "status_group", ["ntfp_design"])
    assert "ntfp_design" in prereq_check._TAGS


def test_each_plot_is_not_visited_partly_or_fully_recorded(monkeypatch):
    p1, p2, p3 = _plot(1, ["a", "b"], 85.0, 27.0), _plot(2, ["a", "b"], 85.1, 27.1), _plot(3, ["a"], 85.2, 27.2)
    monkeypatch.setattr(svc, "_plots", lambda db, cid: {1: p1, 2: p2, 3: p3})
    # plot 2 has one of its two species, plot 3 its only one
    pts = svc.plot_points(_Db([p2.id, p3.id]), uuid4())
    assert [(p["plot_number"], p["status_group"]) for p in pts] == [(1, "Not visited"), (2, "Partly recorded"), (3, "Recorded")]
    assert (pts[0]["lon"], pts[0]["lat"]) == (85.0, 27.0)


def test_no_design_means_no_points(monkeypatch):
    monkeypatch.setattr(svc, "_plots", lambda db, cid: {})
    assert svc.plot_points(_Db([]), uuid4()) == []


def test_the_renderer_draws_the_three_statuses_in_workspace_colours():
    pts = [{"lon": 85.0, "lat": 27.0, "status_group": "Recorded"}, {"lon": 85.1, "lat": 27.1, "status_group": "Not visited"}]
    fig, ax = plt.subplots()
    try:
        rows = _draw_point_surface(ax, SPECS["unit__ntfp_plots"], pts, [], {}, None, (84.9, 26.9, 85.3, 27.3))
    finally:
        plt.close(fig)
    # fixed order and colours, only the statuses present
    assert [c for c, _ in rows] == ["#2e7d32", "#9e9e9e"]
    assert [label for _, label in rows] == ["अभिलेख पूरा", "भ्रमण भएको छैन"]


def test_the_workspace_layer_names_this_map_variable():
    import re
    from pathlib import Path

    ts = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "ntfp.ts").read_text(encoding="utf-8")
    key = re.search(r"NTFP_PLOTS_SPEC_KEY = '([a-z]+__[a-z0-9_]+)'", ts).group(1)
    assert key in SPECS
    # the three status colours are the same on the page and in the print map
    from app.services.operational_plan.thematic_overlay import _NTFP_GROUP_COLOURS

    palette = dict(re.findall(r"(none|partial|done): '(#[0-9a-f]{6})'", ts))
    assert [palette["done"], palette["partial"], palette["none"]] == [_NTFP_GROUP_COLOURS[k] for k in ("Recorded", "Partly recorded", "Not visited")]
