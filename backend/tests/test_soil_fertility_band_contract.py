"""The fertility class / description contract (SFM tracker row P5).

``generate_soil_interpretations`` wrote ``"class"`` straight from ``soil_data`` but
chose the prose with a chain of equality tests against a capitalised vocabulary -
"Very High" / "High" / "Medium" / "Low" / else. The producer,
``app/core/soil_fertility.py::FertilityClass``, emits lowercase ``high`` / ``good`` /
``moderate`` / ``low`` / ``very_low``, which differ from that chain in case *and* in
naming. All five values therefore missed all four comparisons and landed in the
``else``, which was written as though it meant "Very Low".

On calculation ``b67f9e1c`` that produced::

    {"class": "high", "score": 110,
     "description": "Poor soil fertility. Significant limitations for tree growth."}

- a soil classified ``high`` and described as poor, in the same object. It is the P1
failure family again: a value that looked fine and was not.

:func:`test_every_producer_class_resolves_to_its_own_band` and
:func:`test_class_and_description_can_never_disagree` are the load-bearing tests.
The rest pin the two traps in the fix itself: the two vocabularies *collide* (the
producer's ``high`` is the top band while the UI's "High" is the second), so a
generous alias table would silently re-map data; and an unrecognised class must be
reported as unrecognised rather than confidently called "Very Low".
"""

from __future__ import annotations

import pytest

from app.core.soil_fertility import FertilityClass
from app.services.analysis import (
    _FERTILITY_BANDS,
    _normalise_fertility_class,
    _resolve_fertility_band,
    generate_soil_interpretations,
)

# What the producer can actually emit, in descending score order. Read off the enum
# so a new band has to be given prose rather than being silently unrecognised.
PRODUCER_CLASSES = [member.value for member in FertilityClass]

# "Poor soil fertility" is the Very Low prose, so its presence is the contradiction
# this whole file exists to prevent.
POOR_MARKER = "Poor soil fertility"


def _interpret(fertility_class, score=110):
    return generate_soil_interpretations(
        {"fertility_class": fertility_class, "fertility_score": score}
    )["fertility_interpretation"]


def test_the_producer_vocabulary_is_exactly_what_the_bands_cover():
    """The band table and the producing enum must not drift apart."""
    assert set(PRODUCER_CLASSES) == set(_FERTILITY_BANDS), (
        "soil_fertility.FertilityClass and analysis._FERTILITY_BANDS disagree. Every "
        "class needs its own band row, or it will be reported as unrecognised: "
        f"producer={sorted(PRODUCER_CLASSES)} bands={sorted(_FERTILITY_BANDS)}"
    )


def test_every_producer_class_resolves_to_its_own_band():
    """The bug itself: each producer class must resolve, and not to a shared else."""
    for value in PRODUCER_CLASSES:
        band = _resolve_fertility_band(value)
        assert band is not None, f"{value!r} did not resolve to a band"
        assert band["description"], f"{value!r} resolved but has no description"


def test_class_and_description_can_never_disagree():
    """End to end, per class: only ``very_low`` may be described as poor."""
    for value in PRODUCER_CLASSES:
        info = _interpret(value)
        assert info["recognised"] is True, f"{value!r} was not recognised"
        band = _FERTILITY_BANDS[value]
        # Both the label and the prose come from the one band row, so they cannot
        # come from different vocabularies.
        assert info["class"] == band["label"]
        assert info["description"] == band["description"]
        assert (POOR_MARKER in info["description"]) is (value == "very_low"), (
            f"{value!r} is described as {'poor' if POOR_MARKER in info['description'] else 'not poor'}, "
            f"but the class is {info['class']!r}"
        )


def test_the_reported_case_high_110_is_not_described_as_poor():
    """The exact object the owner reported on ``b67f9e1c``."""
    info = _interpret("high", 110)
    assert info["class"] == "Very High"
    assert info["class_key"] == "high"
    assert info["score"] == 110
    assert POOR_MARKER not in info["description"]
    assert info["expected_growth"]
    assert info["recommendation"]


def test_score_is_passed_through_untouched():
    """The bug was a vocabulary mismatch, not a threshold bug - guard the score."""
    for score in (0, 19, 20, 40, 60, 80, 110):
        assert _interpret("high", score)["score"] == score


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  HIGH  ", "Very High"),  # padding
        ("High", "Very High"),  # case
        ("MODERATE", "Medium"),  # case
        (" very_low ", "Very Low"),  # padding
        ("Very_Low", "Very Low"),  # mixed separator
    ],
)
def test_case_and_whitespace_are_not_what_broke_it(raw, expected):
    assert _resolve_fertility_band(raw)["label"] == expected


@pytest.mark.parametrize("value", ["bogus", "excellent", "very high", "   "])
def test_unrecognised_is_reported_not_guessed(value):
    """The old ``else`` claimed "Very Low" with full confidence. It must not."""
    assert _resolve_fertility_band(value) is None
    info = _interpret(value)
    assert info["recognised"] is False
    assert POOR_MARKER not in info["description"]
    assert "Unrecognised" in info["description"]
    assert info["class"] == value  # surfaced verbatim, not replaced by a guess


@pytest.mark.parametrize("value", [None, ""])
def test_absent_reading_is_not_the_same_as_an_unrecognised_one(value):
    """Falsy means "no fertility reading", so no band is invented for it.

    Distinct from the case above: there the class was present but meaningless, and
    had to be flagged. Here there is nothing to interpret at all.
    """
    assert _resolve_fertility_band(value) is None
    assert "fertility_interpretation" not in generate_soil_interpretations(
        {"fertility_class": value, "fertility_score": 110}
    )


def test_ui_labels_are_not_accepted_as_input():
    """The two vocabularies collide, so accepting both would re-map data.

    The producer's ``high`` is the TOP band; the UI's "High" is the SECOND. Only
    producer tokens are ever written to ``class``, so only they are resolved -
    anything else is flagged rather than quietly assigned a band.
    """
    # 'High' folds onto the producer token 'high' = the top band, NOT the second.
    assert _resolve_fertility_band("High")["label"] == "Very High"
    # These are UI-only labels with no producer token, so they are unrecognised.
    for ui_only in ("Very High", "Medium"):
        assert _resolve_fertility_band(ui_only) is None, (
            f"{ui_only!r} is a UI display label, not a producer class; accepting it "
            "would re-map data to a band the producer never meant"
        )


def test_normalisation_collapses_rather_than_producing_empty_tokens():
    assert _normalise_fertility_class("very  low") == "very_low"
    assert _normalise_fertility_class("__high__") == "high"
    assert _normalise_fertility_class("Very-High") == "very_high"
    assert _normalise_fertility_class(None) == ""


def test_no_fertility_class_means_no_interpretation_key():
    """A soil reading with no fertility must not gain a band by accident."""
    assert "fertility_interpretation" not in generate_soil_interpretations({"ph": 6.0})


def test_other_interpretations_are_untouched():
    """This is a fertility-band change; the other readings must still be built."""
    result = generate_soil_interpretations(
        {"ph": 6.0, "organic_carbon": 2.0, "fertility_class": "moderate"}
    )
    assert set(result) >= {"fertility_interpretation"}
    assert result["fertility_interpretation"]["class"] == "Medium"
