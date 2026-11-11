export interface SymbolDef {
  id: string;
  emoji: string;
  labelEn: string;
  labelNp: string;
  group: string;
}

const SYMBOLS: SymbolDef[] = [
  // ===== Vegetation & Forest Products =====
  { id: 'timber', emoji: '🌲', labelEn: 'Timber tree', labelNp: 'रूख', group: 'Vegetation & Forest Products' },
  { id: 'sal', emoji: '🌳', labelEn: 'Sal tree (Shorea robusta)', labelNp: 'साल', group: 'Vegetation & Forest Products' },
  { id: 'pine', emoji: '🌲', labelEn: 'Pine tree', labelNp: 'सल्ला', group: 'Vegetation & Forest Products' },
  { id: 'firewood', emoji: '🪵', labelEn: 'Firewood', labelNp: 'दाउरा', group: 'Vegetation & Forest Products' },
  { id: 'fodder', emoji: '🌿', labelEn: 'Fodder grass', labelNp: 'घाँस', group: 'Vegetation & Forest Products' },
  { id: 'fodder_tree', emoji: '🌿', labelEn: 'Fodder tree (Badahar)', labelNp: 'बादहर', group: 'Vegetation & Forest Products' },
  { id: 'medicinal', emoji: '💊', labelEn: 'Medicinal plant', labelNp: 'जडिबुटी', group: 'Vegetation & Forest Products' },
  { id: 'litter', emoji: '🍂', labelEn: 'Leaf litter area', labelNp: 'मल', group: 'Vegetation & Forest Products' },
  { id: 'nursery', emoji: '🌱', labelEn: 'Nursery', labelNp: 'बिरुवा', group: 'Vegetation & Forest Products' },
  { id: 'grassland', emoji: '🌾', labelEn: 'Grassland', labelNp: 'घाँसे मैदान', group: 'Vegetation & Forest Products' },
  { id: 'bamboo', emoji: '🎋', labelEn: 'Bamboo clump', labelNp: 'बाँस', group: 'Vegetation & Forest Products' },
  { id: 'fruit_tree', emoji: '🍎', labelEn: 'Fruit tree', labelNp: 'फलफूल', group: 'Vegetation & Forest Products' },
  { id: 'flower', emoji: '🌸', labelEn: 'Flowering plant', labelNp: 'फूल', group: 'Vegetation & Forest Products' },
  { id: 'mushroom', emoji: '🍄', labelEn: 'Mushroom collection', labelNp: 'च्याउ', group: 'Vegetation & Forest Products' },
  { id: 'resin', emoji: '💧', labelEn: 'Resin tapping', labelNp: 'राल', group: 'Vegetation & Forest Products' },
  { id: 'tejpat', emoji: '🍃', labelEn: 'Tejpat (bay leaf)', labelNp: 'तेजपात', group: 'Vegetation & Forest Products' },
  { id: 'timur', emoji: '🌶️', labelEn: 'Timur (Sichuan pepper)', labelNp: 'टिमुर', group: 'Vegetation & Forest Products' },
  { id: 'amala', emoji: '🫐', labelEn: 'Amala (Indian gooseberry)', labelNp: 'आँला', group: 'Vegetation & Forest Products' },
  { id: 'harro', emoji: '🫒', labelEn: 'Harro (chebulic myrobalan)', labelNp: 'हर्रो', group: 'Vegetation & Forest Products' },
  { id: 'sisnoo', emoji: '🌱', labelEn: 'Sisnoo (stinging nettle)', labelNp: 'सिस्नू', group: 'Vegetation & Forest Products' },
  { id: 'alloe', emoji: '🌿', labelEn: 'Allo (Himalayan nettle)', labelNp: 'अल्लो', group: 'Vegetation & Forest Products' },
  { id: 'cane', emoji: '🪴', labelEn: 'Cane/Rattan', labelNp: 'बेत', group: 'Vegetation & Forest Products' },
  { id: 'seed_col', emoji: '🌰', labelEn: 'Seed collection site', labelNp: 'बीउ सङ्कलन', group: 'Vegetation & Forest Products' },
  { id: 'grass_cut', emoji: '🌾', labelEn: 'Grass cutting area', labelNp: 'घाँस काट्ने', group: 'Vegetation & Forest Products' },
  { id: 'broom', emoji: '🧹', labelEn: 'Broom grass (Amriso)', labelNp: 'आम्रिसो', group: 'Vegetation & Forest Products' },

  // ===== Wildlife =====
  { id: 'wildlife', emoji: '🦌', labelEn: 'Wildlife habitat', labelNp: 'बनपशु', group: 'Wildlife' },
  { id: 'bird', emoji: '🐦', labelEn: 'General bird', labelNp: 'चरा', group: 'Wildlife' },
  { id: 'peacock', emoji: '🦚', labelEn: 'Peafowl (Danfe)', labelNp: 'मयूर', group: 'Wildlife' },
  { id: 'tiger', emoji: '🐅', labelEn: 'Tiger', labelNp: 'बाघ', group: 'Wildlife' },
  { id: 'leopard', emoji: '🐆', labelEn: 'Leopard', labelNp: 'चितुवा', group: 'Wildlife' },
  { id: 'elephant', emoji: '🐘', labelEn: 'Elephant', labelNp: 'हात्ती', group: 'Wildlife' },
  { id: 'bear', emoji: '🐻', labelEn: 'Bear', labelNp: 'भालु', group: 'Wildlife' },
  { id: 'monkey', emoji: '🐒', labelEn: 'Monkey', labelNp: 'बाँदर', group: 'Wildlife' },
  { id: 'deer', emoji: '🦌', labelEn: 'Deer', labelNp: 'मृग', group: 'Wildlife' },
  { id: 'wild_boar', emoji: '🐗', labelEn: 'Wild boar', labelNp: 'बँदेल', group: 'Wildlife' },
  { id: 'fox', emoji: '🦊', labelEn: 'Fox', labelNp: 'स्याल', group: 'Wildlife' },
  { id: 'jackal', emoji: '🐺', labelEn: 'Jackal', labelNp: 'सियार', group: 'Wildlife' },
  { id: 'snake', emoji: '🐍', labelEn: 'Snake', labelNp: 'सर्प', group: 'Wildlife' },
  { id: 'squirrel', emoji: '🐿️', labelEn: 'Squirrel', labelNp: 'लखेप्रे', group: 'Wildlife' },
  { id: 'porcupine', emoji: '🦔', labelEn: 'Porcupine', labelNp: 'दुम्सी', group: 'Wildlife' },
  { id: 'rabbit', emoji: '🐇', labelEn: 'Rabbit', labelNp: 'खरायो', group: 'Wildlife' },
  { id: 'vulture', emoji: '🦅', labelEn: 'Vulture', labelNp: 'गिद्ध', group: 'Wildlife' },
  { id: 'parrot', emoji: '🦜', labelEn: 'Parrot', labelNp: 'सुगा', group: 'Wildlife' },
  { id: 'owl', emoji: '🦉', labelEn: 'Owl', labelNp: 'उल्लू', group: 'Wildlife' },
  { id: 'hornbill', emoji: '🐦', labelEn: 'Hornbill', labelNp: 'धनेश', group: 'Wildlife' },
  { id: 'pheasant', emoji: '🦃', labelEn: 'Pheasant', labelNp: 'कालिज', group: 'Wildlife' },
  { id: 'crane', emoji: '🦩', labelEn: 'Crane/Stork', labelNp: 'सारस', group: 'Wildlife' },
  { id: 'duck', emoji: '🦆', labelEn: 'Duck/Waterfowl', labelNp: 'हाँस', group: 'Wildlife' },
  { id: 'butterfly', emoji: '🦋', labelEn: 'Butterfly', labelNp: 'पुतली', group: 'Wildlife' },
  { id: 'bee', emoji: '🐝', labelEn: 'Beekeeping/hive', labelNp: 'मौरी', group: 'Wildlife' },
  { id: 'bat', emoji: '🦇', labelEn: 'Bat', labelNp: 'चमेरो', group: 'Wildlife' },
  { id: 'otter', emoji: '🦦', labelEn: 'Otter', labelNp: 'उद्र', group: 'Wildlife' },
  { id: 'turtle', emoji: '🐢', labelEn: 'Turtle', labelNp: 'कछुवा', group: 'Wildlife' },
  { id: 'fish', emoji: '🐟', labelEn: 'Fish/Aquatic', labelNp: 'माछा', group: 'Wildlife' },
  { id: 'frog', emoji: '🐸', labelEn: 'Frog/Amphibian', labelNp: 'भ्यागुतो', group: 'Wildlife' },
  { id: 'mongoose', emoji: '🐱', labelEn: 'Mongoose', labelNp: 'न्याउरी', group: 'Wildlife' },
  { id: 'civet', emoji: '🐱', labelEn: 'Civet cat', labelNp: 'मुसी', group: 'Wildlife' },

  // ===== Agriculture & Livestock =====
  { id: 'paddy', emoji: '🌾', labelEn: 'Paddy field', labelNp: 'धान खेत', group: 'Agriculture & Livestock' },
  { id: 'maize', emoji: '🌽', labelEn: 'Maize field', labelNp: 'मकै', group: 'Agriculture & Livestock' },
  { id: 'potato', emoji: '🥔', labelEn: 'Potato field', labelNp: 'आलु', group: 'Agriculture & Livestock' },
  { id: 'veg_garden', emoji: '🥬', labelEn: 'Vegetable garden', labelNp: 'तरकारी बगैंचा', group: 'Agriculture & Livestock' },
  { id: 'orchard', emoji: '🍊', labelEn: 'Citrus orchard', labelNp: 'सुन्तला बगैंचा', group: 'Agriculture & Livestock' },
  { id: 'banana', emoji: '🍌', labelEn: 'Banana grove', labelNp: 'केरा', group: 'Agriculture & Livestock' },
  { id: 'mango', emoji: '🥭', labelEn: 'Mango grove', labelNp: 'आँप', group: 'Agriculture & Livestock' },
  { id: 'cardamom', emoji: '🫚', labelEn: 'Cardamom (Alainchi)', labelNp: 'अलैंची', group: 'Agriculture & Livestock' },
  { id: 'ginger', emoji: '🫚', labelEn: 'Ginger', labelNp: 'अदुवा', group: 'Agriculture & Livestock' },
  { id: 'turmeric', emoji: '🟡', labelEn: 'Turmeric', labelNp: 'बेसार', group: 'Agriculture & Livestock' },
  { id: 'tea', emoji: '🍵', labelEn: 'Tea garden', labelNp: 'चिया बगैंचा', group: 'Agriculture & Livestock' },
  { id: 'coffee', emoji: '☕', labelEn: 'Coffee plantation', labelNp: 'कफी', group: 'Agriculture & Livestock' },
  { id: 'cattle', emoji: '🐄', labelEn: 'Cattle shed', labelNp: 'गोठ', group: 'Agriculture & Livestock' },
  { id: 'goat', emoji: '🐐', labelEn: 'Goat shed', labelNp: 'बाख्रा', group: 'Agriculture & Livestock' },
  { id: 'sheep', emoji: '🐑', labelEn: 'Sheep rearing', labelNp: 'भेडा', group: 'Agriculture & Livestock' },
  { id: 'pig', emoji: '🐖', labelEn: 'Pig farming', labelNp: 'बंगुर', group: 'Agriculture & Livestock' },
  { id: 'poultry', emoji: '🐔', labelEn: 'Poultry/chicken', labelNp: 'कुखुरा', group: 'Agriculture & Livestock' },
  { id: 'buffalo', emoji: '🐃', labelEn: 'Buffalo shed', labelNp: 'भैंसी', group: 'Agriculture & Livestock' },
  { id: 'fish_farm', emoji: '🐟', labelEn: 'Fish pond/fishery', labelNp: 'माछा पोखरी', group: 'Agriculture & Livestock' },
  { id: 'grazing', emoji: '🐐', labelEn: 'Grazing area', labelNp: 'चरान', group: 'Agriculture & Livestock' },
  { id: 'compost', emoji: '♻️', labelEn: 'Compost pit', labelNp: 'कम्पोस्ट खाल्डो', group: 'Agriculture & Livestock' },

  // ===== Water & Terrain =====
  { id: 'water', emoji: '💧', labelEn: 'Water source', labelNp: 'पानीको मुहान', group: 'Water & Terrain' },
  { id: 'river', emoji: '🌊', labelEn: 'River', labelNp: 'खोला', group: 'Water & Terrain' },
  { id: 'stream', emoji: '🏞️', labelEn: 'Stream', labelNp: 'खहरे', group: 'Water & Terrain' },
  { id: 'lake', emoji: '🏞️', labelEn: 'Lake/Pond', labelNp: 'ताल', group: 'Water & Terrain' },
  { id: 'tap', emoji: '⛲', labelEn: 'Tap/Water tank', labelNp: 'धारा', group: 'Water & Terrain' },
  { id: 'pond', emoji: '🪣', labelEn: 'Small pond', labelNp: 'पोखरी', group: 'Water & Terrain' },
  { id: 'well', emoji: '🪣', labelEn: 'Well', labelNp: 'इनार', group: 'Water & Terrain' },
  { id: 'spring', emoji: '💧', labelEn: 'Spring', labelNp: 'मूल', group: 'Water & Terrain' },
  { id: 'irrigation', emoji: '🚿', labelEn: 'Irrigation canal', labelNp: 'सिँचाइ नहर', group: 'Water & Terrain' },
  { id: 'waterfall', emoji: '🌊', labelEn: 'Waterfall', labelNp: 'झरना', group: 'Water & Terrain' },
  { id: 'reservoir', emoji: '🌊', labelEn: 'Reservoir', labelNp: 'जलाशय', group: 'Water & Terrain' },
  { id: 'dam', emoji: '🌊', labelEn: 'Dam/Check dam', labelNp: 'बाँध', group: 'Water & Terrain' },
  { id: 'bridge', emoji: '🌉', labelEn: 'Bridge', labelNp: 'पुल', group: 'Water & Terrain' },
  { id: 'mountain', emoji: '🏔️', labelEn: 'Mountain/Peak', labelNp: 'हिमाल', group: 'Water & Terrain' },
  { id: 'hill', emoji: '⛰️', labelEn: 'Hill/Ridge', labelNp: 'डाँडा', group: 'Water & Terrain' },
  { id: 'rock', emoji: '🗿', labelEn: 'Rock/Cliff', labelNp: 'चट्टान', group: 'Water & Terrain' },
  { id: 'cave', emoji: '🕳️', labelEn: 'Cave', labelNp: 'गुफा', group: 'Water & Terrain' },
  { id: 'landslide', emoji: '🌋', labelEn: 'Landslide area', labelNp: 'पहिरो', group: 'Water & Terrain' },
  { id: 'quarry', emoji: '⛏️', labelEn: 'Quarry site', labelNp: 'खानी', group: 'Water & Terrain' },
  { id: 'erosion', emoji: '🏜️', labelEn: 'Erosion prone', labelNp: 'क्षय', group: 'Water & Terrain' },
  { id: 'wetland', emoji: '🌾', labelEn: 'Wetland/Marsh', labelNp: 'सिमसार', group: 'Water & Terrain' },
  { id: 'floodplain', emoji: '🌊', labelEn: 'Floodplain', labelNp: 'बाढी मैदान', group: 'Water & Terrain' },

  // ===== Religious & Cultural =====
  { id: 'temple', emoji: '🛕', labelEn: 'Hindu temple', labelNp: 'मन्दिर', group: 'Religious & Cultural' },
  { id: 'mosque', emoji: '🕌', labelEn: 'Mosque', labelNp: 'मस्जिद', group: 'Religious & Cultural' },
  { id: 'church', emoji: '⛪', labelEn: 'Church', labelNp: 'गिर्जाघर', group: 'Religious & Cultural' },
  { id: 'monastery', emoji: '🏯', labelEn: 'Monastery/Gumba', labelNp: 'गुम्बा', group: 'Religious & Cultural' },
  { id: 'stupa', emoji: '💠', labelEn: 'Stupa/Chorten', labelNp: 'स्तुप', group: 'Religious & Cultural' },
  { id: 'shrine', emoji: '⛩️', labelEn: 'Shrine/Chautari', labelNp: 'चौतारी', group: 'Religious & Cultural' },
  { id: 'sacred_grove', emoji: '🌳', labelEn: 'Sacred grove', labelNp: 'पवित्र वन', group: 'Religious & Cultural' },
  { id: 'prayer_flag', emoji: '🏴', labelEn: 'Prayer flag', labelNp: 'ध्वजा', group: 'Religious & Cultural' },
  { id: 'cremation', emoji: '🪔', labelEn: 'Cremation ghat', labelNp: 'शव दाह', group: 'Religious & Cultural' },
  { id: 'graveyard', emoji: '🪦', labelEn: 'Cemetery/Graveyard', labelNp: 'चिहान', group: 'Religious & Cultural' },
  { id: 'pilgrimage', emoji: '🏔️', labelEn: 'Pilgrimage site', labelNp: 'तीर्थस्थल', group: 'Religious & Cultural' },
  { id: 'festival', emoji: '🎉', labelEn: 'Festival ground', labelNp: 'जात्रा स्थल', group: 'Religious & Cultural' },
  { id: 'meeting_hall', emoji: '🏛️', labelEn: 'Community hall', labelNp: 'सभाहल', group: 'Religious & Cultural' },
  { id: 'rest_house', emoji: '🏠', labelEn: 'Rest house', labelNp: 'बिसौनी', group: 'Religious & Cultural' },
  { id: 'heritage_tree', emoji: '🌳', labelEn: 'Heritage/pillar tree', labelNp: 'ऐतिहासिक रूख', group: 'Religious & Cultural' },
  { id: 'monument', emoji: '🗽', labelEn: 'Monument/Memorial', labelNp: 'स्मारक', group: 'Religious & Cultural' },
  { id: 'meditation', emoji: '🧘', labelEn: 'Meditation area', labelNp: 'ध्यान स्थल', group: 'Religious & Cultural' },

  // ===== Infrastructure & Buildings =====
  { id: 'settlement', emoji: '🏘️', labelEn: 'Settlement', labelNp: 'बस्ती', group: 'Infrastructure & Buildings' },
  { id: 'house', emoji: '🏠', labelEn: 'House', labelNp: 'घर', group: 'Infrastructure & Buildings' },
  { id: 'school', emoji: '🏫', labelEn: 'School', labelNp: 'विद्यालय', group: 'Infrastructure & Buildings' },
  { id: 'health_post', emoji: '🏥', labelEn: 'Health post', labelNp: 'स्वास्थ्य चौकी', group: 'Infrastructure & Buildings' },
  { id: 'office', emoji: '🏢', labelEn: 'CFUG committee office', labelNp: 'कार्यालय', group: 'Infrastructure & Buildings' },
  { id: 'dfo_office', emoji: '🏛️', labelEn: 'DFO/Ranger office', labelNp: 'डीएफओ कार्यालय', group: 'Infrastructure & Buildings' },
  { id: 'guard_post', emoji: '🛡️', labelEn: 'Forest guard post', labelNp: 'रक्षक', group: 'Infrastructure & Buildings' },
  { id: 'police_post', emoji: '👮', labelEn: 'Police post', labelNp: 'प्रहरी चौकी', group: 'Infrastructure & Buildings' },
  { id: 'check_post', emoji: '🚧', labelEn: 'Check post', labelNp: 'जाँच चौकी', group: 'Infrastructure & Buildings' },
  { id: 'library', emoji: '📚', labelEn: 'Library', labelNp: 'पुस्तकालय', group: 'Infrastructure & Buildings' },
  { id: 'market', emoji: '🛒', labelEn: 'Market/Shop', labelNp: 'बजार', group: 'Infrastructure & Buildings' },
  { id: 'camp', emoji: '🏕️', labelEn: 'Field camp', labelNp: 'शिविर', group: 'Infrastructure & Buildings' },
  { id: 'road', emoji: '🛣️', labelEn: 'Road', labelNp: 'सडक', group: 'Infrastructure & Buildings' },
  { id: 'trail', emoji: '🛤️', labelEn: 'Trail/Footpath', labelNp: 'गोरेटो बाटो', group: 'Infrastructure & Buildings' },
  { id: 'bus_stop', emoji: '🚏', labelEn: 'Bus stop', labelNp: 'बस स्टप', group: 'Infrastructure & Buildings' },
  { id: 'parking', emoji: '🅿️', labelEn: 'Parking area', labelNp: 'पार्किङ', group: 'Infrastructure & Buildings' },
  { id: 'gate', emoji: '🚪', labelEn: 'Forest gate/entrance', labelNp: 'गेट', group: 'Infrastructure & Buildings' },
  { id: 'fence', emoji: '🧱', labelEn: 'Fence/Barrier', labelNp: 'बार', group: 'Infrastructure & Buildings' },
  { id: 'electric', emoji: '⚡', labelEn: 'Electric pole/line', labelNp: 'बिजुली', group: 'Infrastructure & Buildings' },
  { id: 'solar', emoji: '☀️', labelEn: 'Solar panel', labelNp: 'सौर्य', group: 'Infrastructure & Buildings' },
  { id: 'biogas', emoji: '🟢', labelEn: 'Biogas plant', labelNp: 'वायोग्यास', group: 'Infrastructure & Buildings' },
  { id: 'toilet', emoji: '🚻', labelEn: 'Toilet', labelNp: 'शौचालय', group: 'Infrastructure & Buildings' },
  { id: 'drinking_water', emoji: '🚰', labelEn: 'Drinking water station', labelNp: 'खानेपानी', group: 'Infrastructure & Buildings' },
  { id: 'info_center', emoji: 'ℹ️', labelEn: 'Information center', labelNp: 'सूचना केन्द्र', group: 'Infrastructure & Buildings' },
  { id: 'playground', emoji: '⚽', labelEn: 'Playground', labelNp: 'खेल मैदान', group: 'Infrastructure & Buildings' },

  // ===== Management & Monitoring =====
  { id: 'boundary', emoji: '⛰️', labelEn: 'Boundary pillar', labelNp: 'सिमाना स्तम्भ', group: 'Management & Monitoring' },
  { id: 'boundary_marker', emoji: '📍', labelEn: 'Boundary marker', labelNp: 'सिमा चिन्ह', group: 'Management & Monitoring' },
  { id: 'block_marker', emoji: '🔲', labelEn: 'Block boundary', labelNp: 'ब्लक सिमा', group: 'Management & Monitoring' },
  { id: 'comp_marker', emoji: '🔳', labelEn: 'Compartment boundary', labelNp: 'कम्पार्टमेन्ट सिमा', group: 'Management & Monitoring' },
  { id: 'fire_line', emoji: '🚧', labelEn: 'Fire line', labelNp: 'डाँगो रेखा', group: 'Management & Monitoring' },
  { id: 'fire_incident', emoji: '🔥', labelEn: 'Fire incident point', labelNp: 'डाँगो', group: 'Management & Monitoring' },
  { id: 'fire_risk', emoji: '⚠️', labelEn: 'Fire risk zone', labelNp: 'आगलागी जोखिम', group: 'Management & Monitoring' },
  { id: 'sample_plot', emoji: '🔬', labelEn: 'Sample plot (FRI)', labelNp: 'नमुना प्लट', group: 'Management & Monitoring' },
  { id: 'research_plot', emoji: '📐', labelEn: 'Research plot', labelNp: 'अनुसन्धान प्लट', group: 'Management & Monitoring' },
  { id: 'monitor_plot', emoji: '📊', labelEn: 'Monitoring plot', labelNp: 'अनुगमन प्लट', group: 'Management & Monitoring' },
  { id: 'transect', emoji: '📏', labelEn: 'Transect line', labelNp: 'ट्रान्जेक्ट रेखा', group: 'Management & Monitoring' },
  { id: 'camera_trap', emoji: '📷', labelEn: 'Camera trap point', labelNp: 'क्यामरा जाल', group: 'Management & Monitoring' },
  { id: 'waterhole', emoji: '💧', labelEn: 'Waterhole', labelNp: 'पानी खाल्डो', group: 'Management & Monitoring' },
  { id: 'salt_lick', emoji: '🧂', labelEn: 'Salt lick', labelNp: 'नुन चाट्ने', group: 'Management & Monitoring' },
  { id: 'plantation', emoji: '🌲', labelEn: 'Plantation site', labelNp: 'वृक्षारोपण', group: 'Management & Monitoring' },
  { id: 'enrichment', emoji: '🌱', labelEn: 'Enrichment planting', labelNp: 'गुणस्तर सुधार', group: 'Management & Monitoring' },
  { id: 'restoration', emoji: '♻️', labelEn: 'Restoration area', labelNp: 'पुनर्स्थापना', group: 'Management & Monitoring' },
  { id: 'conservation', emoji: '🛡️', labelEn: 'Conservation area', labelNp: 'संरक्षण क्षेत्र', group: 'Management & Monitoring' },
  { id: 'carbon_plot', emoji: '🌍', labelEn: 'Carbon monitoring plot', labelNp: 'कार्बन अनुगमन', group: 'Management & Monitoring' },
  { id: 'nursery_site', emoji: '🌱', labelEn: 'Nursery site', labelNp: 'बिरुवा उत्पादन', group: 'Management & Monitoring' },
  { id: 'seed_orchard', emoji: '🌰', labelEn: 'Seed orchard/mother tree', labelNp: 'आम रूख', group: 'Management & Monitoring' },
  { id: 'watchtower', emoji: '🗼', labelEn: 'Watchtower', labelNp: 'हेरालो', group: 'Management & Monitoring' },
  { id: 'observation', emoji: '👁️', labelEn: 'Observation point', labelNp: 'अवलोकन बिन्दु', group: 'Management & Monitoring' },

  // ===== Hazards & Disturbances =====
  { id: 'flood', emoji: '🌊', labelEn: 'Flood affected', labelNp: 'बाढी', group: 'Hazards & Disturbances' },
  { id: 'erosion_site', emoji: '🏜️', labelEn: 'Soil erosion', labelNp: 'माटो क्षय', group: 'Hazards & Disturbances' },
  { id: 'wind_damage', emoji: '💨', labelEn: 'Wind storm damage', labelNp: 'हुरी', group: 'Hazards & Disturbances' },
  { id: 'hail', emoji: '🧊', labelEn: 'Hail damage', labelNp: 'असिना', group: 'Hazards & Disturbances' },
  { id: 'pest', emoji: '🐛', labelEn: 'Pest infestation', labelNp: 'किरा संक्रमण', group: 'Hazards & Disturbances' },
  { id: 'drought', emoji: '🏜️', labelEn: 'Drought affected', labelNp: 'खडेरी', group: 'Hazards & Disturbances' },
  { id: 'invasive', emoji: '🌿', labelEn: 'Invasive species', labelNp: 'आक्रान्ता प्रजाति', group: 'Hazards & Disturbances' },
  { id: 'encroach', emoji: '🚫', labelEn: 'Encroachment', labelNp: 'अतिक्रमण', group: 'Hazards & Disturbances' },
  { id: 'poaching', emoji: '🔫', labelEn: 'Poaching/Illegal logging', labelNp: 'सिकार/चोरी', group: 'Hazards & Disturbances' },
  { id: 'avalanche', emoji: '🏔️', labelEn: 'Avalanche prone', labelNp: 'हिउँ पहिरो', group: 'Hazards & Disturbances' },
  { id: 'littering', emoji: '🗑️', labelEn: 'Dumping/littering', labelNp: 'फोहोर फाल्ने', group: 'Hazards & Disturbances' },

  // ===== Tourism & Recreation =====
  { id: 'camping', emoji: '⛺', labelEn: 'Camping site', labelNp: 'पाल टाँग्ने', group: 'Tourism & Recreation' },
  { id: 'picnic', emoji: '🧺', labelEn: 'Picnic spot', labelNp: 'खाजा स्थल', group: 'Tourism & Recreation' },
  { id: 'viewpoint', emoji: '🎯', labelEn: 'Viewpoint', labelNp: 'दृश्य स्थान', group: 'Tourism & Recreation' },
  { id: 'bird_hide', emoji: '🕊️', labelEn: 'Bird hide', labelNp: 'चरा हेर्ने', group: 'Tourism & Recreation' },
  { id: 'nature_trail', emoji: '🥾', labelEn: 'Nature trail', labelNp: 'प्रकृति पथ', group: 'Tourism & Recreation' },
  { id: 'entrance', emoji: '🚪', labelEn: 'Tourist entrance', labelNp: 'प्रवेशद्वार', group: 'Tourism & Recreation' },
  { id: 'toilet_public', emoji: '🚻', labelEn: 'Public toilet', labelNp: 'सार्वजनिक शौचालय', group: 'Tourism & Recreation' },
  { id: 'souvenir', emoji: '🎁', labelEn: 'Souvenir/shop', labelNp: 'स्मृति पसल', group: 'Tourism & Recreation' },
  { id: 'trash_bin', emoji: '🗑️', labelEn: 'Trash bin', labelNp: 'फोहोर ड्रम', group: 'Tourism & Recreation' },
  { id: 'bench', emoji: '🪑', labelEn: 'Rest bench', labelNp: 'बेन्च', group: 'Tourism & Recreation' },
  { id: 'shelter', emoji: '🏠', labelEn: 'Shelter/Pavilion', labelNp: 'आश्रय', group: 'Tourism & Recreation' },
  { id: 'signboard', emoji: '📋', labelEn: 'Signboard/Map', labelNp: 'संकेतपाटी', group: 'Tourism & Recreation' },
  { id: 'bbq', emoji: '🔥', labelEn: 'BBQ/Fire pit', labelNp: 'आगो स्थल', group: 'Tourism & Recreation' },
  { id: 'swimming', emoji: '🏊', labelEn: 'Swimming area', labelNp: 'पौडी स्थल', group: 'Tourism & Recreation' },
];

