"""
Chart generator for report generation
Creates chart images (PNG) from analysis data
"""
# constraint: Chart.js data format
# why: server-side chart rendering for HTML/PDF previews
import base64
from typing import Dict, Any, List, Optional
from io import BytesIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from app.utils.number_format import format_devanagari
from app.core.text_shaping import save_figure

# ── Devanagari font setup ──
_DEV_FONT = None
for _dev_name in ['Nirmala UI', 'Mangal', 'Noto Sans Devanagari', 'Arial Unicode MS']:
    try:
        _fp = fm.findfont(_dev_name, fallback_to_default=False)
        if _fp:
            fm.fontManager.addfont(_fp)
            _DEV_FONT = _fp
            break
    except Exception:  # noqa: BLE001,S112 -- findfont raises when the font is absent, which is the question being asked; the loop tries the next candidate
        continue
if _DEV_FONT:
    _font_name = fm.FontProperties(fname=_DEV_FONT).get_name()
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = [_font_name] + plt.rcParams.get('font.sans-serif', [])
else:
    import logging
    logging.getLogger(__name__).warning("No Devanagari font found - Nepali labels may not render")


def _dev_fontprop(size: int = 14):
    if _DEV_FONT:
        return fm.FontProperties(fname=_DEV_FONT, size=size)
    return fm.FontProperties(size=size)


def _apply_dev_font(ax, title_size=14, label_size=11, tick_size=10):
    fp_title = _dev_fontprop(title_size)
    fp_label = _dev_fontprop(label_size)
    fp_tick = _dev_fontprop(tick_size)
    if _DEV_FONT:
        ax.title.set_fontproperties(fp_title)
        ax.xaxis.label.set_fontproperties(fp_label)
        ax.yaxis.label.set_fontproperties(fp_label)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontproperties(fp_tick)


def _dev_pct(pct):
    """Autopct callable: format percentage with Devanagari digits."""
    return format_devanagari(pct, 1) + "%"


def _save_or_base64(fig, output_path: str = None) -> str:
    """Save figure to file or return base64 string (SVG for proper text shaping)"""
    fig.tight_layout()

    if output_path:
        save_figure(fig, output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return output_path

    buf = BytesIO()
    # manual shaping draws Devanagari as outlines, so the PNG reads correctly whatever fonts the viewer has. A PNG, not an SVG:
    # Word draws a bare SVG clipped with its legend labels missing (a chart of coloured boxes with no text).
    save_figure(fig, buf, format='png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def generate_species_pie(species_list: List[Dict], forest_name: str = "", top_n: int = 8, output_path: str = None) -> str:
    """Species composition pie chart"""
    if not species_list:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    # Sort by rank and take top N
    sorted_species = sorted(species_list, key=lambda x: x.get('availability_rank', 999))[:top_n]

    labels = [s.get('scientific_name', 'Unknown')[:20] for s in sorted_species]
    sizes = [1] * len(sorted_species)

    species_colors = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6', '#f1c40f', '#1abc9c', '#e74c3c', '#95a5a6']

    wedges, texts = ax.pie(
        sizes, labels=None, startangle=90,
        colors=species_colors[:len(labels)],
    )
    ax.legend(
        wedges, labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.2), ncol=min(2, len(labels)),
        fontsize=6, frameon=False, prop=_dev_fontprop(6),
    )

    title = f'{forest_name} - Species Composition (Top {top_n})' if forest_name else f'Species Composition (Top {top_n})'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.3)

    return _save_or_base64(fig, output_path)


def generate_forest_type_pie(forest_type_percentages: Dict, forest_name: str = "", output_path: str = None, language: str = "NP") -> str:
    """Forest type distribution pie chart"""
    if not forest_type_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    labels = list(forest_type_percentages.keys())
    sizes = list(forest_type_percentages.values())

    ft_colors = ['#1a5c2e', '#27ae60', '#82e0aa', '#d5f5e3', '#2ecc71', '#a9dfbf']
    wedges, texts = ax.pie(
        sizes, labels=None, startangle=90,
        colors=ft_colors[:len(labels)],
    )
    legend_labels = [f"{l} ({_dev_pct(s) if language == 'NP' else f'{s:.1f}%'})" for l, s in zip(labels, sizes)]
    ax.legend(
        wedges, legend_labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.18), ncol=min(2, len(labels)),
        fontsize=7, frameon=False, prop=_dev_fontprop(7),
    )

    title = f'{forest_name} - Forest Type Distribution' if forest_name else 'Forest Type Distribution'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.28)

    return _save_or_base64(fig, output_path)


