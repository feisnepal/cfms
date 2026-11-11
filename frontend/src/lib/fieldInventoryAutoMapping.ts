/**
 * Which file column is which, for a field-inventory spreadsheet: the one mapping both the Field Inventory tab and "Add data" use, so the same
 * file gives the same result from either. Matching is by normalised column name (case, spaces and underscores ignored); validation / check
 * columns are skipped; a column the template does not know is left out (the server's own column detection then reports what is missing).
 */
export function autoMapFieldInventoryColumns(csvColumns: string[]): Record<string, string> {
  const autoMapping: Record<string, string> = {};
  (csvColumns || []).forEach((col: string) => {
    const lowerCol = col.toLowerCase().replace(/[_\s]/g, '');

    // Skip validation/check columns (contain "check", "valid", "status", etc.)
    if (lowerCol.includes('check') || lowerCol.includes('valid') || lowerCol.includes('status')) {
      return;
    }

    // Map common columns — accept compartment_name as block_name alias
    if ((lowerCol.includes('block') && lowerCol.includes('name')) || lowerCol === 'blockname' ||
        (lowerCol.includes('compartment') && lowerCol.includes('name')) || lowerCol === 'compartmentname') {
      autoMapping['block_name'] = col;
    }
    if ((lowerCol.includes('sample') && lowerCol.includes('plot')) || lowerCol.includes('plotnumber')) {
      autoMapping['sample_plot_number'] = col;
    }
    if (lowerCol === 'latitude' || lowerCol === 'lat') autoMapping['latitude'] = col;
    if (lowerCol === 'longitude' || lowerCol === 'lon' || lowerCol === 'long') autoMapping['longitude'] = col;

    // Species columns - exact match to avoid confusion
    if (lowerCol === 'regenspeciesscientific' || lowerCol === 'regenspecies') {
      autoMapping['regen_species_scientific'] = col;
    }
    if (lowerCol === 'saplingspeciesscientific' || lowerCol === 'saplingspecies') {
      autoMapping['sapling_species_scientific'] = col;
    }
    if (lowerCol === 'polespeciesscientific' || lowerCol === 'polespecies') {
      autoMapping['pole_species_scientific'] = col;
    }
    if (lowerCol === 'treespeciesscientific' || lowerCol === 'treespecies') {
      autoMapping['tree_species_scientific'] = col;
    }

    // DBH columns - exact match to avoid picking up *_dbh_check columns
    if (lowerCol === 'regendbh' || lowerCol === 'regendbhcm') {
      autoMapping['regen_dbh_cm'] = col;
    }
    if (lowerCol === 'saplingdbh' || lowerCol === 'saplingdbhcm') {
      autoMapping['sapling_dbh_cm'] = col;
    }
    if (lowerCol === 'poledbh' || lowerCol === 'poledbhcm') {
      autoMapping['pole_dbh_cm'] = col;
    }
    if (lowerCol === 'treedbh' || lowerCol === 'treedbhcm') {
      autoMapping['tree_dbh_cm'] = col;
    }

    // Height columns - exact match to avoid picking up *_height_check columns
    if (lowerCol === 'poleheight' || lowerCol === 'poleheightm' || lowerCol === 'pole_height_m') {
      autoMapping['pole_height_m'] = col;
    }
    if (lowerCol === 'treeheight' || lowerCol === 'treeheightm' || lowerCol === 'tree_height_m') {
      autoMapping['tree_height_m'] = col;
    }

    // Class columns
    if (lowerCol === 'poleclass' || lowerCol === 'pole_class') {
      autoMapping['pole_class'] = col;
    }
    if (lowerCol === 'treeclass' || lowerCol === 'tree_class') {
      autoMapping['tree_class'] = col;
    }

    // Count columns
    if (lowerCol === 'regencount') autoMapping['regen_count'] = col;
    if (lowerCol === 'saplingcount') autoMapping['sapling_count'] = col;

    // Yield columns (firewood, grass, bedding material per 100 sqm per year)
    if (lowerCol === 'firewoodkgper100sqmperyear' || (lowerCol.includes('firewood') && lowerCol.includes('100sqm'))) {
      autoMapping['firewood_kg_per_100sqm_per_year'] = col;
    }
    if (lowerCol === 'grasskgper100sqmperyear' || (lowerCol.includes('grass') && lowerCol.includes('100sqm'))) {
      autoMapping['grass_kg_per_100sqm_per_year'] = col;
    }
    if (lowerCol === 'beddingmaterialkgper100sqmperyear' || (lowerCol.includes('bedding') && lowerCol.includes('100sqm'))) {
      autoMapping['bedding_material_kg_per_100sqm_per_year'] = col;
    }
  });
  return autoMapping;
}