export const SYMBOL_BY_ID: Record<string, SymbolDef> = {};
for (const s of SYMBOLS) {
  SYMBOL_BY_ID[s.id] = s;
}

export const SYMBOL_GROUPS: { group: string; symbols: SymbolDef[] }[] = [];
const groupMap: Record<string, SymbolDef[]> = {};
for (const s of SYMBOLS) {
  if (!groupMap[s.group]) groupMap[s.group] = [];
  groupMap[s.group].push(s);
}
for (const [group, symbols] of Object.entries(groupMap)) {
  SYMBOL_GROUPS.push({ group, symbols });
}

/** Column names that should be treated as symbol source */
export const SYMBOL_SOURCE_COLUMNS = new Set([
  'remark', 'remarks', 'Remarks', 'REMARKS',
  'description', 'Description', 'DESCRIPTION',
  'symbol', 'Symbol', 'SYMBOL',
  'type', 'Type', 'TYPE',
  'category', 'Category', 'CATEGORY',
  'note', 'Note', 'NOTES', 'notes',
  'class', 'Class', 'CLASS',
  'kind', 'Kind', 'KIND',
]);

/** Detect which column in feature properties is the symbol source */
export function detectSymbolColumn(features: { properties?: Record<string, unknown> }[]): string | null {
  if (!features || features.length === 0) return null;
  const propKeys = new Set<string>();
  for (const f of features) {
    if (f.properties) Object.keys(f.properties).forEach((k) => propKeys.add(k));
  }
  for (const k of propKeys) {
    if (SYMBOL_SOURCE_COLUMNS.has(k)) return k;
  }
  return null;
}

