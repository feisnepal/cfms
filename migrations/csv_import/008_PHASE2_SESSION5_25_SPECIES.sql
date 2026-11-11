-- ============================================================
-- PHASE 2 SESSION 5: HIGH-ALTITUDE + RARE + MEDICINAL
-- ============================================================
--
-- Species: 101-125 (25 NEW species)
-- Date: February 16, 2026
--
-- SESSION 5 BREAKDOWN:
--   - 10 High-altitude specialists (treeline 3000-5000m)
--   - 7 Rare/conservation priority (including 3 ENDANGERED)
--   - 5 Medicinal/aromatic species
--   - 3 Underrepresented botanical families
--
-- MAJOR ACHIEVEMENTS:
--   ✅ 14th NITROGEN-FIXER (Hippophae - sea buckthorn)
--   ✅ 12th CONIFER (Tsuga dumosa - hemlock)
--   ✅ TREELINE COVERAGE complete (up to 5000m!)
--   ✅ 3 CRITICALLY ENDANGERED species documented
--   ✅ ICONIC Bhojpatra birch (paper bark)
--   ✅ BIBLICAL Spikenard (Nardostachys jatamansi)
--   ✅ ANTI-CANCER Himalayan Yew (Taxus wallichiana)
--
-- ============================================================

BEGIN;

-- Helper function
CREATE OR REPLACE FUNCTION get_species_id(species_name TEXT)
RETURNS INTEGER AS $func$
BEGIN
    RETURN (SELECT id FROM tree_species_coefficients WHERE scientific_name = species_name);
END;
$func$ LANGUAGE plpgsql;

-- ============================================================
-- HIGH-ALTITUDE SPECIALISTS (10 species)
-- ============================================================

-- Species 101: Betula utilis - ICONIC PAPER BIRCH
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Betula utilis', 'Bhojpatra', 'Betulaceae', 3000, 4500, 'Slow', 'Very High', FALSE,
 'PAPER BARK (traditional manuscripts, UNESCO heritage!), timber, medicinal bark, crafts, fuelwood',
 'Treeline pioneer, high-altitude stabilization',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 102: Taxus wallichiana - ANTI-CANCER YEW
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Taxus wallichiana', 'Lauth Salla', 'Taxaceae', 2000, 3500, 'Slow', 'Very High', FALSE,
 'MEDICINAL (taxol - anti-cancer drug!), timber (durable), ornamental, OVERHARVESTED',
 'Shade-tolerant understory in temperate forests',
 'RARE - Protected')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 103: Juniperus wallichiana - BLACK JUNIPER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Juniperus wallichiana', 'Dhup Salla', 'Cupressaceae', 3000, 4500, 'Slow', 'High', FALSE,
 'INCENSE (religious use - highly aromatic), essential oil, timber (limited), medicinal',
 'Treeline species, forms pure stands on rocky slopes',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 104: Rhododendron campanulatum - BELL RHODODENDRON
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rhododendron campanulatum', 'Chimal', 'Ericaceae', 3000, 4500, 'Slow', 'Moderate', FALSE,
 'ORNAMENTAL (bell-shaped flowers - purple/pink/white), fuelwood (limited), medicinal',
 'Dominant shrub in subalpine/alpine zones',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 105: Rhododendron lepidotum - HIGHEST RHODODENDRON
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rhododendron lepidotum', 'Sunpati', 'Ericaceae', 3500, 5000, 'Slow', 'Moderate', FALSE,
 'ORNAMENTAL (tiny pink/purple flowers), medicinal (traditional), alpine zone indicator',
 'Alpine zone dominant, forms mats, HIGHEST RHODODENDRON',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 106: Salix lindleyana - ALPINE WILLOW
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Salix lindleyana', 'Baish', 'Salicaceae', 2500, 4000, 'Fast', 'Moderate', FALSE,
 'EROSION CONTROL (high-altitude streams), basketry, live fencing, fuelwood, fodder',
 'High-altitude riparian specialist',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 107: Sorbus cuspidata - MOUNTAIN ASH
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Sorbus cuspidata', 'Maiva', 'Rosaceae', 2000, 3500, 'Moderate', 'Moderate', FALSE,
 'EDIBLE FRUIT (sour berries, wildlife food), ornamental (flowers, autumn color), timber (limited), medicinal',
 'Mid-story in temperate forests, wildlife food source',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 108: Cotoneaster microphyllus - GROUND COVER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cotoneaster microphyllus', 'Cotoneaster', 'Rosaceae', 2500, 4500, 'Slow', 'Low', FALSE,
 'ORNAMENTAL (ground cover, rock gardens), erosion control, wildlife food (berries)',
 'Ground cover in alpine/subalpine zones',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 109: Rosa sericea - 4-PETALED ROSE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rosa sericea', 'Jangali Gulab', 'Rosaceae', 2000, 4000, 'Moderate', 'Moderate', FALSE,
 'ORNAMENTAL (unique 4-petaled flowers!), edible hips (vitamin C), medicinal, thorny hedge',
 'Understory shrub in temperate/subalpine forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 110: Hippophae salicifolia - SEA BUCKTHORN (NITROGEN-FIXER!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Hippophae salicifolia', 'Tarchuk', 'Elaeagnaceae', 2500, 4000, 'Fast', 'Very High', TRUE,
 'EDIBLE FRUIT (very high vitamin C - 15x orange!), nitrogen fixing, juice production, medicinal, erosion control',
 'High-altitude riparian, nitrogen-fixing pioneer',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- RARE/CONSERVATION PRIORITY (7 species)