def generate_slope_pie(slope_percentages: Dict, dominant: str = "", forest_name: str = "", output_path: str = None, language: str = "NP") -> str:
    """Slope class distribution pie chart"""
    if not slope_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    labels = list(slope_percentages.keys())
    sizes = list(slope_percentages.values())

    # Color gradient: green (flat) to red (steep) — lowercase keys match analysis.py
    color_map = {
        'gentle': '#84cc16', 'moderate': '#eab308',
        'steep': '#f97316', 'very_steep': '#ef4444',
        'flat': '#22c55e', 'Flat': '#22c55e',
    }
    colors = [color_map.get(l, '#95a5a6') for l in labels]

    wedges, texts = ax.pie(
        sizes, labels=None, startangle=90, colors=colors,
    )
    legend_labels = [f"{l} ({_dev_pct(s) if language == 'NP' else f'{s:.1f}%'})" for l, s in zip(labels, sizes)]
    ax.legend(
        wedges, legend_labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.18), ncol=min(2, len(labels)),
        fontsize=8, frameon=False, prop=_dev_fontprop(8),
    )

    dom_text = f' (Dominant: {dominant})' if dominant else ''
    title = f'{forest_name} - Slope Classification{dom_text}' if forest_name else f'Slope Classification{dom_text}'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.28)

    return _save_or_base64(fig, output_path)


def generate_canopy_pie(canopy_percentages: Dict, dominant: str = "", forest_name: str = "", output_path: str = None, language: str = "NP") -> str:
    """Canopy cover distribution pie chart"""
    if not canopy_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    labels = list(canopy_percentages.keys())
    sizes = list(canopy_percentages.values())

    # Keys match analysis.py: non_forest(1m), regeneration(2-5m), pole_trees(6-15m), tree(>15m)
    color_map = {
        'tree': '#059669', 'pole_trees': '#10b981', 'regeneration': '#84cc16', 'non_forest': '#94a3b8',
        'dense': '#059669', 'medium': '#10b981', 'sparse': '#84cc16', 'open': '#d5f5e3',
    }
    colors = [color_map.get(l, '#95a5a6') for l in labels]

    wedges, texts = ax.pie(
        sizes, labels=None, startangle=90, colors=colors,
    )
    legend_labels = [f"{l} ({_dev_pct(s) if language == 'NP' else f'{s:.1f}%'})" for l, s in zip(labels, sizes)]
    ax.legend(
        wedges, legend_labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.18), ncol=min(2, len(labels)),
        fontsize=8, frameon=False, prop=_dev_fontprop(8),
    )

    dom_text = f' (Dominant: {dominant})' if dominant else ''
    title = f'{forest_name} - Canopy Cover{dom_text}' if forest_name else f'Canopy Cover{dom_text}'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.28)

    return _save_or_base64(fig, output_path)


