# Sampling Design Guide
**नमूना डिजाइन गर्ने प्रक्रिया**

## Overview
Create statistically valid sample plot designs for field inventory. Supports Guideline-2061 (Nepal standard) and custom designs.

---

## Step 1: Choose Sampling Method

### Guideline-2061 (Recommended - Default)
- **Method**: Systematic grid sampling
- **Grid**: 200m × 250m (adjustable)
- **Plot types**: Pole (100 m²) + Tree (500 m²)
- **Intensity**: 0.5% or 1.0% of productive area
- **Stratification**: By block + land cover (auto)
- **Minimum plots**: 15 per block (≥1 ha)

### Manual Method (Advanced)
- **Sampling types**: Systematic, Random, Stratified
- **Custom grid spacing**
- **Custom plot sizes**
- **Custom intensity**
- **Protected zone handling**: Include/exclude/sample separately

---

## Step 2: Configure Parameters

### Guideline-2061 Settings
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| Productive intensity | 0.5% | 0.1-2.0% | Per CFMG guidelines |
| Pole plot size | 100 m² | Fixed | 11.28m radius |
| Tree plot size | 500 m² | Fixed | 12.62m radius |
| Boundary buffer | 50 m | 0-200 m | Excludes edge plots |
| Min plots/block | 15 | 5-30 | For blocks ≥ 1 ha |

### Accessible Forest Filters (Phase 2)
| Filter | Default | Purpose |
|--------|---------|---------|
| Tree cover only | **ON** | Uses ESA WorldCover 10m |
| Slope filter | OFF | Exclude >45° (configurable) |
| Max slope | 45° | Safety/accessibility |

---

## Step 3: Preview Accessible Forest

### Before Creating Design
Click **"Preview Accessible & Protected Forest Areas"**:

1. **Map shows:**
   - Green = Accessible forest (tree cover, slope OK)
   - Orange = Protected zones (from boundary)
   - Red = Excluded (steep, non-forest, buffer)
   - Gray = Outside boundary

2. **Statistics panel:**
   - Total forest area (ha)
   - Accessible area (ha)
   - Protected zone count/area
   - Estimated plot count

3. **Adjust filters if needed:**
   - Toggle slope filter
   - Change max slope threshold
   - Enable/disable tree cover filter

---

## Step 4: Generate Sampling Design

### Click "Create Sampling Design"
System will:
1. Generate systematic grid over accessible area
2. Assign plot centers to grid intersections
4. Classify each plot as **Pole** or **Tree** based on local forest type
5. Calculate **sample intensity** achieved
6. Check **minimum 15 plots per block**

### Output: Sampling Design Record
- Unique Design ID
- Total plots (pole + tree)
- Plots per block
- GPX file for field navigation
- PDF map with plot locations

---

## Step 5: Review & Export

### Review Checklist
- [ ] All blocks have ≥ 15 plots (or documented exception)
- [ ] Protected zones properly excluded/sampled
- [ ] Plot spacing matches guideline (200×250m)
- [ ] Pole/Tree plot assignment correct
- [ ] GPX exports open in GPS device

### Export Options
| Format | Purpose |
|--------|---------|
| **GPX** | Load into GPS/phone for field navigation |
| **KML** | View in Google Earth/QGIS |
| **CSV** | Plot coordinates + metadata |
| **PDF Map** | Print for field crew |

---

## Step 6: Field Data Collection

### Using GPX on GPS Device
1. Transfer `.gpx` to GPS (Garmin, phone app)
2. Navigate to each waypoint (plot center)
3. Establish plot (circular, measure radius)
4. Record all trees per protocol

### Recommended Field Apps
- **QField** (QGIS mobile) — loads GPX + basemap
- **Gaia GPS** / **GPS Essentials** — simple navigation
- **OruxMaps** — offline maps + GPX

---

## Protected Zone Handling
If protected zones detected (from boundary sub-areas):

| Option | Behavior |
|--------|----------|
| **Exclude** (default) | No plots in protected zones |
| **Sample at 0.1%** | Low-intensity separate sampling |
| **Separate design** | Creates separate design record |

---

## Common Issues

| Issue | Solution |
|-------|----------|
| "Too few plots in Block X" | Block < 1 ha? Merge with adjacent or document exception |
| "Protected zone not excluded" | Check sub-area category = "protected" |
| "Plots too close to boundary" | Increase boundary buffer to 100m |
| "Grid spacing wrong" | Guideline-2061 fixed at 200×250m; use Manual for custom |

---

## After Sampling: Link to Inventory
1. Complete field measurements
2. Upload inventory CSV (see Inventory Upload Guide)
3. System auto-links plots to sampling design
4. Per-hectare values calculated using **actual plot count per block**

---

## Video Tutorial
📺 [Watch: Sampling Design & Field Prep (5 min)](https://example.com/videos/sampling-design)

*Guide version 1.0 | Last updated: 2026-07-20*