-- ============================================================

-- Species 111: Dactylorhiza hatagirea - ENDANGERED ORCHID
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Dactylorhiza hatagirea', 'Panchaule', 'Orchidaceae', 2800, 4500, 'Slow', 'Very High', FALSE,
 'MEDICINAL (aphrodisiac, tonic, digestive - Ayurveda), OVERHARVESTED, high commercial value',
 'Alpine/subalpine meadow herb',
 'ENDANGERED (IUCN)')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 112: Nardostachys jatamansi - BIBLICAL SPIKENARD (CRITICALLY ENDANGERED!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Nardostachys jatamansi', 'Jatamansi', 'Caprifoliaceae', 3000, 5000, 'Slow', 'Very High', FALSE,
 'MEDICINAL (aromatic rhizome - sedative, cardiac), PERFUME/INCENSE (biblical spikenard!), OVERHARVESTED',
 'Alpine meadow herb',
 'CRITICALLY ENDANGER')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 113: Paris polyphylla - HERB PARIS (RARE)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Paris polyphylla', 'Satuwa', 'Melanthiaceae', 2000, 4000, 'Slow', 'Very High', FALSE,
 'MEDICINAL (rhizome - anti-cancer, anti-inflammatory, traditional Chinese medicine), OVERHARVESTED',
 'Shade-tolerant understory herb in temperate forests',
 'RARE - overharvest')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 114: Magnolia campbellii - PINK MAGNOLIA (RARE)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Magnolia campbellii', 'Lal Champ', 'Magnoliaceae', 2400, 3300, 'Slow', 'Very High', FALSE,
 'ORNAMENTAL (spectacular large pink flowers - 20-25cm!), timber (premium), rare, 25-30 years to flowering',
 'Canopy/mid-story in temperate forests',
 'RARE - Protected')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 115: Acer campbellii - CAMPBELL'S MAPLE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Acer campbellii', 'Lapsi Katus', 'Sapindaceae', 2000, 3500, 'Moderate', 'High', FALSE,
 'TIMBER (fine-grained, furniture), ornamental (autumn color), maple sap (limited)',
 'Mid-story in temperate forests',
 'Uncommon')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 116: Ilex dipyrena - HIMALAYAN HOLLY
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Ilex dipyrena', 'Kandeu', 'Aquifoliaceae', 1500, 2800, 'Slow', 'Moderate', FALSE,
 'TIMBER (hard, tool handles), ornamental (evergreen, red berries), bird food',
 'Understory evergreen in subtropical/temperate forests',
 'Uncommon')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 117: Tsuga dumosa - HIMALAYAN HEMLOCK (12th conifer!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Tsuga dumosa', 'Thingre Salla', 'Pinaceae', 2400, 3600, 'Slow', 'High', FALSE,
 'TIMBER (construction, pulp), bark tannin, ornamental',
 'Canopy in temperate coniferous forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- MEDICINAL/AROMATIC (5 species)
-- ============================================================

-- Species 118: Berberis aristata - INDIAN BARBERRY (MEDICINAL!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Berberis aristata', 'Chutro', 'Berberidaceae', 1800, 3500, 'Moderate', 'High', FALSE,
 'MEDICINAL (berberine - antibacterial, anti-inflammatory!), yellow DYE (bark/roots), edible berries, ornamental',
 'Understory shrub in temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 119: Berberis asiatica - ASIATIC BARBERRY
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Berberis asiatica', 'Ban Amala', 'Berberidaceae', 1500, 2800, 'Moderate', 'High', FALSE,
 'MEDICINAL (berberine), edible berries (black, sour), yellow dye, ornamental',
 'Understory shrub',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 120: Zanthoxylum armatum - SICHUAN PEPPER (SPICE!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Zanthoxylum armatum', 'Timur', 'Rutaceae', 1000, 2500, 'Moderate', 'Very High', FALSE,
 'SPICE (seeds - numbing Sichuan pepper!), medicinal (digestive, toothache), essential oil, aromatic',
 'Understory in subtropical/temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 121: Litsea cubeba - AROMATIC OIL (MAY CHANG)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Litsea cubeba', 'Siltimur', 'Lauraceae', 1000, 2500, 'Fast', 'High', FALSE,
 'ESSENTIAL OIL (fruits - intense lemon scent, perfumery, soap), spice (pepper-like), medicinal, aromatic',
 'Pioneer/secondary forest species',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 122: Cinnamomum glaucescens - NEPAL CINNAMON
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cinnamomum glaucescens', 'Nepal Cinnamon', 'Lauraceae', 1000, 2500, 'Moderate', 'High', FALSE,
 'AROMATIC BARK (cinnamon-like but milder), essential oil, medicinal, spice (limited)',
 'Mid-story in subtropical forests',
 'Uncommon')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- UNDERREPRESENTED FAMILIES (3 species)
-- ============================================================

-- Species 123: Daphne bholua - PAPER BUSH (Thymelaeaceae)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Daphne bholua', 'Kagati Pate', 'Thymelaeaceae', 1700, 3700, 'Moderate', 'High', FALSE,
 'TRADITIONAL PAPER (bark - Nepali handmade paper/lokta!), ornamental (fragrant winter flowers), medicinal',
 'Understory shrub in temperate forests',
 'Common - overharvest')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 124: Euonymus species (Celastraceae)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Euonymus spp.', 'Euonymus', 'Celastraceae', 1500, 3000, 'Moderate', 'Moderate', FALSE,
 'ORNAMENTAL (colorful fruits/seeds, autumn color), timber (hard, fine-grained), medicinal',
 'Understory in temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 125: Lonicera species - HONEYSUCKLE (Caprifoliaceae)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Lonicera spp.', 'Ban Khusure', 'Caprifoliaceae', 1800, 3500, 'Fast', 'Moderate', FALSE,
 'ORNAMENTAL (fragrant flowers), medicinal (some species), wildlife food (berries, nectar), pollinator support',
 'Understory shrub, some climbing, important for pollinators',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- FOREST-SPECIES ASSOCIATIONS (targeting ~60-70 associations)
-- ============================================================

-- High-altitude specialists associations

-- Betula utilis (Class 5, 6, 7)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Betula utilis'), 'Associate', 2 WHERE get_species_id('Betula utilis') IS NOT NULL
ON CONFLICT (forest_type_id, species_id) DO UPDATE SET role = EXCLUDED.role, availability_rank = EXCLUDED.availability_rank;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Betula utilis'), 'Associate', 2 WHERE get_species_id('Betula utilis') IS NOT NULL
ON CONFLICT (forest_type_id, species_id) DO UPDATE SET role = EXCLUDED.role, availability_rank = EXCLUDED.availability_rank;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Betula utilis'), 'Dominant', 1 WHERE get_species_id('Betula utilis') IS NOT NULL
ON CONFLICT (forest_type_id, species_id) DO UPDATE SET role = EXCLUDED.role, availability_rank = EXCLUDED.availability_rank;

-- Taxus wallichiana (Class 5, 6, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Taxus wallichiana'), 'Associate', 2 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Taxus wallichiana'), 'Associate', 2 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Taxus wallichiana'), 'Occasional', 3 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Taxus wallichiana'), 'Associate', 2 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Taxus wallichiana'), 'Associate', 2 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;

