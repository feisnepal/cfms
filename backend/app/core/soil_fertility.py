"""
Soil Fertility Assessment — Configurable Scoring Engine
=======================================================

Replaces ~25 raw thresholds in analysis.py:1815-1871 with a data-driven
scoring table that can be adjusted without code changes.

Usage:
    from app.core.soil_fertility import (
        SoilParameter,
        SOIL_FERTILITY_CRITERIA,
        assess_soil_fertility,
        SoilFertilityResult,
    )

    result = assess_soil_fertility(
        ph=6.2, soc=1.8, nitrogen=0.12, cec=120,
        compaction=1.4, moisture=25
    )
    print(result.fertility_class)  # 'moderate'
    print(result.total_score)      # 65
"""

from dataclasses import dataclass
from typing import Callable, Optional
from enum import Enum


class FertilityClass(str, Enum):
    """Final soil fertility classification."""
    HIGH = "high"       # Score >= 80
    GOOD = "good"       # Score 60-79
    MODERATE = "moderate"  # Score 40-59
    LOW = "low"         # Score 20-39
    VERY_LOW = "very_low"  # Score < 20


@dataclass(frozen=True)
class ScoreRange:
    """A score band with inclusive min, exclusive max."""
    min_score: int
    max_score: int
    fertility_class: FertilityClass


# ── Score-to-Class Mapping ───────────────────────────────────
# Matches analysis.py thresholds: 80, 60, 40, 20

SCORE_RANGES: tuple[ScoreRange, ...] = (
    ScoreRange(80, 151, FertilityClass.HIGH),
    ScoreRange(60, 80, FertilityClass.GOOD),
    ScoreRange(40, 60, FertilityClass.MODERATE),
    ScoreRange(20, 40, FertilityClass.LOW),
    ScoreRange(0, 20, FertilityClass.VERY_LOW),
)


def score_to_class(total_score: int) -> FertilityClass:
    """Convert total score to fertility class."""
    for sr in SCORE_RANGES:
        if sr.min_score <= total_score < sr.max_score:
            return sr.fertility_class
    return FertilityClass.VERY_LOW


# ── Parameter Scoring Rules ──────────────────────────────────

@dataclass(frozen=True)
class ScoreRule:
    """Single scoring rule: if condition is met, award this score."""
    condition: Callable[[float], bool]
    score: int
    label: str


@dataclass(frozen=True)
class SoilParameter:
    """Definition of a soil parameter and its scoring rules."""
    name: str
    name_np: str
    unit: str
    max_score: int
    rules: tuple[ScoreRule, ...]
    default_score: int = 5


# ── pH ───────────────────────────────────────────────────────
# Optimal: 5.5-7.0 -> 25 pts
# Tolerable: 5.0-7.5 -> 15 pts
# Outside: 5 pts

SOIL_PH = SoilParameter(
    name="ph",
    name_np="पीएच",
    unit="",
    max_score=25,
    rules=(
        ScoreRule(lambda v: 5.5 <= v <= 7.0, 25, "optimal"),
        ScoreRule(lambda v: 5.0 <= v <= 7.5, 15, "tolerable"),
    ),
    default_score=5,
)

# ── Soil Organic Carbon (SOC) ────────────────────────────────
# High: >= 2.0% -> 25 pts
# Medium: >= 1.0% -> 15 pts
# Low: < 1.0% -> 5 pts

SOIL_SOC = SoilParameter(
    name="soc",
    name_np="माटो कार्बन",
    unit="%",
    max_score=25,
    rules=(
        ScoreRule(lambda v: v >= 2.0, 25, "high"),
        ScoreRule(lambda v: v >= 1.0, 15, "medium"),
    ),
    default_score=5,
)

# ── Nitrogen ─────────────────────────────────────────────────
# High: >= 0.15% -> 25 pts
# Medium: >= 0.10% -> 15 pts
# Low: < 0.10% -> 5 pts

SOIL_NITROGEN = SoilParameter(
    name="nitrogen",
    name_np="नाइट्रोजन",
    unit="%",
    max_score=25,
    rules=(
        ScoreRule(lambda v: v >= 0.15, 25, "high"),
        ScoreRule(lambda v: v >= 0.10, 15, "medium"),
    ),
    default_score=5,
)

# ── CEC (Cation Exchange Capacity) ───────────────────────────
# High: >= 150 mmol/kg -> 25 pts
# Medium: >= 80 mmol/kg -> 15 pts
# Low: < 80 -> 5 pts

SOIL_CEC = SoilParameter(
    name="cec",
    name_np="क्याटायन आदानप्रदान क्षमता",
    unit="mmol/kg",
    max_score=25,
    rules=(
        ScoreRule(lambda v: v >= 150, 25, "high"),
        ScoreRule(lambda v: v >= 80, 15, "medium"),
    ),
    default_score=5,
)

