"""
Section templates for report generation
Defines structure and metadata for each report section
"""

REPORT_SECTIONS = {
    1: {
        "title_ne": "परिचय",
        "title_en": "Introduction",
        "requires_data": ["basic_info"],
        "auto_generate": True,
    },
    2: {
        "title_ne": "सामुदायिक वन र समूहको भौगोलिक अवस्थिति",
        "title_en": "Geographical Location of Community Forest and Group",
        "requires_data": ["basic_info", "boundary", "raster_analysis"],
        "auto_generate": True,
        "includes_maps": ["boundary_map"],
    },
    3: {
        "title_ne": "वनको किसिम मुख्य प्रजाति",
        "title_en": "Forest Type and Main Species",
        "requires_data": ["species", "raster_analysis"],
        "auto_generate": True,
        "includes_charts": ["species_pie", "forest_type_pie"],
    },
    4: {
        "title_ne": "वन पैदावारको माग र आपूर्तिको अवस्था",
        "title_en": "Demand and Supply Status of Forest Products",
        "requires_data": ["households", "inventory", "raster_analysis"],
        "auto_generate": True,
    },
    5: {
        "title_ne": "समूहको आर्थिक तथा सामाजिक अवस्था",
        "title_en": "Economic and Social Status of the Group",
        "requires_data": ["households", "committees"],
        "auto_generate": True,
    },
    6: {
        "title_ne": "विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा",
        "title_en": "Review of Previous Forest Management Plans",
        "requires_data": [],
        "auto_generate": False,
        "needs_user_input": True,
    },
    7: {
        "title_ne": "वनस्रोत सर्वेक्षण, विश्लेषण, वन संवर्द्धन प्रणाली तथा व्यवस्थापन",
        "title_en": "Forest Resource Survey, Analysis, Conservation System and Management",
        "subsections": {
            "क": {
                "title_ne": "भू-उपयोग",
                "title_en": "Land Use",
                "requires_data": ["raster_analysis", "basic_info"],
                "auto_generate": True,
                "includes_charts": ["slope_pie", "canopy_pie", "landcover_pie"],
                "includes_maps": ["slope_map", "canopy_map"],
            },
            "ख": {
                "title_ne": "ब्लक/कम्पार्टमेण्ट विभाजन, ब्लक/कम्पार्टमेण्ट अनुसारको वनको मौज्दात",
                "title_en": "Block/Compartment Division and Forest Stock by Block",
                "requires_data": ["blocks", "inventory", "raster_analysis"],
                "auto_generate": True,
                "includes_maps": ["block_map"],
                "includes_charts": ["block_area_bar"],
            },
            "ग": {
                "title_ne": "वन संवर्द्धन प्रणाली छनोटको आधार",
                "title_en": "Basis for Selection of Forest Conservation System",
                "requires_data": ["species", "raster_analysis"],
                "auto_generate": True,
            },
            "घ": {
                "title_ne": "वन संवर्द्धन प्रणाली तथा क्रियाकलाप, कार्यान्वयन समय तालिका, वार्षिक स्वीकार्य कटान",
                "title_en": "Forest Conservation System, Activities, Implementation Schedule, Annual Allowable Cut",
                "requires_data": ["sampling", "activities", "species"],
                "auto_generate": True,
                "includes_maps": ["sampling_map"],
            },
            "ङ": {
                "title_ne": "वन पैदावार सङ्कलन चक्र तथा पुनरोत्पादन तरिका",
                "title_en": "Forest Product Collection Cycle and Reproduction Methods",
                "requires_data": ["species", "inventory"],
                "auto_generate": True,
            },
        },
    },
    8: {
        "title_ne": "वन पैदावार उत्पादन र आपूर्तिको तरिका",
        "title_en": "Methods of Forest Product Production and Supply",
        "subsections": {
            "क": {
                "title_ne": "वन पैदावार कटान, सङ्कलन तथा घाटगद्दी गर्ने समय तालिका",
                "title_en": "Schedule for Cutting, Collection and Depot of Forest Products",
                "requires_data": ["inventory", "activities"],
                "auto_generate": True,
            },
            "ख": {
                "title_ne": "वन पैदावारको मूल्य निर्धारण",
                "title_en": "Pricing of Forest Products",
                "requires_data": ["inventory"],
                "auto_generate": True,
            },
            "ग": {
                "title_ne": "घाटगद्दीबाट वन पैदावार बिक्री वितरण व्यवस्थापन र नियन्त्रण तरिका",
                "title_en": "Sale, Distribution, Management and Control of Forest Products from Depot",
                "requires_data": [],
                "auto_generate": False,
                "needs_user_input": True,
            },
        },
    },
    9: {
        "title_ne": "संरक्षण तथा संवर्द्धन कार्य व्यवस्थापन",
        "title_en": "Conservation and Promotion Work Management",
        "subsections": {
            "क": {
                "title_ne": "वन डढेलो तथा चरिचरन नियन्त्रण",
                "title_en": "Forest Fire and Grazing Control",
                "requires_data": ["raster_analysis"],
                "auto_generate": True,
            },
            "ख": {
                "title_ne": "एकीकृत रोग किरा तथा मिचाहा प्रजाति नियन्त्रण",
                "title_en": "Integrated Pest and Invasive Species Control",
                "requires_data": ["biodiversity"],
                "auto_generate": True,
            },
            "ग": {
                "title_ne": "वन अतिक्रमण, चोरी शिकार तथा कटानी नियन्त्रण",
                "title_en": "Forest Encroachment, Poaching and Logging Control",
                "requires_data": [],
                "auto_generate": False,
                "needs_user_input": True,
            },
            "घ": {
                "title_ne": "वन्यजन्तु तथा जैविक मार्ग संरक्षण",
                "title_en": "Wildlife and Biological Corridor Conservation",
                "requires_data": ["biodiversity"],
                "auto_generate": True,
            },
            "ड": {
                "title_ne": "वातावरणीय सेवा मूलप्रवाहीकरण",
                "title_en": "Environmental Service Mainstreaming",
                "requires_data": ["raster_analysis"],
                "auto_generate": True,
            },
            "च": {
                "title_ne": "पानीका मुहान, खोला किनार, सिमसार, जलाधार संरक्षण तथा भू-क्षय नियन्त्रण",
                "title_en": "Water Sources, River Banks, Wetlands, Watershed Conservation and Erosion Control",
                "requires_data": ["raster_analysis"],
                "auto_generate": True,
            },
            "छ": {
                "title_ne": "जलवायुजन्य जोखिम न्यूनीकरण तथा अनुकूलनका उपाय",
                "title_en": "Climate Risk Reduction and Adaptation Measures",
                "requires_data": ["raster_analysis"],
                "auto_generate": True,
            },
            "ज": {
                "title_ne": "वन संवर्द्धनका क्रियाकलाप",
                "title_en": "Forest Promotion Activities",
                "requires_data": ["activities", "sampling"],
                "auto_generate": True,
            },
            "झ": {
                "title_ne": "वन सम्बन्धी परम्परागत ज्ञान र प्रथाजनित अभ्यास",
                "title_en": "Traditional Knowledge and Practices Related to Forest",
                "requires_data": [],
                "auto_generate": False,
                "needs_user_input": True,
            },
        },
    },
    10: {
        "title_ne": "वन पैदावारमा आधारित आय-आर्जन, सिप विकास, उद्योग तथा पर्यापर्यटन सम्बन्धी व्यवस्था",
        "title_en": "Income Generation, Skill Development, Industry and Ecotourism Based on Forest Products",
        "requires_data": [],
        "auto_generate": False,
        "needs_user_input": True,
    },
    11: {
        "title_ne": "वार्षिक बजेट तथा कार्यक्रम तर्जुमा, कार्यान्वयन, अनुगमन र प्रतिवेदन सम्बन्धी व्यवस्था",
        "title_en": "Annual Budget and Program Formulation, Implementation, Monitoring and Reporting",
        "requires_data": ["activities"],
        "auto_generate": True,
    },
    12: {
        "title_ne": "व्यवस्थापन कार्ययोजना अवधिको लागि वार्षिक क्रियाकलाप तथा बजेट",
        "title_en": "Annual Activities and Budget for Management Plan Period",
        "requires_data": ["activities", "basic_info"],
        "auto_generate": True,
    },
    13: {
        "title_ne": "छिमेकी समूहसँग सहकार्य तथा साझेदारीको व्यवस्था",
        "title_en": "Collaboration and Partnership with Neighboring Groups",
        "requires_data": ["user_group"],
        "auto_generate": True,
    },
    14: {
        "title_ne": "व्यवस्थापन कार्ययोजनाको वित्तीय विश्लेषण",
        "title_en": "Financial Analysis of Management Plan",
        "requires_data": ["activities"],
        "auto_generate": True,
    },
    15: {
        "title_ne": "व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन",
        "title_en": "Review, Monitoring and Evaluation of Management Plan",
        "requires_data": [],
        "auto_generate": False,
        "needs_user_input": True,
    },
    16: {
        "title_ne": "अन्य आवश्यक कुरा",
        "title_en": "Other Necessary Matters",
        "requires_data": [],
        "auto_generate": False,
        "needs_user_input": True,
    },
}


COVER_PAGE_FIELDS = [
    {"key": "serial_number", "label_ne": "क्रम संख्या", "required": False},
    {"key": "province", "label_ne": "प्रदेश", "required": False},
    {"key": "division", "label_ne": "डिभिजन", "required": False},
    {"key": "sub_division", "label_ne": "सब डिभिजन", "required": False},
    {"key": "municipality", "label_ne": "पालिका", "required": False},
    {"key": "forest_name", "label_ne": "सामुदायिक वनको नाम", "required": True},
    {"key": "group_name", "label_ne": "उपभोक्ता समूहको नाम", "required": True},
    {"key": "address", "label_ne": "ठेगाना", "required": False},
    {"key": "fy_start", "label_ne": "आ.व. सुरु", "required": True},
    {"key": "fy_end", "label_ne": "आ.व. अन्त्य", "required": True},
    {"key": "cf_national_code", "label_ne": "सामुदायिक वन राष्ट्रिय तथ्याङ्क कोड", "required": False},
]