def generate_landcover_pie(landcover_percentages: Dict, dominant: str = "", forest_name: str = "", top_n: int = 6, output_path: str = None, language: str = "NP") -> str:
    """Land cover distribution pie chart"""
    if not landcover_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    # Sort and take top N
    sorted_lc = sorted(landcover_percentages.items(), key=lambda x: x[1], reverse=True)[:top_n]
    labels = [lc[0] for lc in sorted_lc]
    sizes = [lc[1] for lc in sorted_lc]

    landcover_color_map = {
        "Tree cover": "#006400", "tree_cover": "#006400",
        "Shrubland": "#FFBB22", "shrubland": "#FFBB22",
        "Grassland": "#FFFF4C", "grassland": "#FFFF4C",
        "Cropland": "#F096FF", "cropland": "#F096FF",
        "Built-up": "#FA0000", "built_up": "#FA0000", "built-up": "#FA0000",
        "Bare/sparse vegetation": "#B4B4B4", "bare": "#B4B4B4",
        "Permanent water bodies": "#0064C8", "water": "#0064C8",
        "Snow and ice": "#E0E0E0", "Snow": "#E0E0E0",
        "Herbaceous wetland": "#00C8C8",
        "Mangroves": "#006464",
    }
    lc_colors = [landcover_color_map.get(l, "#95a5a6") for l in labels]
    wedges, texts = ax.pie(
        sizes, labels=None, startangle=90, colors=lc_colors,
    )
    legend_labels = [f"{l} ({_dev_pct(s) if language == 'NP' else f'{s:.1f}%'})" for l, s in zip(labels, sizes)]
    ax.legend(
        wedges, legend_labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.18), ncol=min(3, len(labels)),
        fontsize=7, frameon=False, prop=_dev_fontprop(7),
    )

    dom_text = f' (Dominant: {dominant})' if dominant else ''
    title = f'{forest_name} - Land Cover{dom_text}' if forest_name else f'Land Cover{dom_text}'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.28)

    return _save_or_base64(fig, output_path)


def generate_ug_landcover_pie(land_cover_classes: List[Dict], forest_name: str = "", top_n: int = 6, output_path: str = None, language: str = "NP") -> str:
    """User group land cover distribution pie chart"""
    if not land_cover_classes:
        return ""

    sorted_lc = sorted(land_cover_classes, key=lambda x: x.get("percentage", 0), reverse=True)[:top_n]
    labels = [c.get("class_name", f"Class {c.get('class_code', '')}") for c in sorted_lc]
    sizes = [c.get("percentage", 0) for c in sorted_lc]
    dominant = labels[0] if labels else ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    landcover_color_map = {
        "Tree cover": "#006400", "tree_cover": "#006400",
        "Shrubland": "#FFBB22", "shrubland": "#FFBB22",
        "Grassland": "#FFFF4C", "grassland": "#FFFF4C",
        "Cropland": "#F096FF", "cropland": "#F096FF",
        "Built-up": "#FA0000", "built_up": "#FA0000", "built-up": "#FA0000",
        "Bare/sparse vegetation": "#B4B4B4", "bare": "#B4B4B4",
        "Permanent water bodies": "#0064C8", "water": "#0064C8",
        "Snow and ice": "#E0E0E0", "Snow": "#E0E0E0",
        "Herbaceous wetland": "#00C8C8",
        "Mangroves": "#006464",
    }
    lc_colors = [landcover_color_map.get(l, "#95a5a6") for l in labels]
    wedges, texts = ax.pie(sizes, labels=None, startangle=90, colors=lc_colors)

    legend_labels = [f"{l} ({_dev_pct(s) if language == 'NP' else f'{s:.1f}%'})" for l, s in zip(labels, sizes)]
    ax.legend(
        wedges, legend_labels, loc='lower center',
        bbox_to_anchor=(0.5, -0.18), ncol=min(3, len(labels)),
        fontsize=7, frameon=False, prop=_dev_fontprop(7),
    )

    title = f'{forest_name} - User Group Land Cover' if forest_name else 'User Group Land Cover'
    ax.set_title(title, fontsize=11, fontweight='bold', pad=12)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)
    fig.subplots_adjust(bottom=0.28)

    return _save_or_base64(fig, output_path)


def generate_aspect_rose(aspect_percentages: Dict, forest_name: str = "", output_path: str = None) -> str:
    """Aspect distribution rose diagram"""
    if not aspect_percentages:
        return ""

    fig = plt.figure(figsize=(6, 5), dpi=150)
    ax = fig.add_subplot(111, projection='polar')

    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    angles = np.linspace(0, 2 * np.pi, 8, endpoint=False)

    sizes = [aspect_percentages.get(d, 0) for d in directions]

    width = 2 * np.pi / 8

    bars = ax.bar(angles, sizes, width=width, bottom=0.0,
                  color=plt.cm.RdYlGn(np.linspace(0.3, 0.9, 8)), edgecolor='white')

    ax.set_xticks(angles)
    ax.set_xticklabels(directions, fontsize=10)
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=10)
    ax.set_title(f'{forest_name} - Aspect Distribution' if forest_name else 'Aspect Distribution',
                 fontsize=11, fontweight='bold', pad=20)
    ax.title.set_fontproperties(_dev_fontprop(11))

    return _save_or_base64(fig, output_path)


