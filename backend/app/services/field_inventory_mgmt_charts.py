"""
Management Plan Chart Generator
Creates 9 Matplotlib chart images (PNG) for DOCX embedding.
Village-friendly: large fonts, consistent colors, Nepali labels.
"""
# business: CFMG — management plan charts: species composition, block comparison, carbon stock
# constraint: Chart.js data format for frontend rendering
# why: separate from report chart_generator for management plan use

import io
import logging
from typing import Dict, Any, List, Optional
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

logger = logging.getLogger(__name__)

# ── Devanagari font — centralised in app.core.fonts (§3.8 / P0) ──
from app.core.fonts import configure_matplotlib_devanagari, dev_font_prop, devanagari_font_path
from app.core.text_shaping import save_figure

configure_matplotlib_devanagari()
_DEVANAGARI_FONT = devanagari_font_path()


def _dev_fontprop(size: int = 14):
    return dev_font_prop(size)


def _apply_dev_font(ax, title_size=14, label_size=11, tick_size=10):
    if _DEVANAGARI_FONT:
        ax.title.set_fontproperties(_dev_fontprop(title_size))
        ax.xaxis.label.set_fontproperties(_dev_fontprop(label_size))
        ax.yaxis.label.set_fontproperties(_dev_fontprop(label_size))
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontproperties(_dev_fontprop(tick_size))


COLORS = {
    "forest": "#2e7d32", "forest_light": "#4caf50", "forest_pale": "#a5d6a7",
    "water": "#1565c0", "water_light": "#42a5f5",
    "degraded": "#795548", "degraded_light": "#a1887f",
    "caution": "#f9a825", "caution_light": "#fff176",
    "danger": "#c62828", "danger_light": "#ef5350",
    "neutral": "#78909c", "neutral_light": "#b0bec5",
}
CONDITION_COLORS = {"Good": COLORS["forest"], "Moderate": COLORS["caution"], "Weak": COLORS["danger"]}
GROWTH_COLORS = {"Fast": COLORS["forest"], "Moderate": COLORS["caution"], "Slow": COLORS["degraded"]}
DPI = 100


def _save_buffer(fig, dpi=DPI) -> io.BytesIO:
    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    # save_figure applies Devanagari shaping (mplcairo, or uharfbuzz→outlines)
    save_figure(fig, buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf


def chart_species_composition(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Pie chart: species volume share (top 10 + Others)."""
    species = data.get("forest_wide", [])
    if not species:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    labels = [s.get("local_name", s.get("scientific_name", "")) for s in species]
    sizes = [s.get("volume_pct", 0) for s in species]
    colors = plt.cm.Set2(np.linspace(0, 1, len(labels)))

    fig, ax = plt.subplots(figsize=(7, 5))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct='%1.0f%%', startangle=90,
        colors=colors, textprops={'fontsize': 12, 'fontweight': 'bold'},
        pctdistance=0.75, wedgeprops={'edgecolor': 'white', 'linewidth': 1},
    )
    for t in autotexts:
        t.set_fontproperties(_dev_fontprop(12))
    ax.legend(wedges, labels, title="Species", loc="center left",
              bbox_to_anchor=(1, 0, 0.5, 1), fontsize=10, prop=_dev_fontprop(10))
    title = f"{forest_name}\nप्रजाती संरचना (Species Composition)" if forest_name else "प्रजाती संरचना"
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=10)
    return _save_buffer(fig)


def chart_block_comparison(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Horizontal bar chart: blocks sorted by growing stock."""
    ranked = data.get("ranked", [])
    if not ranked:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    names = [b.get("name", "") for b in ranked]
    gs = [b.get("growing_stock_m3ha", 0) for b in ranked]
    aah_t = [b.get("aah_timber_m3yr", 0) for b in ranked]
    colors = [CONDITION_COLORS.get(b.get("condition", "Moderate"), COLORS["neutral"]) for b in ranked]

    fig, ax = plt.subplots(figsize=(8, max(4, len(names) * 0.5)))
    y_pos = range(len(names))
    bars = ax.barh(y_pos, gs, height=0.6, color=colors, edgecolor='white', linewidth=0.5)
    for i, (bar, aah) in enumerate(zip(bars, aah_t)):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height() / 2,
                f"AAH: {aah:.1f} m³/yr", va='center', fontsize=9, color='#333',
                fontproperties=_dev_fontprop(9))

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=11)
    ax.set_xlabel("Growing Stock (m³/ha)", fontsize=11)
    title = f"{forest_name}\nब्लक तुलना (Block Comparison)" if forest_name else "ब्लक तुलना"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.invert_yaxis()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)
    legend_patches = [mpatches.Patch(color=c, label=l) for l, c in CONDITION_COLORS.items()]
    ax.legend(handles=legend_patches, title="Condition", fontsize=9, loc='lower right', prop=_dev_fontprop(9))
    return _save_buffer(fig)


