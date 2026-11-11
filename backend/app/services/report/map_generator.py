"""
Map generator for report generation
Creates static map images (PNG) from GeoJSON data
"""
import os
import tempfile
import base64
from typing import Dict, Any, Optional, List
from io import BytesIO

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

# ── Devanagari font — centralised in app.core.fonts (§3.8 / P0) ──
from app.core.fonts import configure_matplotlib_devanagari, dev_font_prop, devanagari_font_path

configure_matplotlib_devanagari()
_DEV_FONT = devanagari_font_path()


def _dev_fontprop(size: int = 14):
    return dev_font_prop(size)


def _apply_dev_font(ax, title_size=14, label_size=11, tick_size=10):
    if not _DEV_FONT:
        return
    fp_title = _dev_fontprop(title_size)
    fp_label = _dev_fontprop(label_size)
    fp_tick = _dev_fontprop(tick_size)
    ax.title.set_fontproperties(fp_title)
    ax.xaxis.label.set_fontproperties(fp_label)
    ax.yaxis.label.set_fontproperties(fp_label)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(fp_tick)


def _get_color(index: int) -> str:
    """Get color for block/map element"""
    colors = ['#2ecc71', '#3498db', '#e67e22', '#e74c3c', '#9b59b6', '#f1c40f', '#1abc9c']
    return colors[index % len(colors)]