function _normalize(s: string): string {
  return s.toLowerCase().replace(/[\s\-_/]+/g, ' ').trim();
}

function _bigramSimilarity(a: string, b: string): number {
  const bigrams = (s: string): Set<string> => {
    const set = new Set<string>();
    for (let i = 0; i < s.length - 1; i++) set.add(s.substring(i, i + 2));
    return set;
  };
  const ba = bigrams(a);
  const bb = bigrams(b);
  if (ba.size === 0 && bb.size === 0) return 1;
  let intersection = 0;
  for (const bg of ba) if (bb.has(bg)) intersection++;
  return (2 * intersection) / (ba.size + bb.size);
}

/** Fuzzy-match a text value against all symbol labels.
 *  Returns the best matching symbol id, or null if no good match (threshold 0.35). */
export function fuzzyMatchSymbol(text: string | undefined | null): string | null {
  if (!text) return null;
  const normalized = _normalize(text);
  if (!normalized) return null;

  let bestScore = 0;
  let bestId: string | null = null;

  for (const sym of SYMBOLS) {
    const candidates = [sym.id, sym.labelEn, sym.labelNp];
    for (const candidate of candidates) {
      const normCandidate = _normalize(candidate);
      if (!normCandidate) continue;

      if (normalized === normCandidate) return sym.id;

      if (normCandidate.includes(normalized) || normalized.includes(normCandidate)) {
        const lenRatio = Math.min(normalized.length, normCandidate.length) / Math.max(normalized.length, normCandidate.length);
        const score = 0.6 + 0.4 * lenRatio;
        if (score > bestScore) { bestScore = score; bestId = sym.id; }
        continue;
      }

      const score = _bigramSimilarity(normalized, normCandidate);
      if (score > bestScore) { bestScore = score; bestId = sym.id; }
    }
  }

  if (bestScore >= 0.35) return bestId;
  return null;
}