def chart_annual_harvest(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Grouped bar: AAH Timber + AAH Fuelwood per block."""
    blocks = data.get("blocks", [])
    if not blocks:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    names = [b.get("name", "") for b in blocks]
    timber = [b.get("aah_timber_m3yr", 0) for b in blocks]
    fuelwood = [b.get("aah_fuelwood_m3yr", 0) for b in blocks]

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(names))
    w = 0.35
    bars1 = ax.bar(x - w / 2, timber, w, label='AAH Timber', color=COLORS["forest"], edgecolor='white')
    bars2 = ax.bar(x + w / 2, fuelwood, w, label='AAH Fuelwood', color=COLORS["caution"], edgecolor='white')

    for bar in bars1:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h, f'{h:.1f}', ha='center', va='bottom', fontsize=8,
                    fontproperties=_dev_fontprop(8))
    for bar in bars2:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h, f'{h:.1f}', ha='center', va='bottom', fontsize=8,
                    fontproperties=_dev_fontprop(8))

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=11)
    ax.set_ylabel("m³/yr", fontsize=11)
    title = f"{forest_name}\nवार्षिक फसल योजना (Annual Harvest Plan)" if forest_name else "वार्षिक फसल योजना"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(fontsize=10, prop=_dev_fontprop(10))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)
    return _save_buffer(fig)


def chart_forest_condition(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Pie chart: condition area + bar chart: regeneration."""
    by_cond = data.get("by_condition", [])
    regen = data.get("regeneration", [])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    # Pie: condition
    if by_cond:
        labels = [c.get("condition", "") for c in by_cond]
        sizes = [c.get("area_ha", 0) for c in by_cond]
        colors = [CONDITION_COLORS.get(l, COLORS["neutral"]) for l in labels]
        wedges, texts, autotexts = ax1.pie(
            sizes, labels=None, autopct='%1.0f%%', startangle=90,
            colors=colors, textprops={'fontsize': 11, 'fontweight': 'bold'},
            wedgeprops={'edgecolor': 'white', 'linewidth': 1},
        )
        for t in autotexts:
            t.set_fontproperties(_dev_fontprop(11))
        ax1.legend(wedges, [f"{l} ({s:.0f} ha)" for l, s in zip(labels, sizes)],
                   title="Forest Condition", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9,
                   prop=_dev_fontprop(9))
    ax1.set_title("वन स्थिति (Forest Condition)", fontsize=12, fontweight='bold')
    _apply_dev_font(ax1, title_size=12, label_size=10, tick_size=9)

    # Bar: regeneration
    if regen:
        r_names = [r.get("block", "") for r in regen]
        r_seedling = [r.get("seedling_nha", 0) for r in regen]
        r_sapling = [r.get("sapling_nha", 0) for r in regen]
        x = np.arange(len(r_names))
        w = 0.35
        ax2.bar(x - w / 2, r_seedling, w, label='Seedling (0-4cm)', color=COLORS["forest_light"])
        ax2.bar(x + w / 2, r_sapling, w, label='Sapling (4-10cm)', color=COLORS["forest_pale"])
        ax2.set_xticks(x)
        ax2.set_xticklabels(r_names, fontsize=10)
        ax2.set_ylabel("N/ha", fontsize=10)
        ax2.legend(fontsize=8, prop=_dev_fontprop(8))
    ax2.set_title("पुनरुत्पादन (Regeneration)", fontsize=12, fontweight='bold')
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    _apply_dev_font(ax2, title_size=12, label_size=10, tick_size=10)

    fig.suptitle(forest_name, fontsize=14, fontweight='bold') if forest_name else None
    fig.tight_layout()
    return _save_buffer(fig)


def chart_dbh_class_volume(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Stacked bar: volume per DBH class, one bar per block."""
    blocks = data.get("blocks", [])
    if not blocks:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    dbh_labels = ["10-20", "20-30", "30-40", "40-50", "50-60", "60+"]
    dbh_colors = ["#a5d6a7", "#66bb6a", "#43a047", "#2e7d32", "#1b5e20", "#0d3b0e"]

    fig, ax = plt.subplots(figsize=(max(8, len(blocks) * 1.5), 5))
    x = np.arange(len(blocks))
    bottoms = np.zeros(len(blocks))

    for di, (dl, dc) in enumerate(zip(dbh_labels, dbh_colors)):
        values = []
        for b in blocks:
            cls_list = b.get("classes", [])
            match = [c for c in cls_list if c.get("dbh_class", "").startswith(dl)]
            values.append(match[0].get("total_m3ha", 0) if match else 0)
        ax.bar(x, values, bottom=bottoms, label=dl, color=dc, edgecolor='white', linewidth=0.5)
        bottoms += np.array(values)

    ax.set_xticks(x)
    ax.set_xticklabels([b.get("block", "") for b in blocks], fontsize=11)
    ax.set_ylabel("Volume (m³/ha)", fontsize=11)
    title = f"{forest_name}\nDBH वर्ग आयतन वितरण (DBH Class Volume)" if forest_name else "DBH वर्ग आयतन वितरण"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(title="DBH Class (cm)", fontsize=9, loc='upper right', prop=_dev_fontprop(9))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)
    return _save_buffer(fig)


def chart_carbon_stock(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Grouped bar: AGB vs BGB per block."""
    blocks = data.get("blocks", [])
    if not blocks:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    names = [b.get("block", "") for b in blocks]
    agb = [b.get("agb_tha", 0) for b in blocks]
    bgb = [b.get("bgb_tha", 0) for b in blocks]

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(names))
    w = 0.35
    bars1 = ax.bar(x - w / 2, agb, w, label='AGB (Above Ground)', color=COLORS["forest"], edgecolor='white')
    bars2 = ax.bar(x + w / 2, bgb, w, label='BGB (Below Ground)', color=COLORS["degraded"], edgecolor='white')

    for bars in [bars1, bars2]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h, f'{h:.0f}', ha='center', va='bottom', fontsize=8,
                        fontproperties=_dev_fontprop(8))

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=11)
    ax.set_ylabel("t/ha", fontsize=11)
    title = f"{forest_name}\nकार्बन भण्डार (Carbon Stock)" if forest_name else "कार्बन भण्डार"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(fontsize=10, prop=_dev_fontprop(10))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)
    return _save_buffer(fig)


