"""Shared test fixture: the sample-plot inventory SFM now classifies a block from (owner, 2026-10-06).

A block's forest type comes from its OWN sample plots, so SFM tests that need a classified block add plots, not
stem-mapping trees.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text


def add_field_inventory(
    db,
    calc,
    block_name: str,
    *,
    species: str = "Shorea robusta",
    plots: int = 5,
    gs_per_ha: float = 150.0,
    seedlings_per_ha: float = 6000,
    saplings_per_ha: float = 2500,
    fic_id: str | None = None,
) -> str:
    """One completed field inventory for ``calc`` (re-used when ``fic_id`` is given) with ``plots`` sample plots
    of ``species`` in ``block_name`` and a block summary. Returns the field-inventory id."""
    if fic_id is None:
        fic_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO field_inventory_calculations "
                "(id, calculation_id, user_id, uploaded_filename, regeneration_area_sqm, "
                " sapling_area_sqm, pole_area_sqm, tree_area_sqm, status) "
                "VALUES (:id, :cid, :uid, 'fi.csv', 10, 25, 100, 500, 'completed')"
            ),
            {"id": fic_id, "cid": str(calc.id), "uid": str(calc.user_id)},
        )
    db.execute(
        text(
            "INSERT INTO field_inventory_block_summary "
            "(id, field_inventory_calculation_id, block_name, total_sample_plots, regeneration_per_ha, "
            " sapling_per_ha, total_growing_stock_m3_per_ha, dbh_class_breakdown) "
            "VALUES (:id, :fic, :bk, :n, :rg, :sp, :gs, CAST(:bd AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()), "fic": fic_id, "bk": block_name, "n": plots, "rg": seedlings_per_ha,
            "sp": saplings_per_ha, "gs": gs_per_ha, "bd": json.dumps({"40_50": {"timber": 100}}),
        },
    )
    for n in range(1, plots + 1):
        plot_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO field_inventory_sample_plots "
                "(id, field_inventory_calculation_id, block_name, sample_plot_number, location) "
                "VALUES (:id, :fic, :bk, :n, ST_GeogFromText('SRID=4326;POINT(84.01 27.01)'))"
            ),
            {"id": plot_id, "fic": fic_id, "bk": block_name, "n": n},
        )
        db.execute(
            text(
                "INSERT INTO field_inventory_measurements "
                "(id, sample_plot_id, stand_type, sn, species_scientific, dbh_cm, net_volume, count) "
                "VALUES (:id, :pid, 'Tree', 1, :sp, 45.0, 1.5, 1)"
            ),
            {"id": str(uuid.uuid4()), "pid": plot_id, "sp": species},
        )
    db.flush()
    return fic_id
