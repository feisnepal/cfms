# Block & Compartment Creation Guide
**ब्लक र कम्पार्टमेन्ट सिर्जना गर्ने प्रक्रिया**

## Overview
Blocks are the primary management units (5-25 ha each). Compartments are subdivisions within blocks for detailed management. This guide covers both.

---

## Part A: Block Naming & Configuration

### After Boundary Upload
Once your forest boundary is uploaded and validated, you'll be directed to **Block Naming** page.

### Step 1: Choose Block Mode
| Mode | When to Use |
|------|-------------|
| **Single Block** | Forest < 25 ha, managed as one unit |
| **Multiple Blocks** | Forest > 25 ha, or distinct management zones |

### Step 2: Multiple Blocks - Auto Division
If you choose "Multiple Blocks":
1. System shows auto-generated blocks (Voronoi/grid-based)
2. **Review each block** on the map
3. **Rename blocks** with local names (e.g., "Chautara Block", "Deurali Block")
4. **Merge/split** as needed using map tools

### Step 3: Manual Block Editing
- **Click a block** to select (highlighted in blue)
- **Drag vertices** to adjust boundaries
- **Right-click** → "Split Block" to divide
- **Select multiple** → "Merge Blocks" to combine

### Step 4: Block Attributes
For each block, enter:
- **Block Name** (local name, required)
- **Management Type** (Protection / Production / Conservation)
- **Priority** (High / Medium / Low)

### Step 5: Save & Continue
Click **"Save & Continue"** → System validates:
- ✅ All blocks named
- ✅ No overlaps/gaps
- ✅ Each block 1-50 ha (CFMG guidelines)

---

## Part B: Compartment Splitting

### When to Create Compartments
- Block > 20 ha requiring different prescriptions
- Distinct forest types within block (e.g., Sal vs. Pine areas)
- Different slope/aspect requiring different management

### Step 1: Open Compartment Tab
From **Calculation Detail** → **Compartments** tab

### Step 2: Select Parent Block
Choose the block to subdivide from the dropdown

### Step 3: Choose Split Method
| Method | Description | Best For |
|--------|-------------|----------|
| **Equal Area** | Divides into N equal-area compartments | Uniform forest |
| **Proportional by Stems** | Areas proportional to tree count | Variable density |
| **Manual Drawing** | Draw boundaries on map | Natural boundaries (ridges, streams) |

### Step 4: Configure Split
- **Number of compartments** (2-10)
- **Naming prefix** (e.g., "C1-" → C1-1, C1-2...)
- **Minimum size**: 1 ha per compartment

### Step 5: Preview & Confirm
1. Click **"Preview Split"** → See map with proposed boundaries
2. **Adjust** by dragging boundaries if using manual method
3. Click **"Confirm Split"**

### Step 6: Tree Reassignment
Trees on split boundaries are automatically reassigned to nearest compartment centroid. Review in **Tree Reassignment Dialog**.

---

## Part C: Sub-Area Management

### Sub-Area Types
| Category | Code | Description | Excluded from Area? |
|----------|------|-------------|---------------------|
| Protected | `protected` | Religious sites, biodiversity hotspots | No |
| Plantation | `plantation` | Enrichment planting areas | No |
| Private Land | `private_land` | Private holdings within CF | **Yes** |
| Encroached | `encroached` | Illegally occupied | **Yes** |
| Water Body | `water` | Ponds, streams | **Yes** |
| Barren | `barren` | Rocky, non-forest | **Yes** |
| Settlement | `settlement` | Habitation areas | **Yes** |
| Agriculture | `agriculture` | Cultivated land | **Yes** |

### Adding Sub-Areas
1. Select **"Add Sub-Area"** in sidebar
2. **Choose category** from dropdown
3. **Draw polygon** on map (or upload KML)
3. **Enter name** (e.g., "Devi Sthan Protected Zone")
4. **Save**

### Auto-Calculation
System automatically:
- Subtracts excluded sub-areas from **Effective Area**
- Updates **Table 5** (Block Area Detail) in Operational Plan
- Recalculates growing stock per effective hectare

---

## Validation Rules
- ❌ Blocks cannot overlap
- ❌ Sub-areas cannot extend outside parent block
- ❌ Compartments must stay within parent block
- ❌ Minimum block area: 1 ha
- ❌ Minimum compartment area: 1 ha
- ✅ Sub-areas can span multiple blocks

---

## Common Issues

| Issue | Solution |
|-------|----------|
| "Blocks overlap" | Use map tools to snap boundaries; check for duplicate vertices |
| "Sub-area outside block" | Redraw sub-area within block boundary |
| "Tree reassignment failed" | Check for trees exactly on boundary line; manual adjust |
| "Compartment too small" | Merge with adjacent or reduce compartment count |

---

## Next Steps After Blocks/Compartments
1. **Inventory Upload** → Add tree measurements per block
2. **Sampling Design** → Generate sample plots
3. **Analysis** → Run forest analysis (slope, aspect, canopy, biomass)
4. **Operational Plan** → Auto-populate from collected data

---

## Video Tutorial
📺 [Watch: Block & Compartment Creation (5 min)](https://example.com/videos/blocks-compartments)

*Guide version 1.0 | Last updated: 2026-07-20*