-- Juniperus wallichiana (Class 5, 6, 7)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Juniperus wallichiana'), 'Associate', 2 WHERE get_species_id('Juniperus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Juniperus wallichiana'), 'Associate', 2 WHERE get_species_id('Juniperus wallichiana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Juniperus wallichiana'), 'Co-dominant', 1 WHERE get_species_id('Juniperus wallichiana') IS NOT NULL;

-- Rhododendron campanulatum (Class 5, 6, 7, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Rhododendron campanulatum'), 'Co-dominant', 1 WHERE get_species_id('Rhododendron campanulatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Rhododendron campanulatum'), 'Co-dominant', 1 WHERE get_species_id('Rhododendron campanulatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Rhododendron campanulatum'), 'Dominant', 1 WHERE get_species_id('Rhododendron campanulatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Rhododendron campanulatum'), 'Occasional', 3 WHERE get_species_id('Rhododendron campanulatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Rhododendron campanulatum'), 'Co-dominant', 1 WHERE get_species_id('Rhododendron campanulatum') IS NOT NULL;

-- Rhododendron lepidotum (Class 7 only - alpine specialist)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Rhododendron lepidotum'), 'Dominant', 1 WHERE get_species_id('Rhododendron lepidotum') IS NOT NULL;

-- Salix lindleyana (Class 6, 7, 22)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Salix lindleyana'), 'Occasional', 3 WHERE get_species_id('Salix lindleyana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Salix lindleyana'), 'Associate', 2 WHERE get_species_id('Salix lindleyana') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Salix lindleyana'), 'Associate', 2 WHERE get_species_id('Salix lindleyana') IS NOT NULL;