def generate_block_area_bar(blocks: List[Dict], forest_name: str = "", output_path: str = None, language: str = "NP") -> str:
    """Block-wise area bar chart"""
    if not blocks:
        return ""

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)

    names = [b.get('name', f'Block {i+1}')[:15] for i, b in enumerate(blocks)]
    areas = [b.get('area_hectares', 0) for b in blocks]
    colors = ['#2ecc71', '#3498db', '#e67e22', '#e74c3c', '#9b59b6', '#f1c40f', '#1abc9c'][:len(blocks)]

    bars = ax.bar(names, areas, color=colors, edgecolor='white', linewidth=1.5)

    for bar, area in zip(bars, areas):
        label = f'{format_devanagari(area, 1)} ha' if language == "NP" else f'{area:.1f} ha'
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.1,
                label, ha='center', va='bottom', fontsize=9, fontweight='bold',
                fontproperties=_dev_fontprop(9))

    ax.set_ylabel('Area (hectares)', fontsize=11)
    title = f'{forest_name} - Block-wise Area' if forest_name else 'Block-wise Area'
    ax.set_title(title, fontsize=11, fontweight='bold')
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=9)

    ax.yaxis.grid(True, alpha=0.3)
    ax.set_axisbelow(True)

    return _save_or_base64(fig, output_path)


def generate_dbh_histogram(dbh_summary: Dict, forest_name: str = "", output_path: str = None) -> str:
    """DBH class distribution histogram"""
    if not dbh_summary:
        return ""

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)

    classes = list(dbh_summary.keys())
    counts = list(dbh_summary.values())

    bars = ax.bar(range(len(classes)), counts, color='#3498db', edgecolor='white', linewidth=1.5)

    ax.set_xticks(range(len(classes)))
    ax.set_xticklabels(classes, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('Number of Trees', fontsize=11)
    ax.set_xlabel('DBH Class (cm)', fontsize=11)

    title = f'{forest_name} - DBH Class Distribution' if forest_name else 'DBH Class Distribution'
    ax.set_title(title, fontsize=11, fontweight='bold')
    _apply_dev_font(ax, title_size=11, label_size=11, tick_size=8)

    ax.yaxis.grid(True, alpha=0.3)
    ax.set_axisbelow(True)

    return _save_or_base64(fig, output_path)


def generate_biomass_bar(agb_total: float, carbon_stock: float, forest_name: str = "", output_path: str = None, language: str = "NP") -> str:
    """Biomass and carbon stock bar chart"""
    if agb_total == 0 and carbon_stock == 0:
        return ""

    fig, ax = plt.subplots(figsize=(5, 4), dpi=150)

    labels = ['Above Ground\nBiomass (tons)', 'Carbon Stock\n(tons)']
    values = [agb_total, carbon_stock]
    colors = ['#27ae60', '#2980b9']

    bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=1.5)

    for bar, val in zip(bars, values):
        label = format_devanagari(val, 1) if language == "NP" else f'{val:.1f}'
        ax.text(bar.get_x() + bar.get_width()/2., val + 0.5,
                label, ha='center', va='bottom', fontsize=10, fontweight='bold',
                fontproperties=_dev_fontprop(10))

    title = f'{forest_name} - Biomass & Carbon Stock' if forest_name else 'Biomass & Carbon Stock'
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.set_ylabel('Amount (tons)', fontsize=10)
    _apply_dev_font(ax, title_size=11, label_size=10, tick_size=9)

    ax.yaxis.grid(True, alpha=0.3)
    ax.set_axisbelow(True)

    return _save_or_base64(fig, output_path)