/** Get the emoji for a feature.
 *  Priority:
 *    1. Explicit `symbol` property
 *    2. Fuzzy match against a detected symbol-source column (remark, description, type, category, etc.)
 *    3. Fallback: fuzzy match ANY string property value */
export function getFeatureEmoji(feature: { properties?: Record<string, unknown> } | undefined | null): string {
  if (!feature || !feature.properties) return '📍';

  const explicitSymbol = feature.properties.symbol as string | undefined;
  if (explicitSymbol) {
    const def = SYMBOL_BY_ID[explicitSymbol];
    if (def) return def.emoji;
  }

  const sourceCol = detectSymbolColumn([feature]);
  if (sourceCol) {
    const val = feature.properties[sourceCol] as string | undefined;
    const matchedId = fuzzyMatchSymbol(val);
    if (matchedId) {
      const def = SYMBOL_BY_ID[matchedId];
      if (def) return def.emoji;
    }
  }

  // Fallback: try every string property value against fuzzy matching
  for (const val of Object.values(feature.properties)) {
    if (typeof val === 'string' && val.length < 80) {
      const matchedId = fuzzyMatchSymbol(val);
      if (matchedId) {
        const def = SYMBOL_BY_ID[matchedId];
        if (def) return def.emoji;
      }
    }
  }

  return '📍';
}

export function getSymbolEmoji(symbolId: string | undefined | null): string {
  if (!symbolId) return '📍';
  const def = SYMBOL_BY_ID[symbolId];
  return def ? def.emoji : '📍';
}

export function getSymbolDef(symbolId: string | undefined | null): SymbolDef | undefined {
  if (!symbolId) return undefined;
  return SYMBOL_BY_ID[symbolId];
}

export default SYMBOLS;

/** Count symbols per group */
export function getSymbolStats(): { total: number; groups: Record<string, number> } {
  const groups: Record<string, number> = {};
  for (const s of SYMBOLS) {
    groups[s.group] = (groups[s.group] || 0) + 1;
  }
  return { total: SYMBOLS.length, groups };
}
