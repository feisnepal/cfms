"""The designated NTFP (non-timber forest product) species list: Forest Regulations 2079 (वन नियमावली, २०७९), Schedule-7 (अनुसूची-७).

"जडीबुटीको नाम र मूल्य दर" -- the herbs and other forest products the regulation names, with the price rate per kilogram. Pages 120-130
of the Nepal Law Commission text (www.lawcommission.gov.np); transcribed 2026-10-17 and checked against the PDF's text layer by
``tests/test_ntfp_schedule7.py`` (every scientific name below must occur in the published text).

Eight groups (the regulation's own): क roots and tubers, ख bark, ग leaf and stem, घ flower and fluff, ङ fruit and seed, च whole plant,
छ gum, resin and incense. A species may appear in several groups (a different part is harvested), with a different price.

Each row: ``(group, serial, nepali_name, scientific_name_as_printed, price_npr, unit)``. ``price_npr`` is per kilogram unless ``unit`` says
otherwise. An empty scientific name means the regulation gives none (the product is not a single named plant: wild mushroom, honey,
lac, rock exudate, "orchid", lichen, or a name left blank in the table).

Notes printed under the schedule: (1) for a species brought illegally from outside that is not found in Nepal, the price is set at five
times the revenue of the country concerned; (2) the price is the same whether the herb is green or dry.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .species_synonyms import canonical_key

SOURCE = "वन नियमावली, २०७९ अनुसूची-७"
SOURCE_EN = "Forest Regulations 2079, Schedule-7"

GROUPS: Dict[str, Tuple[str, str]] = {
    "क": ("जरा तथा गानो जाति", "Roots and tubers"),
    "ख": ("बोक्रा जाति", "Bark"),
    "ग": ("पात/डाँठ जाति", "Leaf and stem"),
    "घ": ("फूल र भुवा जाति", "Flower and fluff"),
    "ङ": ("फल र बीज जाति", "Fruit and seed"),
    "च": ("बिरुवा जाति", "Whole plant"),
    "छ": ("गम, रेजिन, लोहावन जाति", "Gum, resin and incense"),
}

ROWS: List[Tuple[str, int, str, str, int, str]] = [
    # ── क  जरा तथा गानो जाति ────────────────────────────────────────────────
    ("क", 1, "अतिस", "Aconitum heterophylloides/Acotinum heterophyllum/Delphinium himalayai", 15, "kg"),
    ("क", 2, "अनन्तमूल", "Hemidesmus indicus", 10, "kg"),
    ("क", 3, "अश्वगन्धा", "Withania somnifera", 25, "kg"),
    ("क", 4, "असारेफूल/धोविनी", "Mussaenda spp.", 8, "kg"),
    ("क", 5, "आरडिक्स", "Rdix tinosporae", 10, "kg"),
    ("क", 6, "इन्द्रेणी", "Citrullus colocynthis/Trichosanthes wallichiana", 10, "kg"),
    ("क", 7, "उन्यू", "Dryopteris cochleata, Huperzia javanica", 10, "kg"),
    ("क", 8, "ऐंसेलु", "Rubus ellipticus", 15, "kg"),
    ("क", 9, "कचुर", "Curcuma aromatica", 5, "kg"),
    ("क", 10, "कपुरकचरी", "Hedychium spicatum", 2, "kg"),
    ("क", 11, "काकोली/वन लसुन", "Fritillaria cirrhosa", 5, "kg"),
    ("क", 12, "कामराज, मयुरखुट्टे", "Helminthostachys zeylanica", 6, "kg"),
    ("क", 13, "कालो निगुरो", "Dryoathyrium boryanum", 2, "kg"),
    ("क", 14, "कुकुरडाइनो", "Smilax spp.", 10, "kg"),
    ("क", 15, "कुकुरतरुल, वनतरुल, भ्याकुर", "Dioscorea spp.", 15, "kg"),
    ("क", 16, "कुचिला", "Strychnos nux-vomica", 7, "kg"),
    ("क", 17, "कुट्की", "Neopicrorhiza scrophulariiflora", 40, "kg"),
    ("क", 18, "कुथ", "Saussurea costus", 5, "kg"),
    ("क", 19, "कुरिलो/सतावरी", "Asparagus spp.", 5, "kg"),
    ("क", 20, "क्रेमास्तरा", "Cremastra appendiculata", 10, "kg"),
    ("क", 21, "खसखस/उशीर/भेटिभेर", "Chrysopogon zizanioides, Vetiveria zizanioides", 10, "kg"),
    ("क", 22, "खिरौले (मेदा)/खिरौला/सेतकचिनी", "Polygonatum spp.", 25, "kg"),
    ("क", 23, "गन्धाईनो", "Angelica glauca", 5, "kg"),
    ("क", 24, "गन्नाइनो", "Pleurospermum spp.", 3, "kg"),
    ("क", 25, "गुजरगानो/निमी लहरा", "Stephania spp.", 7, "kg"),
    ("क", 26, "गुर्जो/गुडुची/गुड्की", "Tinospora sinensis", 5, "kg"),
    ("क", 27, "गोकुलधुप", "Commiphora mukul", 5, "kg"),
    ("क", 28, "गोलकाँक्री", "Solena amplexicaulis", 5, "kg"),
    ("क", 29, "चुत्रो/दारुहल्दी", "Berberis spp.", 8, "kg"),
    ("क", 30, "जटामसी", "Nardostachys jatamansi", 75, "kg"),
    ("क", 31, "जमानेमान्द्रो", "Mahonia napaulensis", 5, "kg"),
    ("क", 32, "जेठीमधु (येष्ठीमधु)", "Glycyrrhiza glabra", 15, "kg"),
    ("क", 33, "जोरपाते बेली गानो", "Psammosilene tunicoides", 15, "kg"),
    ("क", 34, "झुलो", "Gerbera macrophyla", 5, "kg"),
    ("क", 35, "टुकीफूल", "Taraxacum spp.", 5, "kg"),
    ("क", 36, "ठूलो/बुढो ओखती", "Astilbe rivularis", 7, "kg"),
    ("क", 37, "डाइसोमा", "Dysosma versipellis", 10, "kg"),
    ("क", 38, "नक्कली सतुवा", "Trillidium govanianum", 40, "kg"),
    ("क", 39, "नागरमोथे, मोथे", "Cyperus spp.", 5, "kg"),
    ("क", 40, "नारु", "Silene spp.", 5, "kg"),
    ("क", 41, "निरमसी/निरबिषी", "Delphinium denudatum/Aconitum palmatum/Aconitum orochryseum", 60, "kg"),
    ("क", 42, "पदमचाल/अमलवेद", "Rheum austral, Rheum emodi", 10, "kg"),
    ("क", 43, "पदमपुष्कर/निनाइजडि", "Iris decora", 5, "kg"),
    ("क", 44, "पाखनवेद/पाषाणभेद", "Bergenia pacumbis/Bergenia ciliate", 7, "kg"),
    ("क", 45, "पाँच औंले", "Dactylorhiza hatagirea", 500, "piece"),
    ("क", 46, "पिपला/पिपली", "Piper longum", 10, "kg"),
    ("क", 47, "बज्रदन्ती", "Potentilla spp.", 5, "kg"),
    ("क", 48, "बायजडि", "Hippolytia dolichophylla", 5, "kg"),
    ("क", 49, "बोझो", "Acorus calamus", 5, "kg"),
    ("क", 50, "भूतकेश", "Selinum wallichianum", 5, "kg"),
    ("क", 51, "ममिरा", "Parnassia nubicola", 70, "kg"),
    ("क", 52, "मुसली (कालो)", "Curculigo orchioides", 10, "kg"),
    ("क", 53, "मुसली (सेतो)", "Chlorophytum spp.", 10, "kg"),
    ("क", 54, "रास्गरी/भूइसरो", "Roscoea spp.", 5, "kg"),
    ("क", 55, "लघुपत्र", "Podophyllum hexandrum", 7, "kg"),
    ("क", 56, "वन प्याज", "Allium spp.", 15, "kg"),
    ("क", 57, "वन हलेदो", "Curcuma angustifolia", 5, "kg"),
    ("क", 58, "वनमुला", "Dipsacus inermis", 15, "kg"),
    ("क", 59, "वनलसुन", "Allium wallichii", 30, "kg"),
    ("क", 60, "वनलसुन/खिरौंले", "Lilium nepalense", 30, "kg"),
    ("क", 61, "वाँको/सर्पको मकै", "Arisaema spp.", 2, "kg"),
    ("क", 62, "बाटुल्पाते", "Cissampelos pareira", 2, "kg"),
    ("क", 63, "विदारीकन्द", "Pueraria phaseoloides", 2, "kg"),
    ("क", 64, "विलौने", "Maesa chisia", 5, "kg"),
    ("क", 65, "विष, विषमा", "Aconitum spp.", 10, "kg"),
    ("क", 66, "विषफेज", "Polypodiodes amoena", 10, "kg"),
    ("क", 67, "वेत लौरी", "Cheilocostus speciosus", 5, "kg"),
    ("क", 68, "शटी/गाइसरो", "Hedychium spicatum", 5, "kg"),
    ("क", 69, "सतुवा", "Paris polyphylla", 50, "kg"),
    ("क", 70, "सर्पगन्धा/चाँदमरुवा", "Rauvolfia serpentina", 50, "kg"),
    ("क", 71, "सातगाँठे", "Panax pseudoginseng", 50, "kg"),
    ("क", 72, "सिस्नु", "Urtica spp.", 2, "kg"),
    ("क", 73, "सुगन्धवाल", "Valeriana jatamansi", 25, "kg"),
    ("क", 74, "सुनडाँठिगानो", "Gastrodia elata", 10, "kg"),
    # ── ख  बोक्रा जाति ──────────────────────────────────────────────────────
    ("ख", 1, "अँगेरी", "Lyonia ovalifolia", 5, "kg"),
    ("ख", 2, "अर्जुन", "Terminalia arjuna", 10, "kg"),
    ("ख", 3, "अशोक", "Saraca asoca", 2, "kg"),
    ("ख", 4, "ओखर", "Juglans regia", 100, "kg"),
    ("ख", 5, "काफल", "Myrica esculenta", 100, "kg"),
    ("ख", 6, "कुटमिरो/काल्चुरी", "Litsea monopetala", 5, "kg"),
    ("ख", 7, "कोइरालो/कचनार", "Bauhinia variegata", 5, "kg"),
    ("ख", 8, "खमारी", "Gmelina arborea", 15, "kg"),
    ("ख", 9, "गिनेरी", "Premna barbata", 15, "kg"),
    ("ख", 10, "चुत्रो/दारुहल्दी", "Berberis spp.", 10, "kg"),
    ("ख", 11, "छतिवन", "Alstonia scholaris/A.neriifolia", 10, "kg"),
    ("ख", 12, "जमानेमान्द्रो/केशरी/जमानेचुत्रो", "Mohania nepaulensis", 5, "kg"),
    ("ख", 13, "टटेलो/टोटला", "Oroxylum indicum", 5, "kg"),
    ("ख", 14, "टाँकी", "Bauhinia purpurea", 5, "kg"),
    ("ख", 15, "दार/दारगिठी", "Boehmaria rugulosa", 15, "kg"),
    ("ख", 16, "धूपी", "Juniperus spp.", 25, "kg"),
    ("ख", 17, "निम", "Azadirachta indica", 5, "kg"),
    ("ख", 18, "नेपाली दालचिनी/सिन्कौली", "Cinnamomum tamala", 10, "kg"),
    ("ख", 19, "पलास", "Butea monosperma", 25, "kg"),
    ("ख", 20, "पातली", "Stereospemum suaveolenis", 10, "kg"),
    ("ख", 21, "पावन/काठे काउलो", "Machilus duthiei", 30, "kg"),
    ("ख", 22, "पैंयु", "Prunus cerasoides", 10, "kg"),
    ("ख", 23, "बकाइनो", "Melia azedarach", 2, "kg"),
    ("ख", 24, "बबुल", "Acacia nilotica", 10, "kg"),
    ("ख", 25, "भोजपत्र", "Betula utilis", 20, "kg"),
    ("ख", 26, "भोर्ला/मालु", "Bauhinia vahlii", 2, "kg"),
    ("ख", 27, "लोध", "Symplocos racemosa", 10, "kg"),
    ("ख", 28, "वनखिर्रो/कुटज/इन्द्र जौ", "Holarrhena pubescens/Holarrhena antidecentrica", 5, "kg"),
    ("ख", 29, "वनसुडो", "Viburnum spp.", 10, "kg"),
    ("ख", 30, "विलौने", "Maesa chisia", 10, "kg"),
    ("ख", 31, "सल्ला", "Pinus spp.", 2, "kg"),
    ("ख", 32, "सिप्लीकान", "Creatave nurvala", 15, "kg"),
    ("ख", 33, "सेतो काउलो", "Persea odoratissima", 30, "kg"),
    # ── ग  पात/डाँठ जाति ────────────────────────────────────────────────────
    ("ग", 1, "अखेनो, घोडेमच्चो", "Thymus linearis", 3, "kg"),
    ("ग", 2, "अदुवाघाँस/हातकटुवा", "Carex spp.", 1, "kg"),
    ("ग", 3, "अमलवेद/पदमचाल चुल्ठे अमिलो/काराज चुल्ठी", "Rheum australe", 5, "kg"),
    ("ग", 4, "असुरो/अडुस/वासक", "Justicia adhatoda", 1, "kg"),
    ("ग", 5, "उन्यू", "Dryopteris cochleata", 3, "kg"),
    ("ग", 6, "ऐसेलु", "Rubus ellipticus", 15, "kg"),
    ("ग", 7, "करिपत्ता", "Murraya koenigii", 2, "kg"),
    ("ग", 8, "गुडमार", "Gymnema sylvestre", 5, "kg"),
    ("ग", 9, "गुर्जोलहरा/गुडुची", "Tinospora sinensis", 5, "kg"),
    ("ग", 10, "गेन्टियना", "Gentiana spp.", 10, "kg"),
    ("ग", 11, "घिउकुमारी", "Aloe vera", 5, "kg"),
    ("ग", 12, "चरि अमिलो", "Oxalis corniculata", 5, "kg"),
    ("ग", 13, "चुत्रो", "Berberis spp.", 8, "kg"),
    ("ग", 14, "चुम्लानी", "Skimmia laureola", 1, "kg"),
    ("ग", 15, "जगर/जिगर/वन सुपारी", "Caryota urens", 2, "kg"),
    ("ग", 16, "जेठीमधु (येष्टीमधु)", "Glycyzrrhiza glabra", 15, "kg"),
    ("ग", 17, "जोरपाते वेली गानो", "Psammosilene tunicoides", 15, "kg"),
    ("ग", 18, "टोकला, टोटला", "", 1, "kg"),
    ("ग", 19, "ठिगुरेसल्ला/ठिङ्ग्रेसल्ला", "Tsuga dumosa", 2, "kg"),
    ("ग", 20, "डालेचुक", "Hippophae spp.", 2, "kg"),
    ("ग", 21, "तालिसपत्र", "Abies spectabilis", 5, "kg"),
    ("ग", 22, "तितेपाती", "Artemisia spp.", 2, "kg"),
    ("ग", 23, "तेजपात", "Cinnamomum tamala", 3, "kg"),
    ("ग", 24, "दुधेलहरा/सरीवा", "Cryptolepis dubia", 2, "kg"),
    ("ग", 25, "धसिंग्रे/मच्छिनो/पटपटे", "Gaultheria fragrantissima", 2, "kg"),
    ("ग", 26, "धूपी", "Juniperus spp.", 2, "kg"),
    ("ग", 27, "निरगुण्डी", "Pitax nirgundi", 2, "kg"),
    ("ग", 28, "निसोद", "Opurculina turpethum", 10, "kg"),
    ("ग", 29, "नुनढिकी", "Osyris lanceolata", 1, "kg"),
    ("ग", 30, "पानी अमला", "Nephrolepis cordifolia", 3, "kg"),
    ("ग", 31, "पामारोजा", "Cymbopogon martini", 1, "kg"),
    ("ग", 32, "बोहोरी", "Cordia spp.", 5, "kg"),
    ("ग", 33, "भिडेत्ती", "Elcholtzia fruticosa", 5, "kg"),
    ("ग", 34, "मजिठो", "Rubia manjith", 7, "kg"),
    ("ग", 35, "मलाटा", "Macaranga spp.", 1, "kg"),
    ("ग", 36, "मसला", "Eucalyptus spp.", 1, "kg"),
    ("ग", 37, "मेकोनोप्सिस", "Meconopsis spp.", 10, "kg"),
    ("ग", 38, "लेमनग्रास", "Cymbopogon flexuosus", 1, "kg"),
    ("ग", 39, "लौठसल्ला", "Taxus spp.", 50, "kg"),
    ("ग", 40, "विजयसाल", "Pterocarpus marsupium", 10, "kg"),
    ("ग", 41, "सिकाकाई", "Acacia rugata", 3, "kg"),
    ("ग", 42, "सिट्रोनेला", "Cymbopogon winterianus", 1, "kg"),
    ("ग", 43, "सिस्नु", "Urtica spp.", 1, "kg"),
    ("ग", 44, "सुनपाती", "Rhododendron anthopogon", 7, "kg"),
    ("ग", 45, "सोमलता", "Ephedra spp.", 5, "kg"),
    ("ग", 46, "हिंगुवा/चियापाते", "Camellia kissi", 1, "kg"),
    # ── घ  फूल र भुवा जाति ──────────────────────────────────────────────────
    ("घ", 1, "असुरो/अडुस/वासक", "Justicia adhatoda", 1, "kg"),
    ("घ", 2, "आँकको भूवा", "Calotropis spp.", 4, "kg"),
    ("घ", 3, "उत्तिसको फूल", "Alnus nepalensis", 3, "kg"),
    ("घ", 4, "कमलगट्टा", "Nelumbo nucifera", 2, "kg"),
    ("घ", 5, "कोइरालो/कचनार", "Bauhinia variegata", 1, "kg"),
    ("घ", 6, "गुराँस/चिमाल", "Rhododendron spp.", 5, "kg"),
    ("घ", 7, "टटेलोफूल/टोटला", "Oroxylum indicum", 3, "kg"),
    ("घ", 8, "टुकीफूल", "Taraxacum spp.", 7, "kg"),
    ("घ", 9, "धँयरो", "Woodfordia fruticosa", 1, "kg"),
    ("घ", 10, "नागेश्वर/नारेश्वर", "Mesua ferrea", 5, "kg"),
    ("घ", 11, "पदमपुष्कर/निनाइजडि", "Iris decora", 3, "kg"),
    ("घ", 12, "बुकीफूल", "Anaphalis spp./Pseudognaphalium spp.", 1, "kg"),
    ("घ", 13, "मौवा (तराई)", "Madhuca latifolia", 5, "kg"),
    ("घ", 14, "मौवा (पहाडी)", "Engelhardtia spicata", 2, "kg"),
    ("घ", 15, "रुखकमल", "Magnolia grandiflora", 25, "kg"),
    ("घ", 16, "सिमलको फूल", "Bombax ceiba", 3, "kg"),
    ("घ", 17, "सिमलको भूवा", "Bombax ceiba", 4, "kg"),
    ("घ", 18, "सुनपाती", "Rhododendron anthopogon", 5, "kg"),
    # ── ङ  फल र बीज जाति ────────────────────────────────────────────────────
    ("ङ", 1, "अंडेर", "Ricinus communis", 2, "kg"),
    ("ङ", 2, "अपमार्ग/दतिवन", "Achyranthtu aspera", 2, "kg"),
    ("ङ", 3, "अमला", "Phyllanthus emblica", 2, "kg"),
    ("ङ", 4, "असना/साज", "Terminalia tomentosa", 2, "kg"),
    ("ङ", 5, "इन्द्रजौ", "Holarrhena pubescens", 1, "kg"),
    ("ङ", 6, "इन्द्रेणी", "Citrullus colosynthis/Trichosanthes wallichiana", 8, "kg"),
    ("ङ", 7, "उत्तिस", "Alnus nepalensis", 50, "kg"),
    ("ङ", 8, "ओखर फल", "Juglans regia", 10, "kg"),
    ("ङ", 9, "ओखर फलको बोक्रा", "Juglans regia", 5, "kg"),
    ("ङ", 10, "औलेलौठ (जैतुन)", "Olea spp.", 10, "kg"),
    ("ङ", 11, "कञ्जा", "Pongamia pinnata", 3, "kg"),
    ("ङ", 12, "कड्जा/करञ्जा", "Caesalpinia bondus", 3, "kg"),
    ("ङ", 13, "कन्टकारी", "Solanum xanthocarpum", 1, "kg"),
    ("ङ", 14, "कस्मर्द", "Cassia occidentalis", 5, "kg"),
    ("ङ", 15, "काइयो फल/टकाली", "Pavetta tomentosa", 5, "kg"),
    ("ङ", 16, "काउसो", "Mucuna pruriens", 2, "kg"),
    ("ङ", 17, "काक्नासा", "Martynia annua", 2, "kg"),
    ("ङ", 18, "कालादाना", "Ipomoea spp.", 7, "kg"),
    ("ङ", 19, "कालीकाठको दाना", "Myrsine semiserrata", 5, "kg"),
    ("ङ", 20, "कुचिला", "Strychnos nux-vomica", 2, "kg"),
    ("ङ", 21, "कुसुम", "Schleichera oleosa", 2, "kg"),
    ("ङ", 22, "कोइरालो/कचनार", "Bauhinia variegata", 1, "kg"),
    ("ङ", 23, "कौडिल्ला", "Coix lachryma (jobi)", 2, "kg"),
    ("ङ", 24, "खमारी", "Gmelina arborea", 5, "kg"),
    ("ङ", 25, "खयर", "Acacia catechu", 25, "kg"),
    ("ङ", 26, "खोटेसल्लाको बीउ", "Pinus roxburghii", 200, "kg"),
    ("ङ", 27, "गोखुकाँडा", "Tribulus terrestris", 2, "kg"),
    ("ङ", 28, "चम्पावती/चाँप", "Magnolia champaca", 50, "kg"),
    ("ङ", 29, "चिउरी", "Diploknema butyracea", 3, "kg"),
    ("ङ", 30, "चिलाउनेको गेडा", "Schima wallichii", 1, "kg"),
    ("ङ", 31, "जङ्गली आरु (चुली)", "Prunus davidiana", 5, "kg"),
    ("ङ", 32, "जङ्गली गुलाब", "Rosa sericea", 5, "kg"),
    ("ङ", 33, "जङ्गली जीरा (वन जिरा)", "Carum carvi", 5, "kg"),
    ("ङ", 34, "जङ्गली ज्वानो", "Apium graveolens", 5, "kg"),
    ("ङ", 35, "जामुन", "Syzygium cumini", 1, "kg"),
    ("ङ", 36, "टाप्रे", "Senna tora", 1, "kg"),
    ("ङ", 37, "टिमुर", "Zanthoxylum armatum", 10, "kg"),
    ("ङ", 38, "डालेचुक", "Hippophae spp.", 5, "kg"),
    ("ङ", 39, "ढटेलो", "Prinsepia utilis", 5, "kg"),
    ("ङ", 40, "ढालेकटुस", "Castanopsis indica", 1, "kg"),
    ("ङ", 41, "तिगेडी", "", 10, "kg"),
    ("ङ", 42, "थाकलको फल", "Phoenix spp.", 2, "kg"),
    ("ङ", 43, "देवदार", "Cedrus deodara", 100, "kg"),
    ("ङ", 44, "धतुरो", "Datura spp.", 2, "kg"),
    ("ङ", 45, "धूपीको गेडा", "Juniperus spp.", 3, "kg"),
    ("ङ", 46, "नागवेली", "Lycopodium japonicum", 50, "kg"),
    ("ङ", 47, "नागेश्वर/नारेश्वर", "Mesua ferrea", 5, "kg"),
    ("ङ", 48, "निमको बीउ", "Azadirachta indica", 1, "kg"),
    ("ङ", 49, "पलाँस", "Butea monosperma", 5, "kg"),
    ("ङ", 50, "पाङ्ग्रा/लेक पाङ्ग्रा", "Entada phaseoloides/Aesculus indica", 5, "kg"),
    ("ङ", 51, "पानी अमला", "Nephrolepis cordifolia", 3, "kg"),
    ("ङ", 52, "पिपला/पिपली", "Piper longum", 10, "kg"),
    ("ङ", 53, "पियारको फल", "Buchanania latifolia", 10, "kg"),
    ("ङ", 54, "पैंयुको फल", "Prunus cerasoides", 2, "kg"),
    ("ङ", 55, "बकाइनो", "Melia azedarach", 1, "kg"),
    ("ङ", 56, "बयर", "Ziziphus mauritiana", 2, "kg"),
    ("ङ", 57, "बर्रो", "Terminalia bellirica", 2, "kg"),
    ("ङ", 58, "बाक्ची", "Psoralia corylifolia", 5, "kg"),
    ("ङ", 59, "बीरेन्द्रफूलको फल", "Jacaranda mimosifolia", 5, "kg"),
    ("ङ", 60, "बेत", "Calamus spp.", 5, "kg"),
    ("ङ", 61, "बेल", "Aegle marmelos", 2, "kg"),
    ("ङ", 62, "भलायो", "Semecarpus anacardium", 3, "kg"),
    ("ङ", 63, "भूजेत्रो/भूलेत्रो", "Butea minor", 5, "kg"),
    ("ङ", 64, "मरोरफली", "Helicteris isora", 2, "kg"),
    ("ङ", 65, "माल्कागुनो", "Celastrus paniculatus", 5, "kg"),
    ("ङ", 66, "मैनाफल", "Randiadum etorum", 2, "kg"),
    ("ङ", 67, "मौवा (तराई)", "Madhuca latifolia", 3, "kg"),
    ("ङ", 68, "मौवा (पहाडी)", "Engelhardtia spicata", 3, "kg"),
    ("ङ", 69, "रतीगेडी/लालगेडी", "Abrus precatorius", 5, "kg"),
    ("ङ", 70, "राजवृक्ष", "Cassia fistula", 2, "kg"),
    ("ङ", 71, "रामफल/आटी/सरिफा", "Annona reticulata", 2, "kg"),
    ("ङ", 72, "रिट्ठा", "Sapindus mukorossi", 3, "kg"),
    ("ङ", 73, "रुखकमलको फल", "Magnolia grandiflora", 25, "kg"),
    ("ङ", 74, "रुद्राक्ष, भद्राक्ष", "Elaeocarpus sphaericus", 10, "kg"),
    ("ङ", 75, "रोहिणी/सिंदुरे", "Mallotus philippensis", 5, "kg"),
    ("ङ", 76, "लताकस्तुरी", "Abelmoschus moschatus", 5, "kg"),
    ("ङ", 77, "लप्सी", "Choerospondias axillaris", 3, "kg"),
    ("ङ", 78, "लहरे उन्यू", "Lygodium Japonicum", 5, "kg"),
    ("ङ", 79, "वन करेला", "Herpetospermum pedunculosum", 5, "kg"),
    ("ङ", 80, "शिवलिङ्गी", "Bryonia laciniosa", 5, "kg"),
    ("ङ", 81, "सजिवन", "Jatropha curcas", 2, "kg"),
    ("ङ", 82, "सतिसाल", "Dalbergia latifolia", 30, "kg"),
    ("ङ", 83, "सालको बीउ", "Shorea robusta", 10, "kg"),
    ("ङ", 84, "सिकाकाई/रसुल्ला", "Acacia concinna", 4, "kg"),
    ("ङ", 85, "सिमलको फल", "Bombax ceiba", 3, "kg"),
    ("ङ", 86, "सिल्टीमुर", "Lindera neesiana", 2, "kg"),
    ("ङ", 87, "सिसौको कोसा", "Dalbergia sissoo", 15, "kg"),
    ("ङ", 88, "सीताफल", "Annona squamosa", 2, "kg"),
    ("ङ", 89, "सुगन्धकोकिला/मलायागेडी", "Cinnamomum glanduliferum/Cinnamomum tenuipile", 15, "kg"),
    ("ङ", 90, "हरो", "Terminalia chebula", 2, "kg"),
    # ── च  बिरुवा जाति ──────────────────────────────────────────────────────
    ("च", 1, "अपमार्ग/दतिवन", "Achyranthtu aspera", 2, "kg"),
    ("च", 2, "अस्थिसमहर्क", "Cissus quadrangularis", 5, "kg"),
    ("च", 3, "आकाशवेली", "Cuscuta reflexa", 2, "kg"),
    ("च", 4, "एक्लेवीर", "Lobelia pyramidalis", 5, "kg"),
    ("च", 5, "काँस", "Sacchrum spontaneum", 2, "kg"),
    ("च", 6, "कालमेग", "Andrographis paniculata", 7, "kg"),
    ("च", 7, "काली कुइया", "", 5, "kg"),
    ("च", 8, "कालो दुवो", "", 2, "kg"),
    ("च", 9, "कुमकुम", "Didymocarpus cinereus", 5, "kg"),
    ("च", 10, "गाईतिहारे", "Inula cappa", 5, "kg"),
    ("च", 11, "गुच्ची च्याउ", "Morchella spp.", 500, "kg"),
    ("च", 12, "गेन्टियना", "Gentiana spp.", 10, "kg"),
    ("च", 13, "गोरखमुण्डी", "Sphaernthus indica", 2, "kg"),
    ("च", 14, "गोल्को", "", 5, "kg"),
    ("च", 15, "घोडताप्रे/ब्राम्ही", "Centella asiatica", 2, "kg"),
    ("च", 16, "चावा", "Piper chaba", 10, "kg"),
    ("च", 17, "चिराइतो", "Swertia spp.", 15, "kg"),
    ("च", 18, "जलब्रामी", "Bacopa monnieri", 2, "kg"),
    ("च", 19, "झ्याउ", "Lichen", 50, "kg"),
    ("च", 20, "टाप्रे", "Senna tora", 1, "kg"),
    ("च", 21, "तितेपाती", "Artemisia spp.", 1, "kg"),
    ("च", 22, "द्रोणपुष्पी", "Leucas cephalotes", 2, "kg"),
    ("च", 23, "नागवेली", "Lycopodium japonicum", 15, "kg"),
    ("च", 24, "पिप्लामुल", "", 2, "kg"),
    ("च", 25, "पुडाइनो", "", 5, "kg"),
    ("च", 26, "पुदिना", "Mentha spp.", 2, "kg"),
    ("च", 27, "पुनर्नवा", "Boerhavia diffusa", 8, "kg"),
    ("च", 28, "प्रिस्नपर्णि", "Uraria picta", 2, "kg"),
    ("च", 29, "भूमि अमला", "Phyllanthus niruri", 5, "kg"),
    ("च", 30, "भूईकस्तुरी", "Chenopodium ambrosioides", 15, "kg"),
    ("च", 31, "भृंगराज", "Eclipta prostrata", 5, "kg"),
    ("च", 32, "मेकोनोपसिस", "Meconopsis spp.", 10, "kg"),
    ("च", 33, "यार्सागुम्बा (यार्चगुम्बू)", "Ophiocordyceps spp.", 31000, "kg"),
    ("च", 34, "रगतसिंगे", "", 5, "kg"),
    ("च", 35, "रातो च्याउ", "Ganoderma lucidum", 50, "kg"),
    ("च", 36, "लज्जावती", "Mimosa pudica", 2, "kg"),
    ("च", 37, "वनालु/कस्तुरी/लताकस्तुरी", "Abelmoschus moschatus", 15, "kg"),
    ("च", 38, "विहिकाँडा", "Solanum nigrmum", 2, "kg"),
    ("च", 39, "शंखपुष्पी", "Evolvulusal sinoides", 5, "kg"),
    ("च", 40, "साधारण च्याउ", "Wild mushroom", 10, "kg"),
    ("च", 41, "सालपर्णि", "Uraria picta", 2, "kg"),
    ("च", 42, "सिमझार", "Rotala rotundifolia", 10, "kg"),
    ("च", 43, "सिलाजिनेला", "Selaginella spp.", 1, "kg"),
    ("च", 44, "सुनाखरी/सुनगाभा/जीवन्ती/गामाडोल (पाँचऔले बाहेक)", "Orchid", 500, "kg"),
    ("च", 45, "हडचुर", "Viscum album , V. articulatum", 3, "kg"),
    ("च", 46, "हलहले", "Rumex nepalensis", 3, "kg"),
    ("च", 47, "हिमाली गुलाब", "", 7, "kg"),
    # ── छ  गम, रेजिन, लोहावन जाति ───────────────────────────────────────────
    ("छ", 1, "अगरउड (काठ)", "Aquilaria spp.", 50, "kg"),
    ("छ", 2, "काकरसिंगी", "Insect gall on Pistacia integerrima", 20, "kg"),
    ("छ", 3, "मइन", "Bee wax", 5, "kg"),
    ("छ", 4, "मह (जङ्गली)", "Bee honey", 20, "kg"),
    ("छ", 5, "लाहा/लोहवान", "Lac gum", 40, "kg"),
    ("छ", 6, "शिलाजित", "Rock exudate/Asphaltum", 50, "kg"),
    ("छ", 7, "सल्लाको खोटो", "Pinus spp.", 12, "kg"),
    ("छ", 8, "सालधुप", "Shorea robusta", 15, "kg"),
    ("छ", 9, "सिमल", "Bombax ceiba", 15, "kg"),
    ("छ", 10, "हिङ्ग", "Ferula asafoetida", 50, "kg"),
]

# The regulation prints several scientific names with a spelling slip (the Law Commission text has them too). They are kept as printed in
# ``ROWS`` and corrected here, only for matching a recorded species to the list. Genuine synonyms are left alone.
ACCEPTED_SPELLING: Dict[str, str] = {
    "gerbera macrophyla": "gerbera macrophylla",
    "stereospemum suaveolenis": "stereospermum suaveolens",
    "stereospermum suaveolenis": "stereospermum suaveolens",
    "achyranthtu aspera": "achyranthes aspera",
    "achyranthu aspera": "achyranthes aspera",
    "pitax nirgundi": "vitex negundo",
    "trillidium govanianum": "trillium govanianum",
    "boehmaria rugulosa": "boehmeria rugulosa",
    "mohania nepaulensis": "mahonia napaulensis",
    "creatave nurvala": "crateva nurvala",
    "opurculina turpethum": "operculina turpethum",
    "glycyzrrhiza glabra": "glycyrrhiza glabra",
    "randiadum etorum": "randia dumetorum",
    "sphaernthus indica": "sphaeranthus indicus",
    "evolvulusal sinoides": "evolvulus alsinoides",
    "solanum nigrmum": "solanum nigrum",
    "elcholtzia fruticosa": "elsholtzia fruticosa",
    "rheum austral": "rheum australe",
    "psoralia corylifolia": "psoralea corylifolia",
    "helicteris isora": "helicteres isora",
    "caesalpinia bondus": "caesalpinia bonduc",
    "citrullus colosynthis": "citrullus colocynthis",
    "dryoathyrium boryanum": "deparia boryana",
    "acotinum heterophyllum": "aconitum heterophyllum",
    "aconitum heterophylloides": "aconitum heterophyllum",
    "bergenia pacumbis": "bergenia pacumbis",
    "bergenia ciliate": "bergenia ciliata",
}

# printed names that are not a single plant, so they cannot be matched to a recorded species
_NOT_A_PLANT = {"orchid", "lichen", "wild mushroom", "bee wax", "bee honey", "lac gum", "rock exudate/asphaltum", "rdix tinosporae"}
_CLEAN = re.compile(r"[^a-z ]")


def _norm(name: str) -> str:
    """Lower case letters and single spaces; a hyphen is dropped, not turned into a space (``nux-vomica`` -> ``nuxvomica``), so a
    hyphenated epithet stays one word."""
    return re.sub(r"\s+", " ", _CLEAN.sub(" ", name.lower().replace("-", ""))).strip()


def scientific_names(printed: str) -> List[str]:
    """The Latin names in a printed scientific-name cell, one per entry (``A b/C d, E f`` -> three), normalised to lower case with
    ``spp.`` kept as the genus alone. An abbreviated genus (``V. articulatum``) takes the genus before it. A cell that is not a
    plant (honey, lac, rock exudate, "orchid") or is blank gives ``[]``."""
    text = (printed or "").strip()
    if not text or text.lower() in _NOT_A_PLANT:
        return []
    text = re.sub(r"^insect gall on ", "", text, flags=re.I)
    out: List[str] = []
    last_genus = ""
    for part in re.split(r"[/,]", text):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"^([A-Z])[.](?=[A-Za-z])", lambda m: m.group(1) + ". ", part)  # "A.neriifolia" -> "A. neriifolia"
        words = part.split()
        if len(words) >= 2 and re.fullmatch(r"[A-Z]\.?", words[0]) and last_genus:
            words[0] = last_genus
        genus = words[0]
        if len(words) == 1 or words[1].lower().rstrip(".") == "spp":
            name = _norm(genus)
        else:
            name = _norm(" ".join(words[:2]))
        if name:
            out.append(ACCEPTED_SPELLING.get(name, name))
        last_genus = genus
    return list(dict.fromkeys(out))


# ── matching a recorded species to the list ────────────────────────────────────────────────────────────────────────────────

def _key(scientific_name: str) -> List[str]:
    """Genus and epithet of a recorded name, lower case, without author, variety or ``spp.``: ``Juglans regia L.`` -> [juglans, regia]."""
    return canonical_key(scientific_name or "").split()  # a synonym is read as its canonical name (core/species_synonyms.py)


_INDEX: Dict[str, List[dict]] = {}


def _build_index() -> Dict[str, List[dict]]:
    index: Dict[str, List[dict]] = {}
    for group, serial, nepali, printed, price, unit in ROWS:
        for name in scientific_names(printed):
            index.setdefault(name, []).append({
                "group": group, "serial": serial, "nepali": nepali, "price": price, "unit": unit,
                "group_ne": GROUPS[group][0], "group_en": GROUPS[group][1],
            })
    return index


def designated_entries(scientific_name: str) -> List[dict]:
    """The Schedule-7 entries a recorded species falls under, or ``[]``.

    The rule is deliberately lopsided, as for the policy species list: a *species* on the list (``Juglans regia``) matches only that
    species; a *genus* on the list (``Pinus spp.``) matches every species of the genus, and a record kept only at genus level
    (``Pinus spp.``) matches only a genus entry. Otherwise a genus test applied to species-level entries would sweep in unrelated
    species."""
    global _INDEX
    if not _INDEX:
        _INDEX = _build_index()
    key = _key(scientific_name)
    if not key:
        return []
    specific: List[dict] = _INDEX.get(" ".join(key), []) if len(key) == 2 else []
    # for a part the list prices by species, that price governs; the genus-wide price is only for the parts it does not name
    named = {e["group"] for e in specific}
    return specific + [e for e in _INDEX.get(key[0], []) if e["group"] not in named]


def designated_names() -> List[str]:
    """Every normalised Latin name on the list (``genus epithet`` or ``genus``), sorted."""
    global _INDEX
    if not _INDEX:
        _INDEX = _build_index()
    return sorted(_INDEX)
