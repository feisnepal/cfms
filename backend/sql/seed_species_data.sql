-- Seed tree species coefficients data
-- 25 Nepal tree species with allometric equations

INSERT INTO public.tree_species_coefficients (
    scientific_name, local_name,
    a, b, c, a1, b1, s, m, bg,
    aliases, max_dbh_cm, max_height_m,
    typical_hd_ratio_min, typical_hd_ratio_max,
    is_active
) VALUES
('Abies spp', 'Thingre Salla', -2.4453, 1.722, 1.0757, 5.4433, -2.6902, 0.436, 0.372, 0.355,
 ARRAY['Abies', 'Fir', 'thingre salla', 'thingre'], 150, 45, 80, 120, TRUE),

('Acacia catechu', 'Khayar', -2.3256, 1.6476, 1.0552, 5.4401, -2.491, 0.443, 0.511, 0.71,
 ARRAY['Acacia', 'khayar', 'Khadir'], 80, 25, 60, 100, TRUE),

('Adina cardifolia', 'Karma', -2.5626, 1.8598, 0.8783, 5.4681, -2.491, 0.443, 0.511, 0.71,
 ARRAY['Adina', 'karma', 'Haldu'], 100, 30, 60, 100, TRUE),

('Albizia spp', 'Siris', -2.4284, 1.7609, 0.9662, 4.4031, -2.2094, 0.443, 0.511, 0.71,
 ARRAY['Albizia', 'siris', 'Sirish'], 100, 30, 60, 100, TRUE),

('Alnus nepalensis', 'Uttis', -2.7761, 1.9006, 0.9428, 6.019, -2.7271, 0.803, 1.226, 1.51,
 ARRAY['Alnus', 'uttis', 'Utis'], 80, 25, 60, 100, TRUE),

('Anogeissus latifolia', 'Banjhi', -2.272, 1.7499, 0.9174, 4.9502, -2.3353, 0.443, 0.511, 0.71,
 ARRAY['Anogeissus', 'banjhi'], 100, 30, 60, 100, TRUE),

('Bombax ceiba', 'Simal', -2.3856, 1.7414, 1.0063, 4.5554, -2.3009, 0.443, 0.511, 0.71,
 ARRAY['Bombax', 'simal', 'Simul'], 150, 35, 60, 100, TRUE),

('Cedrela toona', 'Tooni', -2.1832, 1.8679, 0.7569, 4.9705, -2.3436, 0.443, 0.511, 0.71,
 ARRAY['Cedrela', 'tooni', 'Toon'], 120, 35, 60, 100, TRUE),

('Dalbergia sissoo', 'Sissoo', -2.1959, 1.6567, 0.9899, 4.358, -2.1559, 0.684, 0.684, 0.684,
 ARRAY['Dalbergia', 'sissoo', 'Sisau', 'Shisham'], 120, 30, 60, 100, TRUE),

('Eugenia Jambolana', 'Jamun', -2.5693, 1.8816, 0.8498, 5.1749, -2.3636, 0.443, 0.511, 0.71,
 ARRAY['Eugenia', 'jamun', 'Jamun'], 80, 25, 60, 100, TRUE),

('Hymenodictyon excelsum', 'Bhudkul', -2.585, 1.9437, 0.7902, 5.5572, -2.496, 0.443, 0.511, 0.71,
 ARRAY['Hymenodictyon', 'bhudkul'], 100, 30, 60, 100, TRUE),

('Lagerstroemia parviflora', 'Botdhayero', -2.3411, 1.7246, 0.9702, 5.3349, -2.4428, 0.443, 0.511, 0.71,
 ARRAY['Lagerstroemia', 'botdhayero', 'Asna'], 100, 30, 60, 100, TRUE),

('Michelia champaca', 'Chanp', -2.0152, 1.8555, 0.763, 3.3499, -2.0161, 0.443, 0.511, 0.71,
 ARRAY['Michelia', 'chanp', 'Champ', 'Champak'], 100, 30, 60, 100, TRUE),

('Pinus roxburghii', 'Khote Salla', -2.977, 1.9235, 1.0019, 6.2696, -2.8252, 0.189, 0.256, 0.3,
 ARRAY['Pinus roxburghii', 'khote salla', 'Chir Pine'], 120, 45, 80, 120, TRUE),

('Pinus wallichiana', 'Gobre Salla', -2.8195, 1.725, 1.1623, 5.7216, -2.6788, 0.683, 0.488, 0.41,
 ARRAY['Pinus wallichiana', 'gobre salla', 'Blue Pine'], 150, 50, 80, 120, TRUE),

('Quercus spp', 'Kharsu', -2.36, 1.968, 0.7496, 4.8511, -2.4494, 0.747, 0.96, 1.06,
 ARRAY['Quercus', 'kharsu', 'Oak'], 120, 30, 60, 100, TRUE),

('Schima wallichii', 'Chilaune', -2.7385, 1.8155, 1.0072, 7.4617, -3.0676, 0.52, 0.186, 0.168,
 ARRAY['Schima', 'chilaune', 'Chilam'], 100, 30, 60, 100, TRUE),

('Shorea robusta', 'Sal', -2.4554, 1.9026, 0.8352, 5.2026, -2.4788, 0.055, 0.341, 0.357,
 ARRAY['Shorea', 'sal', 'Sakhu'], 150, 35, 60, 100, TRUE),

('Terminalia alata', 'Saj', -2.4616, 1.8497, 0.88, 4.5968, -2.2305, 0.443, 0.511, 0.71,
 ARRAY['Terminalia alata', 'saj', 'Asna'], 100, 30, 60, 100, TRUE),

('Trewia nudiflora', 'Gamhari', -2.4585, 1.8043, 0.922, 5.3475, -2.4774, 0.443, 0.511, 0.71,
 ARRAY['Trewia', 'gamhari'], 100, 30, 60, 100, TRUE),

('Tsuga spp', 'Dhupi Salla', -2.5293, 1.7815, 1.0369, 5.2774, -2.6483, 0.443, 0.511, 0.71,
 ARRAY['Tsuga', 'dhupi salla', 'Hemlock'], 120, 40, 80, 120, TRUE),

('Terai spp', 'Terai Spp', -2.3993, 1.7836, 0.9546, 4.8991, -2.3406, 0.443, 0.511, 0.71,
 ARRAY['terai', 'Terai mixed'], 120, 35, 60, 100, TRUE),

('Hill spp', 'Hill spp', -2.3204, 1.8507, 0.8223, 5.5323, -2.4815, 0.443, 0.511, 0.71,
 ARRAY['hill', 'Hill mixed'], 100, 30, 60, 100, TRUE),

('Coniferious', NULL, NULL, NULL, NULL, NULL, NULL, 0.436, 0.372, 0.355,
 ARRAY['conifer', 'coniferous'], 150, 50, 80, 120, TRUE),

('Broadleaved', NULL, NULL, NULL, NULL, NULL, NULL, 0.443, 0.511, 0.71,
 ARRAY['broadleaf', 'broad leaved'], 150, 40, 60, 100, TRUE);

SELECT COUNT(*) as species_count FROM public.tree_species_coefficients;