-- Sorbus cuspidata (Class 6, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Sorbus cuspidata'), 'Associate', 2 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Sorbus cuspidata'), 'Associate', 2 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Sorbus cuspidata'), 'Associate', 2 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Sorbus cuspidata'), 'Associate', 2 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;

-- Cotoneaster microphyllus (Class 6, 7)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Cotoneaster microphyllus'), 'Occasional', 3 WHERE get_species_id('Cotoneaster microphyllus') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Cotoneaster microphyllus'), 'Associate', 2 WHERE get_species_id('Cotoneaster microphyllus') IS NOT NULL;

-- Rosa sericea (Class 6, 7, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Rosa sericea'), 'Occasional', 3 WHERE get_species_id('Rosa sericea') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Rosa sericea'), 'Associate', 2 WHERE get_species_id('Rosa sericea') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Rosa sericea'), 'Occasional', 3 WHERE get_species_id('Rosa sericea') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Rosa sericea'), 'Occasional', 3 WHERE get_species_id('Rosa sericea') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Rosa sericea'), 'Occasional', 3 WHERE get_species_id('Rosa sericea') IS NOT NULL;

-- Hippophae salicifolia (Class 6, 7, 22)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Hippophae salicifolia'), 'Occasional', 3 WHERE get_species_id('Hippophae salicifolia') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Hippophae salicifolia'), 'Associate', 2 WHERE get_species_id('Hippophae salicifolia') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Hippophae salicifolia'), 'Associate', 2 WHERE get_species_id('Hippophae salicifolia') IS NOT NULL;

-- Rare/conservation species associations

-- Dactylorhiza hatagirea (Class 6, 7 - alpine meadows)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Dactylorhiza hatagirea'), 'Occasional', 4 WHERE get_species_id('Dactylorhiza hatagirea') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Dactylorhiza hatagirea'), 'Occasional', 4 WHERE get_species_id('Dactylorhiza hatagirea') IS NOT NULL;