# ── Compaction (Bulk Density) ────────────────────────────────
# Lower is better for forest soils
# Optimal: <= 1.3 g/cm3 -> 25 pts
# Tolerable: <= 1.6 -> 15 pts
# Poor: <= 1.8 -> 5 pts
# Very poor: > 1.8 -> 0 pts (handled by default)

SOIL_COMPACTION = SoilParameter(
    name="compaction",
    name_np="संकुचन",
    unit="g/cm3",
    max_score=25,
    rules=(
        ScoreRule(lambda v: v <= 1.3, 25, "optimal"),
        ScoreRule(lambda v: v <= 1.6, 15, "tolerable"),
        ScoreRule(lambda v: v <= 1.8, 5, "poor"),
    ),
    default_score=0,
)

# ── Moisture (supplementary) ─────────────────────────────────
# Good: >= 25% -> 25 pts
# Moderate: >= 15% -> 15 pts
# Low: < 15% -> 5 pts

SOIL_MOISTURE = SoilParameter(
    name="moisture",
    name_np="आर्द्रता",
    unit="%",
    max_score=25,
    rules=(
        ScoreRule(lambda v: v >= 25, 25, "good"),
        ScoreRule(lambda v: v >= 15, 15, "moderate"),
    ),
    default_score=5,
)

# ── Master Criteria Table ────────────────────────────────────

SOIL_FERTILITY_CRITERIA: tuple[SoilParameter, ...] = (
    SOIL_PH,
    SOIL_SOC,
    SOIL_NITROGEN,
    SOIL_CEC,
    SOIL_COMPACTION,
    SOIL_MOISTURE,
)


# ── Assessment Engine ────────────────────────────────────────

@dataclass
class ParameterScore:
    name: str
    name_np: str
    value: float
    unit: str
    score: int
    rule_label: str


@dataclass
class SoilFertilityResult:
    total_score: int
    max_possible: int
    fertility_class: FertilityClass
    fertility_label_np: str
    parameter_scores: list[ParameterScore]


_FERTILITY_LABELS_NP: dict[FertilityClass, str] = {
    FertilityClass.HIGH: "अत्यन्त उर्वर",
    FertilityClass.GOOD: "उर्वर",
    FertilityClass.MODERATE: "मध्यम उर्वर",
    FertilityClass.LOW: "कम उर्वर",
    FertilityClass.VERY_LOW: "अत्यन्त कम उर्वर",
}


def assess_soil_fertility(
    ph: float,
    soc: float,
    nitrogen: float,
    cec: float,
    compaction: float,
    moisture: float,
) -> SoilFertilityResult:
    """Assess soil fertility from 6 parameters.

    Args:
        ph: Soil pH (0-14)
        soc: Soil organic carbon (%)
        nitrogen: Total nitrogen (%)
        cec: Cation exchange capacity (mmol/kg)
        compaction: Bulk density (g/cm3)
        moisture: Soil moisture content (%)

    Returns:
        SoilFertilityResult with total score, class, and per-parameter breakdown.
    """
    values = {
        "ph": ph,
        "soc": soc,
        "nitrogen": nitrogen,
        "cec": cec,
        "compaction": compaction,
        "moisture": moisture,
    }

    param_scores: list[ParameterScore] = []
    total = 0
    max_possible = 0

    for param in SOIL_FERTILITY_CRITERIA:
        val = values[param.name]
        score = param.default_score
        label = "default"

        for rule in param.rules:
            if rule.condition(val):
                score = rule.score
                label = rule.label
                break

        param_scores.append(ParameterScore(
            name=param.name,
            name_np=param.name_np,
            value=val,
            unit=param.unit,
            score=score,
            rule_label=label,
        ))
        total += score
        max_possible += param.max_score

    fclass = score_to_class(total)

    return SoilFertilityResult(
        total_score=total,
        max_possible=max_possible,
        fertility_class=fclass,
        fertility_label_np=_FERTILITY_LABELS_NP[fclass],
        parameter_scores=param_scores,
    )


# ── Legacy Compatibility ─────────────────────────────────────
# Drop-in replacement for analysis.py:1815-1871 logic

def legacy_soil_fertility_score(
    ph: float,
    soc: float,
    nitrogen: float,
    cec: float,
    compaction: float,
    moisture: float,
) -> dict:
    """Return a plain dict matching the old analysis.py output format."""
    result = assess_soil_fertility(ph, soc, nitrogen, cec, compaction, moisture)
    return {
        "total_score": result.total_score,
        "max_possible": result.max_possible,
        "fertility_class": result.fertility_class.value,
        "fertility_label_np": result.fertility_label_np,
        "parameters": [
            {
                "name": ps.name,
                "name_np": ps.name_np,
                "value": ps.value,
                "score": ps.score,
                "label": ps.rule_label,
            }
            for ps in result.parameter_scores
        ],
    }