def generate_boundary_map(
    boundary_geojson: Dict,
    forest_name: str = "",
    blocks: List[Dict] = None,
    output_path: str = None,
    figsize: tuple = (8, 6),
) -> str:
    """Generate boundary map PNG"""
    if not boundary_geojson:
        return ""

    fig, ax = plt.subplots(figsize=figsize, dpi=150)

    coords = _extract_coords(boundary_geojson)

    if blocks:
        for i, block in enumerate(blocks):
            block_coords = _extract_coords(block.get('geometry', {}))
            if block_coords:
                x, y = _split_coords(block_coords)
                if x and y:
                    ax.fill(x, y, color=_get_color(i), alpha=0.4, edgecolor=_get_color(i), linewidth=2)
                    centroid = block.get('centroid', {})
                    if centroid:
                        ax.annotate(
                            block.get('name', f'Block {i+1}'),
                            xy=(centroid.get('lon', 0), centroid.get('lat', 0)),
                            fontsize=8, fontweight='bold', ha='center',
                            fontproperties=_dev_fontprop(8),
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
                        )
    elif coords:
        x, y = _split_coords(coords)
        if x and y:
            ax.fill(x, y, color='#2ecc71', alpha=0.4, edgecolor='#27ae60', linewidth=2)

    ax.set_xlabel('Longitude', fontsize=10, fontproperties=_dev_fontprop(10))
    ax.set_ylabel('Latitude', fontsize=10, fontproperties=_dev_fontprop(10))

    if forest_name:
        ax.set_title(f'{forest_name} - Forest Boundary', fontsize=14, fontweight='bold', fontproperties=_dev_fontprop(14))

    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return output_path

    # Return as base64
    buf = BytesIO()
    plt.savefig(buf, format='svg', dpi=150, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return f"data:image/svg+xml;base64,{base64.b64encode(buf.read()).decode()}"


def generate_slope_map(slope_percentages: Dict, dominant: str, forest_name: str = "", output_path: str = None) -> str:
    """Generate slope classification pie chart"""
    if not slope_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    labels = list(slope_percentages.keys())
    sizes = list(slope_percentages.values())
    colors = ['#27ae60', '#f1c40f', '#e67e22', '#e74c3c'][:len(labels)]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct='%1.1f%%', colors=colors,
        startangle=90, textprops={'fontsize': 10}
    )

    title = f'{forest_name} - Slope Classification\n(Dominant: {dominant})' if forest_name else f'Slope Classification (Dominant: {dominant})'
    ax.set_title(title, fontsize=12, fontweight='bold')
    _apply_dev_font(ax, title_size=12, label_size=10, tick_size=9)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return output_path

    buf = BytesIO()
    plt.savefig(buf, format='svg', dpi=150, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return f"data:image/svg+xml;base64,{base64.b64encode(buf.read()).decode()}"


def generate_canopy_map(canopy_percentages: Dict, dominant: str, forest_name: str = "", output_path: str = None) -> str:
    """Generate canopy cover pie chart"""
    if not canopy_percentages:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)

    labels = list(canopy_percentages.keys())
    sizes = list(canopy_percentages.values())
    colors = ['#1a5c2e', '#27ae60', '#82e0aa', '#d5f5e3'][:len(labels)]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct='%1.1f%%', colors=colors,
        startangle=90, textprops={'fontsize': 10}
    )

    title = f'{forest_name} - Canopy Cover\n(Dominant: {dominant})' if forest_name else f'Canopy Cover (Dominant: {dominant})'
    ax.set_title(title, fontsize=12, fontweight='bold')
    _apply_dev_font(ax, title_size=12, label_size=10, tick_size=9)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return output_path

    buf = BytesIO()
    plt.savefig(buf, format='svg', dpi=150, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return f"data:image/svg+xml;base64,{base64.b64encode(buf.read()).decode()}"


def generate_species_pie_chart(species_list: List[Dict], forest_name: str = "", top_n: int = 8, output_path: str = None) -> str:
    """Generate species composition pie chart"""
    if not species_list:
        return ""

    sorted_species = sorted(species_list, key=lambda x: x.get('availability_rank', 999))[:top_n]

    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)

    labels = [s.get('scientific_name', 'Unknown')[:25] for s in sorted_species]
    sizes = [1] * len(sorted_species)  # Equal weight for composition

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct='', startangle=90,
        textprops={'fontsize': 8}, colors=plt.cm.Set3(np.linspace(0, 1, len(labels)))
    )

    title = f'{forest_name} - Species Composition (Top {top_n})' if forest_name else f'Species Composition (Top {top_n})'
    ax.set_title(title, fontsize=12, fontweight='bold')
    _apply_dev_font(ax, title_size=12, label_size=10, tick_size=9)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return output_path

    buf = BytesIO()
    plt.savefig(buf, format='svg', dpi=150, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return f"data:image/svg+xml;base64,{base64.b64encode(buf.read()).decode()}"


def generate_block_area_bar(blocks: List[Dict], forest_name: str = "", output_path: str = None) -> str:
    """Generate block-wise area bar chart"""
    if not blocks:
        return ""

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)

    names = [b.get('name', f'Block {i+1}') for i, b in enumerate(blocks)]
    areas = [b.get('area_hectares', 0) for b in blocks]
    colors = [_get_color(i) for i in range(len(blocks))]

    bars = ax.bar(names, areas, color=colors, edgecolor='white', linewidth=1.5)

    for bar, area in zip(bars, areas):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.1,
                f'{area:.1f} ha', ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax.set_ylabel('Area (hectares)', fontsize=11)
    title = f'{forest_name} - Block-wise Area Distribution' if forest_name else 'Block-wise Area Distribution'
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_xlabel('Blocks', fontsize=11)
    _apply_dev_font(ax, title_size=12, label_size=11, tick_size=10)

    ax.set_axisbelow(True)
    ax.yaxis.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return output_path

    buf = BytesIO()
    plt.savefig(buf, format='svg', dpi=150, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return f"data:image/svg+xml;base64,{base64.b64encode(buf.read()).decode()}"


def _extract_coords(geojson: Dict) -> List:
    """Extract coordinates from GeoJSON geometry"""
    if not geojson:
        return []

    geom_type = geojson.get('type', '')
    coords = geojson.get('coordinates', [])

    if geom_type == 'Polygon' and coords:
        return coords[0]  # First ring
    elif geom_type == 'MultiPolygon' and coords:
        return coords[0][0] if coords[0] else []
    return []


def _split_coords(coords: List) -> tuple:
    """Split [[lon, lat], ...] into (x_list, y_list)"""
    if not coords:
        return ([], [])
    try:
        x = [c[0] for c in coords]
        y = [c[1] for c in coords]
        return (x, y)
    except (IndexError, TypeError):
        return ([], [])
