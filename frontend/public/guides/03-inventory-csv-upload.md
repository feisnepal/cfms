# Inventory CSV Upload Guide
**इनभेन्टरी CSV अपलोड गर्ने प्रक्रिया**

## Overview
Upload tree measurement data (DBH, height, species) for volume calculation and growing stock estimation. The system supports flexible column mapping.

---

## Step 1: Prepare Your CSV File

### Required Columns (minimum)
| Column | Description | Example |
|--------|-------------|---------|
| `plot_id` | Sample plot identifier | `P001`, `Block1_Plot_1` |
| `tree_id` | Tree number within plot | `1`, `2`, `3` |
| `species` | Species code or local name | `SHOR`, `Sal`, `Saal` |
| `dbh_cm` | Diameter at breast height (cm) | `35.2` |
| `height_m` | Total tree height (meters) | `18.5` |

### Optional but Recommended Columns
| Column | Description | Example |
|--------|-------------|---------|
| `block_name` | Block name for assignment | `Chautara Block` |
| `sub_area` | Sub-area category | `protected`, `plantation` |
| `crown_class` | Crown class (1-4) | `2` |
| `defects` | Defect codes | `hollow, fork` |
| `mother_tree` | Mother tree flag (Y/N) | `Y` |

### Sample CSV Structure
```csv
plot_id,tree_id,species,dbh_cm,height_m,block_name
P001,1,SHOR,35.2,18.5,Chautara
P001,2,SAL,28.7,15.2,Chautara
P002,1,PINE,42.1,22.0,Deurali
```

### Template Download
Click **"Download CSV Template"** on the upload page for a pre-formatted file with headers.

---

## Step 2: Upload Process

### 1. Navigate to Inventory Upload
**My Uploads** → **Inventory Upload** page

### 2. Select File
- Click **"Choose CSV File"** or drag & drop
- Maximum file size: **50 MB** (~500,000 rows)

### 3. Column Mapping (Automatic)
System auto-detects columns. Review and adjust:
- **Green** = Auto-matched correctly
- **Yellow** = Needs manual selection
- **Red** = Required column missing

**Map each field:**
```
Your Column → System Field
tree_species  → species
diameter_cm   → dbh_cm
tree_height   → height_m
```

### 4. Configuration Options
| Setting | Default | Description |
|---------|---------|-------------|
| Grid Spacing (m) | 20 | Mother tree selection grid |
| Projection EPSG | (auto) | 32644 (UTM 44N) or 32645 (UTM 45N) |
| Calculation ID | (optional) | Link to existing forest boundary |
| Correction Strategy | Nearest Tree | How to handle out-of-boundary trees |

### 5. Validate & Upload
1. Click **"Preview Mapping"** → Review first 10 rows
2. Click **"Upload & Validate"** → System checks:
   - ✅ DBH range (0-300 cm)
   - ✅ Height ≥ DBH
   - ✅ Species codes recognized
   - ✅ Plot IDs consistent
   - ✅ Coordinate validation (if GPS provided)

---

## Step 3: Review Validation Results

### Summary Dashboard
| Metric | Description |
|--------|-------------|
| Total Rows | All records in file |
| Valid Rows | Pass all checks |
| Errors | Must fix before processing |
| Warnings | Review but can proceed |

### Error Types (Red - Must Fix)
| Error | Fix |
|-------|-----|
| `DBH out of range (0-300 cm)` | Check data entry; remove outliers |
| `Height < DBH` | Swap values or re-measure |
| `Unknown species: XYZ` | Add to species list or fix spelling |
| `Duplicate plot+tree ID` | Fix numbering in source data |
| `Missing required column` | Add column in CSV |

### Warnings (Yellow - Review)
| Warning | Action |
|---------|--------|
| `Species match confidence < 80%` | Verify species name |
| `Height seems low for DBH` | Check measurement |
| `Tree outside boundary` | Choose correction strategy |

### Auto-Corrections Applied
System automatically:
- Standardizes species names (fuzzy match to master list)
- Converts Nepali digits to Arabic (१२३ → 123)
- Assigns block via spatial join (if boundary linked)

---

## Step 4: Process Inventory

### If Validation Passes
1. Click **"Process Inventory"**
2. System calculates:
   - **Stem volume** (species-specific equations)
   - **Branch volume** (allometric equations)
   - **Per-hectare values** (by block & species)
   - **MAI/AAH** (Mean Annual Increment / Allowable Annual Harvest)

### Processing Time
- < 1,000 trees: ~10 seconds
- 1,000-10,000: ~30 seconds
- 10,000+: ~1-2 minutes

---

## Step 5: View Results

### Inventory Detail Page
- **Species breakdown** (volume, count, % by block)
- **DBH class distribution** (8 classes per CFMG)
- **Per-hectare summaries** (volume, stems, basal area)
- **MAI/AAH tables** (for harvest planning)

### Export Options
| Format | Use Case |
|--------|----------|
| **DFO Excel** | 15-sheet government format |
| **CSV** | Further analysis in R/Python |
| **GeoJSON** | Map visualization |
| **GPX** | Field navigation |

---

## Common Issues & Fixes

| Problem | Solution |
|---------|----------|
| "Column mapping failed" | Download template; ensure headers match exactly |
| Species not recognized | Add local names to `species_coefficients` table via admin |
| Trees outside boundary | Choose "Snap to Nearest Tree" correction strategy |
| Slow upload | Reduce file size; split into multiple uploads per block |
| Volume seems wrong | Check species coefficients; verify DBH/height units |

---

## Pro Tips
- **Use the template** — saves 90% mapping time
- **Include block_name** — enables automatic block assignment
- **Validate in Excel first** — filter for DBH>300, height<DBH
- **Keep original file** — for audit trail
- **Test with small file first** — 50 rows to verify mapping

---

## Video Tutorial
📺 [Watch: Inventory CSV Upload (4 min)](https://example.com/videos/inventory-upload)

*Guide version 1.0 | Last updated: 2026-07-20*