"""
Snapped coordinate grid for village-friendly maps.

Computes grid lines that fall on "round" coordinate values by slightly
shifting the axis origin — producing clean, memorable labels without
rounding individual data points.

Usage:
    lines, labels, snapped_min, snapped_max = compute_snapped_grid(min_val, max_val)
    apply_snapped_ticks(ax, lon_lines, lat_lines, lon_labels, lat_labels)
"""
import math
import logging

logger = logging.getLogger(__name__)


_NICE_MANTS = [1, 2, 5, 10]


def _candidate_steps(raw_step: float) -> list[float]:
    """Generate candidate 'nice' step sizes around a raw step."""
    mag = 10 ** math.floor(math.log10(raw_step))
    steps = set()
    for mant in _NICE_MANTS:
        for m in (mag / 10, mag, mag * 10):
            step = mant * m
            if step > 0:
                steps.add(round(step, 15))
    return sorted(steps)


def _grid_count(step: float, min_val: float, max_val: float) -> int:
    """Number of grid lines for a given step and data range."""
    start = math.floor(min_val / step) * step
    end = math.ceil(max_val / step) * step
    return int(round((end - start) / step)) + 1


def compute_snapped_grid(
    min_val: float,
    max_val: float,
    target_lines: int = 5,
    min_lines: int = 3,
    max_lines: int = 7,
) -> tuple[list[float], list[str], float, float]:
    """
    Compute grid lines that fall on clean coordinate values.

    Tries multiple "nice" step sizes (1, 2, 5 × 10ⁿ) and selects the
    one that yields between *min_lines* and *max_lines* grid lines
    while staying closest to *target_lines*.  Axis bounds are shifted
    outward to align with round multiples of the chosen step.

    Returns:
        lines:        Grid line coordinate values
        labels:       Formatted label strings (smart precision — no trailing zeros)
        snapped_min:  Adjusted axis minimum
        snapped_max:  Adjusted axis maximum
    """
    extent = max_val - min_val
    if extent <= 0 or math.isclose(extent, 0):
        v = (min_val + max_val) / 2
        return [v], [f"{v:.5f}"], v, v

    raw_step = extent / target_lines
    candidates = _candidate_steps(raw_step)

    best_step = candidates[0]
    best_diff = float("inf")

    for step in candidates:
        count = _grid_count(step, min_val, max_val)
        if min_lines <= count <= max_lines:
            best_step = step
            break
        diff = abs(count - target_lines)
        if diff < best_diff:
            best_diff = diff
            best_step = step

    start = math.floor(min_val / best_step) * best_step
    end = math.ceil(max_val / best_step) * best_step

    lines = []
    val = start
    epsilon = best_step * 1e-10
    while val <= end + epsilon:
        lines.append(val)
        val += best_step

    decimals = max(0, -int(math.floor(math.log10(best_step))))
    labels = [f"{v:.{decimals}f}" for v in lines]

    return lines, labels, start, end


def apply_snapped_ticks(
    ax,
    lon_lines: list[float],
    lat_lines: list[float],
    lon_labels: list[str],
    lat_labels: list[str],
    grid_kwargs: dict | None = None,
):
    """Set axis ticks and grid from pre-computed snapped values."""
    ax.set_xticks(lon_lines)
    ax.set_yticks(lat_lines)
    ax.set_xticklabels(lon_labels)
    ax.set_yticklabels(lat_labels)

    # X-axis labels on top to avoid overlap with legend/metadata at bottom
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    kwargs = {"alpha": 0.3, "linestyle": "--", "linewidth": 0.5, "zorder": 8}
    if grid_kwargs:
        kwargs.update(grid_kwargs)
    ax.grid(True, **kwargs)
    ax.tick_params(axis="both", labelsize=8)