def chart_growth_rate(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Pie chart: volume share by growth rate."""
    classes = data.get("classes", [])
    if not classes:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    labels = [c.get("rate", "") for c in classes]
    sizes = [c.get("volume_pct", 0) for c in classes]
    colors = [GROWTH_COLORS.get(l, COLORS["neutral"]) for l in labels]

    fig, ax = plt.subplots(figsize=(6, 5))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct='%1.0f%%', startangle=90,
        colors=colors, textprops={'fontsize': 13, 'fontweight': 'bold'},
        wedgeprops={'edgecolor': 'white', 'linewidth': 1},
    )
    for t in autotexts:
        t.set_fontproperties(_dev_fontprop(13))
    detail_labels = []
    for c in classes:
        detail_labels.append(f"{c.get('rate', '')} ({c.get('species_count', 0)} species)")
    ax.legend(wedges, detail_labels, title="Growth Rate", loc="center left",
              bbox_to_anchor=(1, 0, 0.5, 1), fontsize=10, prop=_dev_fontprop(10))
    title = f"{forest_name}\nवृद्धि दर वर्गीकरण (Growth Rate)" if forest_name else "वृद्धि दर वर्गीकरण"
    ax.set_title(title, fontsize=14, fontweight='bold')
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=10)
    return _save_buffer(fig)


def chart_stand_structure(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Line chart: actual vs ideal reverse-J distribution."""
    blocks = data.get("blocks", [])
    if not blocks:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    dbh_labels_display = ["10-20", "20-30", "30-40", "40-50", "50-60", "60+"]

    for b in blocks:
        blk = b.get("block", "")
        actuals = []
        ideals = []
        for cls in b.get("classes", []):
            actuals.append(cls.get("actual_nha", 0))
            ideals.append(cls.get("ideal_nha", 0))
        x = np.arange(len(dbh_labels_display[:len(actuals)]))
        ax.plot(x, actuals, '-o', label=f"{blk} (Actual)", linewidth=2, markersize=6)
        ax.plot(x, ideals, '--s', label=f"{blk} (Ideal)", linewidth=1.5, markersize=4, alpha=0.7)

    ax.set_xticks(np.arange(len(dbh_labels_display)))
    ax.set_xticklabels(dbh_labels_display, fontsize=11)
    ax.set_xlabel("DBH Class (cm)", fontsize=11)
    ax.set_ylabel("N/ha", fontsize=11)
    title = f"{forest_name}\nरुख संरचना प्रोफाइल (Stand Structure)" if forest_name else "रुख संरचना प्रोफाइल"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(fontsize=9, loc='upper right', prop=_dev_fontprop(9))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.3)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)

    assessment = data.get("assessment", "")
    if assessment:
        ax.text(0.02, 0.02, f"Assessment: {assessment}", transform=ax.transAxes,
                fontsize=10, style='italic', color='#555',
                fontproperties=_dev_fontprop(10),
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    return _save_buffer(fig)


def chart_productivity(data: Dict, forest_name: str = "") -> io.BytesIO:
    """Horizontal bar: blocks grouped by productivity class."""
    classes = data.get("classes", [])
    if not classes:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No data", ha='center', va='center', fontproperties=_dev_fontprop(12))
        return _save_buffer(fig)

    prod_colors = {"High": COLORS["forest"], "Medium": COLORS["caution"], "Low": COLORS["danger"]}

    fig, ax = plt.subplots(figsize=(8, max(3.5, len(classes) * 0.6)))
    names = [c.get("class", "") for c in classes]
    areas = [c.get("area_ha", 0) for c in classes]
    colors_bar = [prod_colors.get(n, COLORS["neutral"]) for n in names]

    bars = ax.barh(names, areas, height=0.5, color=colors_bar, edgecolor='white')
    for bar, c in zip(bars, classes):
        label = f'{c.get("block_count", 0)} blocks, {c.get("volume_m3", 0):.0f} m³'
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, label,
                va='center', fontsize=10, color='#333', fontproperties=_dev_fontprop(10))

    ax.set_xlabel("Area (ha)", fontsize=11)
    title = f"{forest_name}\nउत्पादकता वर्गीकरण (Productivity)" if forest_name else "उत्पादकता वर्गीकरण"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    _apply_dev_font(ax, title_size=14, label_size=11, tick_size=11)
    return _save_buffer(fig)