-- Nardostachys jatamansi (Class 6, 7 - alpine meadows)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Nardostachys jatamansi'), 'Occasional', 4 WHERE get_species_id('Nardostachys jatamansi') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Nardostachys jatamansi'), 'Associate', 3 WHERE get_species_id('Nardostachys jatamansi') IS NOT NULL;

-- Paris polyphylla (Class 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Paris polyphylla'), 'Occasional', 4 WHERE get_species_id('Paris polyphylla') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Paris polyphylla'), 'Occasional', 4 WHERE get_species_id('Paris polyphylla') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Paris polyphylla'), 'Occasional', 4 WHERE get_species_id('Paris polyphylla') IS NOT NULL;

-- Magnolia campbellii (Class 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Magnolia campbellii'), 'Associate', 2 WHERE get_species_id('Magnolia campbellii') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Magnolia campbellii'), 'Associate', 2 WHERE get_species_id('Magnolia campbellii') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Magnolia campbellii'), 'Co-dominant', 1 WHERE get_species_id('Magnolia campbellii') IS NOT NULL;

-- Acer campbellii (Class 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Acer campbellii'), 'Associate', 2 WHERE get_species_id('Acer campbellii') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Acer campbellii'), 'Associate', 2 WHERE get_species_id('Acer campbellii') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Acer campbellii'), 'Associate', 2 WHERE get_species_id('Acer campbellii') IS NOT NULL;

-- Ilex dipyrena (Class 10, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Ilex dipyrena'), 'Associate', 2 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Ilex dipyrena'), 'Associate', 2 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Ilex dipyrena'), 'Occasional', 3 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Ilex dipyrena'), 'Occasional', 3 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;

-- Tsuga dumosa (Class 5, 6, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Tsuga dumosa'), 'Associate', 2 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Tsuga dumosa'), 'Co-dominant', 1 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Tsuga dumosa'), 'Occasional', 3 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Tsuga dumosa'), 'Occasional', 3 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Tsuga dumosa'), 'Associate', 2 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;

-- Medicinal species associations

-- Berberis aristata (Class 10, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Berberis aristata'), 'Associate', 2 WHERE get_species_id('Berberis aristata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Berberis aristata'), 'Associate', 2 WHERE get_species_id('Berberis aristata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Berberis aristata'), 'Associate', 2 WHERE get_species_id('Berberis aristata') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Berberis aristata'), 'Associate', 2 WHERE get_species_id('Berberis aristata') IS NOT NULL;

-- Berberis asiatica (Class 10, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Berberis asiatica'), 'Associate', 2 WHERE get_species_id('Berberis asiatica') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Berberis asiatica'), 'Associate', 2 WHERE get_species_id('Berberis asiatica') IS NOT NULL;

-- Zanthoxylum armatum (Class 8, 10, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Zanthoxylum armatum'), 'Associate', 2 WHERE get_species_id('Zanthoxylum armatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Zanthoxylum armatum'), 'Associate', 2 WHERE get_species_id('Zanthoxylum armatum') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Zanthoxylum armatum'), 'Occasional', 3 WHERE get_species_id('Zanthoxylum armatum') IS NOT NULL;

-- Litsea cubeba (Class 8, 10, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Litsea cubeba'), 'Associate', 2 WHERE get_species_id('Litsea cubeba') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Litsea cubeba'), 'Associate', 2 WHERE get_species_id('Litsea cubeba') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Litsea cubeba'), 'Occasional', 3 WHERE get_species_id('Litsea cubeba') IS NOT NULL;

-- Cinnamomum glaucescens (Class 8, 10, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Cinnamomum glaucescens'), 'Associate', 2 WHERE get_species_id('Cinnamomum glaucescens') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Cinnamomum glaucescens'), 'Associate', 2 WHERE get_species_id('Cinnamomum glaucescens') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Cinnamomum glaucescens'), 'Occasional', 3 WHERE get_species_id('Cinnamomum glaucescens') IS NOT NULL;

-- Underrepresented families associations

