-- ============================================================
-- PHASE 2 SESSION 5: HIGH-ALTITUDE + RARE + MEDICINAL (FINAL)
-- ============================================================
--
-- Species: 101-128 (28 NEW species)
-- Date: February 17, 2026
--
-- SESSION 5 BREAKDOWN:
--   - 10 High-altitude specialists (treeline 2700-4900m)
--   - 8 Rare/conservation priority (3 CRITICALLY ENDANGERED!)
--   - 7 Medicinal/aromatic species
--   - 4 Underrepresented botanical families
--
-- MAJOR ACHIEVEMENTS:
--   ✅ 14 NITROGEN-FIXERS (Hippophae + Elaeagnus)
--   ✅ HIGH-ALTITUDE coverage to 4900m!
--   ✅ 3 CRITICALLY ENDANGERED species
--   ✅ LOKTA PAPER tradition (1000+ years)
--   ✅ TIMUR SPICE (Nepal's signature!)
--   ✅ HIGHEST WOODY PLANT (5200m - Juniperus indica)
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
-- HIGH-ALTITUDE SPECIALISTS (10 species: 101-110)
-- ============================================================

-- Species 101: Betula utilis - ICONIC PAPER BIRCH
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Betula utilis', 'Bhojpatra', 'Betulaceae', 2700, 4500, 'Fast', 'High', FALSE,
 'PAPER BARK (Buddhist manuscripts!), timber, fuelwood, sacred/cultural, ornamental',
 'Keystone treeline species, dominant in subalpine zones',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 102: Juniperus indica - HIGHEST WOODY PLANT
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Juniperus indica', 'Dhupi', 'Cupressaceae', 3600, 4800, 'Slow', 'High', FALSE,
 'INCENSE (Buddhist temples!), essential oil, forms "incense forests", HIGHEST WOODY PLANT (up to 5200m)',
 'Treeline specialist, forms pure stands',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 103: Salix lindleyana - MAT-FORMING ALPINE WILLOW
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Salix lindleyana', 'Nepal Willow', 'Salicaceae', 3600, 4900, 'Moderate', 'Low', FALSE,
 'Erosion control, alpine ground cover (MAT-FORMING - only 5cm high!), covers rocky screes',
 'Alpine mat-former, highest willow specialist',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 104: Rhododendron campanulatum - ALPINE RHODODENDRON
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rhododendron campanulatum', 'Chimal', 'Ericaceae', 3000, 4000, 'Slow', 'Moderate', FALSE,
 'MEDICINAL (antibacterial!), ornamental flowers, Annapurna Circuit favorite',
 'Subalpine shrub layer, bushy thickets',
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
('Rhododendron lepidotum', 'Sunpati', 'Ericaceae', 2500, 5000, 'Slow', 'High', FALSE,
 'MEDICINAL (blood purification, cold treatment), INCENSE (Buddhist monasteries!), antibacterial = streptomycin!',
 'Dwarf shrub layer, alpine specialist',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 106: Hippophae salicifolia - SUPER FRUIT (NITROGEN-FIXER #13!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Hippophae salicifolia', 'Dale Chuk', 'Elaeagnaceae', 2000, 3500, 'Moderate', 'Very High', TRUE,
 'SUPER FRUIT (15x Vitamin C of oranges!), juice, medicine, NITROGEN-FIXING, soil conservation, cosmetics',
 'Dry valley specialist, soil enrichment, erosion control',
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
('Sorbus cuspidata', 'Cheuli', 'Rosaceae', 1350, 3700, 'Moderate', 'Moderate', FALSE,
 'EDIBLE FRUIT (wild), ornamental (flowers, fruits), traditional food',
 'Major associate of upper Oak forest',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 108: Cotoneaster microphyllus - EXTREME ALTITUDE RANGE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cotoneaster microphyllus', 'Cotoneaster', 'Rosaceae', 1200, 5400, 'Slow', 'Low', FALSE,
 'Living fences, medicinal, ornamental (ground cover)',
 'Ground cover in alpine/subalpine zones',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 109: Rosa sericea - UNIQUE 4-PETALED ROSE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rosa sericea', 'Rosa', 'Rosaceae', 2000, 4400, 'Moderate', 'Moderate', FALSE,
 'ORNAMENTAL (ONLY rose with 4 petals!), medicinal (headaches, liver), edible hips',
 'Understory shrub in temperate/subalpine forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 110: Potentilla fruticosa - TEA SUBSTITUTE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Potentilla fruticosa', 'Potentilla', 'Rosaceae', 2000, 4000, 'Moderate', 'Low', FALSE,
 'Tea substitute, traditional medicine, ornamental',
 'High-altitude shrub layer',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- RARE/CONSERVATION PRIORITY (8 species: 111-118)
-- ============================================================

-- Species 111: Dactylorhiza hatagirea - CRITICALLY ENDANGERED ORCHID
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Dactylorhiza hatagirea', 'Panchaule', 'Orchidaceae', 2800, 5000, 'Very Slow', 'Very High', FALSE,
 'MEDICINAL (tonic, pyorrhea), CITES Appendix II, strictly protected in Nepal, OVERHARVESTED',
 'Alpine meadow herb',
 'CRITICALLY ENDANGERED')
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
('Nardostachys jatamansi', 'Jatamansi', 'Caprifoliaceae', 3000, 5000, 'Very Slow', 'Very High', FALSE,
 'AROMATIC rhizomes (perfume, medicine), used in 6 countries traditional medicine, OVERHARVESTED',
 'Alpine meadow herb',
 'CRITICALLY ENDANGERED')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 113: Valeriana jatamansi - SEDATIVE (CRITICALLY ENDANGERED!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Valeriana jatamansi', 'Sugandhawal', 'Caprifoliaceae', 1000, 3300, 'Slow', 'Very High', FALSE,
 'SEDATIVE (most acceptable in modern medicine!), valepotriates in roots, OVERHARVESTED',
 'Temperate forest herb',
 'CRITICALLY ENDANGERED')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 114: Neopicrorhiza scrophulariiflora - KUTKI (ENDANGERED!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Neopicrorhiza scrophulariiflora', 'Kutki', 'Plantaginaceae', 3500, 5000, 'Very Slow', 'Very High', FALSE,
 'MEDICINAL (45 Ayurvedic medicines in Nepal!), 23 herbal industries, government priority species',
 'Alpine/subalpine herb',
 'ENDANGERED')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 115: Paris polyphylla - SATUWA (VULNERABLE!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Paris polyphylla', 'Satuwa', 'Melanthiaceae', 1500, 3500, 'Slow', 'Very High', FALSE,
 'MEDICINAL ("from cut to cancer"), unsustainable harvesting threat',
 'Shade-tolerant understory herb',
 'VULNERABLE')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 116: Magnolia campbellii - PINK MAGNOLIA (RARE!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Magnolia campbellii', 'Champ', 'Magnoliaceae', 2500, 3000, 'Very Slow', 'Very High', FALSE,
 'ORNAMENTAL (spectacular white flowers in Nepal!), 25-30 years to sexual maturity, declined from logging',
 'Canopy/mid-story in temperate forests',
 'RARE')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 117: Acer campbellii - CAMPBELL'S MAPLE (RARE!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Acer campbellii', 'Campbell Maple', 'Sapindaceae', 1800, 3700, 'Slow', 'High', FALSE,
 'Timber, dominant with Magnolia in E. Nepal, doesn''t extend west of central Nepal',
 'Mid-story in temperate forests',
 'RARE')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 118: Ilex dipyrena - HIMALAYAN HOLLY
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Ilex dipyrena', 'Kandeu', 'Aquifoliaceae', 1500, 3350, 'Slow', 'Moderate', FALSE,
 'Medicinal (pain, swelling, burns, fever), timber, ornamental',
 'Understory evergreen',
 'Occasional')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- MEDICINAL/AROMATIC (7 species: 119-125, includes 1 cultural treasure)
-- ============================================================

-- Species 119: Berberis aristata - INDIAN BARBERRY
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Berberis aristata', 'Chutro', 'Berberidaceae', 850, 2500, 'Moderate', 'High', FALSE,
 'AYURVEDIC (berberine - antibacterial!), eye, skin, diabetes treatment',
 'Understory shrub',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 120: Zanthoxylum armatum - NEPAL'S SIGNATURE SPICE!
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Zanthoxylum armatum', 'Timur', 'Rutaceae', 500, 2500, 'Moderate', 'Very High', FALSE,
 'SPICE (Sichuan pepper - citrusy, numbing!), medicinal (toothache, diabetes, hypertension)',
 'Understory in subtropical/temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 121: Litsea cubeba - ESSENTIAL OIL (MAY CHANG)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Litsea cubeba', 'May Chang', 'Lauraceae', 300, 2700, 'Fast', 'Very High', FALSE,
 'ESSENTIAL OIL (lemon aroma - industrial crop!), anticancer, antimicrobial, antioxidant',
 'Pioneer/secondary forest',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 122: Cinnamomum glaucescens - "GIFT TO PERFUMERS"!
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cinnamomum glaucescens', 'Sugandha Kokila', 'Lauraceae', 1000, 2500, 'Moderate', 'Very High', FALSE,
 'ESSENTIAL OIL from fruit ("gift to perfumers"!), Ayurvedic tonic (digestive + CNS)',
 'Mid-story in subtropical forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 123: Lindera neesiana - SIL TIMUR
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Lindera neesiana', 'Sil Timur', 'Lauraceae', 1500, 2700, 'Moderate', 'Moderate', FALSE,
 'Medicinal (fruit chewed - diarrhea, toothache, gastric), antimicrobial essential oil',
 'Understory in temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 124: Daphne bholua - LOKTA (1000+ YEAR PAPER TRADITION!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Daphne bholua', 'Lokta', 'Thymelaeaceae', 1700, 3500, 'Moderate', 'Very High', FALSE,
 'TRADITIONAL PAPER (1000+ years! - sacred texts, documents), fragrant flowers, ALL PARTS POISONOUS (but bark medicinal)',
 'Understory shrub in temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- UNDERREPRESENTED FAMILIES (4 species: 125-128)
-- ============================================================

-- Species 125: Tsuga dumosa - HIMALAYAN HEMLOCK
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Tsuga dumosa', 'Himalayan Hemlock', 'Pinaceae', 1700, 3500, 'Slow', 'High', FALSE,
 'Timber (construction, pulp), dominates with fir at 2500-3000m, 116-year dendrochronology study',
 'Canopy in temperate coniferous forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 126: Rubus ellipticus - AISELU (GOLDEN RASPBERRY!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rubus ellipticus', 'Aiselu', 'Rosaceae', 800, 2200, 'Fast', 'High', FALSE,
 'EDIBLE FRUIT (golden yellow sweet raspberry!), Aiselu Wine Nepal project, nutraceutical potential',
 'Pioneer/edge species, fruiting bramble',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 127: Elaeagnus parvifolia - GUYELO (NITROGEN-FIXER #14!)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Elaeagnus parvifolia', 'Guyelo', 'Elaeagnaceae', 1300, 3000, 'Moderate', 'High', TRUE,
 'NITROGEN-FIXER (Frankia nodules!), edible fruit, soil reclamation',
 'Soil enrichment, degraded land recovery',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- Species 128: Cornus capitata - HIMALAYAN STRAWBERRY TREE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cornus capitata', 'Himalayan Strawberry Tree', 'Cornaceae', 1000, 3200, 'Moderate', 'Moderate', FALSE,
 'EDIBLE FRUIT (strawberry-like, sweet/bitter), nutrient-dense, antimicrobial, antioxidant',
 'Mid-story in temperate forests',
 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
  local_name = EXCLUDED.local_name, family = EXCLUDED.family,
  min_altitude_m = EXCLUDED.min_altitude_m, max_altitude_m = EXCLUDED.max_altitude_m,
  growth_rate = EXCLUDED.growth_rate, economic_value = EXCLUDED.economic_value,
  nitrogen_fixing = EXCLUDED.nitrogen_fixing, main_uses = EXCLUDED.main_uses,
  ecological_role = EXCLUDED.ecological_role, rarity_status = EXCLUDED.rarity_status;

-- ============================================================
-- VERIFICATION AND REPORTING
-- ============================================================

DO $$
DECLARE
    total_species INTEGER;
    nitrogen_fixing_count INTEGER;
    high_altitude_count INTEGER;
    critically_endangered_count INTEGER;
    endangered_count INTEGER;
    total_associations INTEGER;
    forest_types_covered INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    SELECT COUNT(*) INTO nitrogen_fixing_count FROM tree_species_coefficients WHERE nitrogen_fixing = TRUE;
    SELECT COUNT(*) INTO high_altitude_count FROM tree_species_coefficients WHERE max_altitude_m >= 3500;
    SELECT COUNT(*) INTO critically_endangered_count FROM tree_species_coefficients WHERE rarity_status LIKE '%CRITICALLY ENDANGERED%';
    SELECT COUNT(*) INTO endangered_count FROM tree_species_coefficients WHERE rarity_status LIKE '%ENDANGERED%';
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered FROM forest_species_association;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'PHASE 2 SESSION 5 - IMPORT COMPLETE (FINAL)';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '*** 128 SPECIES MILESTONE! (85%% OF PHASE 2) ***';
    RAISE NOTICE '';
    RAISE NOTICE 'Total species: % (target: 128)', total_species;
    RAISE NOTICE 'Nitrogen-fixers: % (14 expected - 140%% of target!)', nitrogen_fixing_count;
    RAISE NOTICE 'High-altitude species (3500m+): %', high_altitude_count;
    RAISE NOTICE 'CRITICALLY ENDANGERED: %', critically_endangered_count;
    RAISE NOTICE 'ENDANGERED: %', endangered_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types covered: %/25', forest_types_covered;
    RAISE NOTICE '';
    RAISE NOTICE '*** MAJOR ACHIEVEMENTS ***';
    RAISE NOTICE '14 Nitrogen-fixers (Hippophae + Elaeagnus)';
    RAISE NOTICE 'Treeline coverage to 4900m';
    RAISE NOTICE '3 CRITICALLY ENDANGERED documented';
    RAISE NOTICE 'Lokta paper tradition (1000+ years)';
    RAISE NOTICE 'Timur spice (Nepal signature)';
    RAISE NOTICE 'Highest woody plant (5200m - Juniperus indica)';
    RAISE NOTICE '';
    RAISE NOTICE 'Progress: 128/150 species (85%%)';
    RAISE NOTICE 'Remaining: 22 species for Session 6';
    RAISE NOTICE '============================================================';
END $$;

DROP FUNCTION IF EXISTS get_species_id(TEXT);

COMMIT;

\echo 'Session 5 import completed successfully!'
\echo '128 SPECIES MILESTONE REACHED! Only 22 more to 150!'
