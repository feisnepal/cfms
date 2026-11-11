# Forest Boundary Upload Guide
**वन सीमा अपलोड गर्ने प्रक्रिया**

## Overview
Upload your community forest boundary to start the management planning process. The system accepts multiple file formats and will validate the geometry automatically.

## Supported Formats
| Format | Extension | Notes |
|--------|-----------|-------|
| Shapefile | `.shp`, `.dbf`, `.shx`, `.prj` | Must be zipped together |
| KML/KMZ | `.kml`, `.kmz` | Google Earth format |
| GeoJSON | `.geojson`, `.json` | Preferred for web |
| GPX | `.gpx` | GPS device export |

**Maximum file size: 50 MB**

---

## Step-by-Step Process

### Step 1: Prepare Your Boundary File
1. **If using GPS device:** Export as GPX or KML
2. **If using GIS software (QGIS/ArcGIS):** Export as Shapefile (zip all `.shp`, `.dbf`, `.shx`, `.prj` files) or GeoJSON
3. **If using Google Earth:** Save as KML
4. **Ensure coordinate system:** WGS84 (EPSG:4326) - latitude/longitude

### Step 2: Upload the File
1. Navigate to **My Uploads** → **Upload** page
2. Click **"Choose File"** or drag & drop your boundary file
3. Select the file from your computer
4. Click **"Upload & Validate"**

### Step 3: Review Validation Results
The system will automatically:
- ✅ Check file format validity
- ✅ Validate geometry (no self-intersections, closed polygons)
- ✅ Check coordinate system (must be WGS84)
- ✅ Calculate area in hectares
- ✅ Detect if it's a single polygon or multi-part (islands)

**If validation fails:** Error messages will appear in Nepali with specific fixes.

### Step 4: Draw/Adjust Boundary (Optional)
If you prefer to draw manually:
1. Click **"Draw Boundary"** instead of uploading
2. Use the polygon tool on the map
3. Click to add vertices around your forest
4. Double-click to complete the polygon
5. Click **"Save Boundary"**

### Step 5: Configure Block Mode
After boundary is saved:
- **Single Block:** For small forests (< 25 ha) managed as one unit
- **Multiple Blocks:** System auto-divides or you can manually create blocks

---

## Common Issues & Solutions

| Error (Nepali) | Meaning | Fix |
|---|---|---|
| "ज्यामिति मान्य छैन" | Invalid geometry | Check for self-intersections; use QGIS "Fix Geometries" |
| "सीमा फाइल ढाँचा मिल्दैन" | Wrong file format | Use supported formats only; zip Shapefile components |
| "निर्देशांक प्रणाली WGS84 होइन" | Wrong projection | Reproject to EPSG:4326 in QGIS |
| "क्षेत्रफल शून्य छ" | Zero area | Ensure polygon is closed and has area |

---

## Next Steps After Upload
Once boundary is saved:
1. **Block Naming** → Define management blocks
2. **Sub-Areas** → Mark protected zones, plantations, private land
3. **Inventory Upload** → Add tree measurement data
4. **Sampling Design** → Generate sample plots
5. **Operational Plan** → Generate the full plan document

---

## Tips for Best Results
- **Use high-resolution GPS** (±3m accuracy or better)
- **Walk the boundary** with GPS logging enabled
- **Take photos** of boundary markers for reference
- **Coordinate with neighboring CFUGs** to avoid overlaps
- **Save original file** for future reference

---

## Video Tutorial
📺 [Watch: Forest Boundary Upload (3 min)](https://example.com/videos/boundary-upload)

*Guide version 1.0 | Last updated: 2026-07-20*