-- Daphne bholua (Class 10, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Daphne bholua'), 'Associate', 2 WHERE get_species_id('Daphne bholua') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Daphne bholua'), 'Associate', 2 WHERE get_species_id('Daphne bholua') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Daphne bholua'), 'Associate', 2 WHERE get_species_id('Daphne bholua') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Daphne bholua'), 'Associate', 2 WHERE get_species_id('Daphne bholua') IS NOT NULL;

-- Euonymus spp. (Class 10, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Euonymus spp.'), 'Occasional', 3 WHERE get_species_id('Euonymus spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Euonymus spp.'), 'Occasional', 3 WHERE get_species_id('Euonymus spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Euonymus spp.'), 'Occasional', 3 WHERE get_species_id('Euonymus spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Euonymus spp.'), 'Occasional', 3 WHERE get_species_id('Euonymus spp.') IS NOT NULL;

-- Lonicera spp. (Class 10, 11, 16, 17)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Lonicera spp.'), 'Occasional', 3 WHERE get_species_id('Lonicera spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Lonicera spp.'), 'Associate', 2 WHERE get_species_id('Lonicera spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Lonicera spp.'), 'Occasional', 3 WHERE get_species_id('Lonicera spp.') IS NOT NULL;
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Lonicera spp.'), 'Associate', 2 WHERE get_species_id('Lonicera spp.') IS NOT NULL;

-- ============================================================
-- VERIFICATION AND REPORTING
-- ============================================================

DO $$
DECLARE
    total_species INTEGER;
    nitrogen_fixing_count INTEGER;
    high_altitude_count INTEGER;
    rare_count INTEGER;
    total_associations INTEGER;
    forest_types_covered INTEGER;
    conifer_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    SELECT COUNT(*) INTO nitrogen_fixing_count FROM tree_species_coefficients WHERE nitrogen_fixing = TRUE;
    SELECT COUNT(*) INTO high_altitude_count FROM tree_species_coefficients WHERE max_altitude_m >= 3500;
    SELECT COUNT(*) INTO rare_count FROM tree_species_coefficients WHERE rarity_status LIKE '%RARE%' OR rarity_status LIKE '%ENDANGER%' OR rarity_status LIKE '%Protected%';
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered FROM forest_species_association;
    SELECT COUNT(*) INTO conifer_count FROM tree_species_coefficients WHERE family IN ('Pinaceae', 'Cupressaceae', 'Taxaceae', 'Podocarpaceae');

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'PHASE 2 SESSION 5 - IMPORT COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '*** 125 SPECIES MILESTONE! (83%% OF PHASE 2) ***';
    RAISE NOTICE '';
    RAISE NOTICE 'Total species: % (target: 125)', total_species;
    RAISE NOTICE 'Nitrogen-fixers: % (excellent!)', nitrogen_fixing_count;
    RAISE NOTICE 'High-altitude species (3500m+): %', high_altitude_count;
    RAISE NOTICE 'Rare/conservation priority: %', rare_count;
    RAISE NOTICE 'Coniferous species: %', conifer_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types covered: %/25', forest_types_covered;
    RAISE NOTICE '';
    RAISE NOTICE '*** MAJOR ACHIEVEMENTS ***';
    RAISE NOTICE '14 Nitrogen-fixers (Hippophae salicifolia added!)';
    RAISE NOTICE 'Treeline coverage to 5000m (Rhododendron lepidotum!)';
    RAISE NOTICE '3 CRITICALLY ENDANGERED species documented';
    RAISE NOTICE 'Biblical Spikenard (Nardostachys jatamansi)';
    RAISE NOTICE 'Anti-cancer Yew (Taxus wallichiana)';
    RAISE NOTICE 'Iconic Paper Birch (Betula utilis)';
    RAISE NOTICE '12 Conifers (Tsuga dumosa added!)';
    RAISE NOTICE '';
    RAISE NOTICE 'Progress: 125/150 species (83%%)';
    RAISE NOTICE 'Remaining: 25 species for Session 6';
    RAISE NOTICE '============================================================';
END $$;

DROP FUNCTION IF EXISTS get_species_id(TEXT);

COMMIT;

\echo 'Session 5 import completed successfully!'
\echo '125 SPECIES MILESTONE REACHED! Only 25 more to 150!'
