"""Add the 34 activities of the Rambhadevi CF OP (table 27) that the master list lacked.

Revision ID: 119_rambhadevi_missing_activities
Revises: 118_merge_cf_code_into_national_code
Create Date: 2026-10-14

RAMBHADEVI_SFM_RENEW_TEMPLATE_PLAN.md §8 item 8. `potential_activities` held 135 activities;
the approved Rambhadevi plan's annual-activity table needs 34 more - mostly the
silviculture-based operations (annual working unit, mother-tree verification, tree marking,
felling-residue removal, controlled burning, regeneration fencing/enhancement, thinning,
preparatory felling, timber / firewood collection per operation, depot) plus fire-control,
patrol, wildlife-conflict, office and governance items.

Idempotent: a row is added only when no row with the same `activities` text exists, and its
project/programme text is copied from a reference row (skipped when that row is absent, e.g. on a
database that never had the master list seeded). No existing row is touched.
"""

import sqlalchemy as sa
from alembic import op

revision = "119_rambhadevi_missing_activities"
down_revision = "118_merge_cf_code_into_national_code"
branch_labels = None
depends_on = None

# (reference row id for project/programme, activities, unit, name_en, search_terms, map_kind, requires_map, is_felling)
CONS, SILV, UTIL, INST, POOR, BIO, OFFICE = 12, 19, 29, 102, 63, 86, 118
ROWS = [
    (CONS, "अग्नि नियन्त्रण रेखा मर्मत तथा सरसफाई", "कि.मि.", "Fire line maintenance and cleaning", "fire, line, marmat, maintenance, cleaning, firebreak", "fire_line", True, None),
    (CONS, "वन डढेलो नियन्त्रणका लागि टोली गठन", "टोली", "Forest fire control team formation", "fire, team, dadhelo, control, brigade", None, False, None),
    (CONS, "वन डढेलो नियन्त्रण सामाग्री खरिद", "सेट", "Forest fire control equipment purchase", "fire, equipment, rake, shovel, axe, gloves, saamagri", None, False, None),
    (CONS, "वन डढेलो, चोरी निकासी तथा अतिक्रमण नियन्त्रणका लागि गस्ती परिचालन", "प्याकेज", "Patrol mobilisation for fire, theft and encroachment control", "patrol, gasti, fire, theft, encroachment", None, False, None),
    (CONS, "वन अतिक्रमण नियन्त्रण कार्यक्रम (नियमित गस्ती, अनुगमन)", "प्याकेज", "Forest encroachment control programme", "encroachment, atikraman, patrol, monitoring", None, False, None),
    (CONS, "वन हेरालुलाई पोसाक", "जना", "Uniform for forest guards", "heralu, guard, uniform, posak", None, False, None),
    (CONS, "बरामद तथा पक्राउ परेका काठ दाउरा ढुवानी र घाटगद्दी", "पटक", "Transport and depot of seized timber and firewood", "seized, confiscated, transport, ghatgaddi, timber, firewood", None, False, None),
    (CONS, "खोलाखोल्सी, खहरे संरक्षण तथा पानी निकास व्यवस्थापन", "प्याकेज", "Stream, gully protection and drainage management", "khola, kholsi, khahare, gully, drainage, stream", "water_source_protection", True, None),
    (SILV, "पुनरुत्पादन कटानका लागि वार्षिक कार्यक्षेत्र (Annual working unit) सीमांकन", "संख्या", "Annual working unit demarcation for regeneration felling", "annual, working, unit, coupe, regeneration, felling, demarcation", "coupe", True, None),
    (SILV, "माउ रुख निरीक्षण, भेरीफिकेशन तथा माउ रुखमा रिङ्ग पेन्टिङ", "रुख संख्या", "Mother tree verification and ring painting", "mother, tree, verification, ring, painting, mau, rukh", "silviculture_area", True, None),
    (SILV, "कटान गरिने रुखको छपान तथा छपान रुखको निरीक्षण र अन्तिम लिस्ट तयारी", "रुख संख्या", "Marking of trees to be felled and final list preparation", "tree, marking, chhapan, felling, list, inspection", "coupe", True, None),
    (SILV, "पुनरुत्पादन कटान क्षेत्रमा कटान अवशेष तथा अनावश्यक वनस्पति हटाउने", "हे.", "Felling residue and unwanted vegetation removal in regeneration felling area", "residue, slash, removal, regeneration, felling, cleaning", "silviculture_area", True, None),
    (SILV, "पुनरुत्पादन कटान पश्चात् सोही कुपमा नियन्त्रित आगलागी", "हे.", "Controlled burning after regeneration felling", "controlled, burning, fire, regeneration, felling, coupe", "silviculture_area", True, None),
    (SILV, "पुनरुत्पादन कटान क्षेत्रमा तारबार गर्ने", "हे.", "Fencing of regeneration felling area", "fencing, tarbar, regeneration, felling, protection", "anr_area", True, None),
    (SILV, "पुनरुत्पादन अभिवृद्धि क्रियाकलाप", "हे.", "Regeneration enhancement activities", "regeneration, enhancement, abhivriddhi, sowing, weeding, protection", "silviculture_area", True, None),
    (SILV, "थिनिङ्ग तथा सुधार कटान", "हेक्टर", "Thinning and improvement felling", "thinning, improvement, felling, sudhar, katan, tending", "silviculture_area", True, True),
    (SILV, "पुनरुत्पादन तयारी कटान", "हेक्टर", "Preparatory felling", "preparatory, felling, regeneration, tayari, katan", "silviculture_area", True, True),
    (UTIL, "डीपो तथा घाटगद्दी निर्माण तथा व्यवस्थापन", "संख्या", "Depot and ghatgaddi construction and management", "depot, ghatgaddi, store, gate, fencing, timber", None, False, None),
    (UTIL, "ढलापडा रुखको काठ संकलन", "क्यु.फि.", "Timber collection from windfall trees", "windfall, dhalapada, fallen, timber, collection", "coupe", True, True),
    (UTIL, "ढलापडा रुखको दाउरा संकलन", "चट्टा", "Firewood collection from windfall trees", "windfall, dhalapada, fallen, firewood, collection", "coupe", True, True),
    (UTIL, "अग्निरेखा निर्माण क्षेत्रबाट काठ संकलन", "क्यु.फि.", "Timber collection from fire line construction area", "fire, line, construction, timber, collection", "coupe", True, True),
    (UTIL, "अग्निरेखा निर्माण क्षेत्रबाट दाउरा संकलन", "चट्टा", "Firewood collection from fire line construction area", "fire, line, construction, firewood, collection", "coupe", True, True),
    (UTIL, "पुनरुत्पादन तयारी तथा थिनिङ्ग कार्यबाट काठ संकलन", "क्यु.फि.", "Timber collection from preparatory felling and thinning", "preparatory, thinning, timber, collection", "coupe", True, True),
    (UTIL, "पुनरुत्पादन तयारी तथा थिनिङ्ग कार्यबाट दाउरा संकलन", "चट्टा", "Firewood collection from preparatory felling and thinning", "preparatory, thinning, firewood, collection", "coupe", True, True),
    (BIO, "मानव वन्यजन्तु द्वन्द्व व्यवस्थापन (राहत वितरण, प्रचारप्रसार तथा वासस्थान सुधार)", "प्याकेज", "Human-wildlife conflict management", "human, wildlife, conflict, relief, habitat, dwandwa", None, False, None),
    (POOR, "जैविक मल तथा कम्पोष्ट मल उत्पादन तालिम", "पटक", "Organic and compost manure production training", "compost, organic, manure, training, talim", None, False, None),
    (POOR, "व्यवसायिक तरकारी खेती तालिम", "पटक", "Commercial vegetable farming training", "vegetable, farming, training, talim, commercial", None, False, None),
    (INST, "वार्षिक प्रगति प्रतिवेदन तयारी", "पटक", "Annual progress report preparation", "annual, progress, report, pratibedan", None, False, None),
    (INST, "अध्यक्षको समन्वय तथा सहकार्य खर्च", "महिना", "Chairperson coordination and collaboration expense", "chairperson, adhyaksha, coordination, collaboration, expense", None, False, None),
    (INST, "अतिथि सत्कार, दान दातव्य, चन्दा", "प्याकेज", "Hospitality, donations and contributions", "hospitality, guest, donation, chanda", None, False, None),
    (OFFICE, "मेसिनरी सामान खरिद (कम्प्युटर, प्रिन्टर, इन्टरनेट, जीपीएस आदि) तथा मर्मत", "प्याकेज", "Machinery and equipment purchase and repair", "computer, printer, internet, gps, machinery, equipment", None, False, None),
    (OFFICE, "कार्यालय सञ्चालन खर्च", "प्याकेज", "Office operation expense", "office, operation, expense, karyalaya, sanchalan", None, False, None),
    (INST, "जलवायु परिवर्तन, कार्बन व्यापार तथा REDD सम्बन्धी सचेतना", "पटक", "Awareness on climate change, carbon trade and REDD", "climate, change, carbon, redd, awareness", None, False, None),
    (INST, "आय व्ययको वार्षिक लेखापरीक्षण (मान्यता प्राप्त लेखापरीक्षकबाट)", "पटक", "Annual audit by a recognised auditor", "audit, lekhaparikshan, auditor, annual", None, False, None),
]

INSERT = sa.text(
    """
    INSERT INTO potential_activities
        (project_name, progarms, activities, unit, name_en, search_terms,
         map_kind, requires_map, is_felling, quantity, yearly_budget, is_default, display_order, is_active)
    SELECT r.project_name, r.progarms, :activities, :unit, :name_en, :terms,
           :map_kind, :requires_map, :is_felling, '', '', '', 0, TRUE
      FROM potential_activities r
     WHERE r.id = :ref
       AND NOT EXISTS (SELECT 1 FROM potential_activities x WHERE x.activities = :activities)
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for ref, activities, unit, name_en, terms, map_kind, requires_map, is_felling in ROWS:
        bind.execute(
            INSERT,
            {
                "ref": ref, "activities": activities, "unit": unit, "name_en": name_en, "terms": terms,
                "map_kind": map_kind, "requires_map": requires_map, "is_felling": is_felling,
            },
        )
    # the display number (sn) is the id in Devanagari digits, like the seeded rows
    bind.execute(
        sa.text(
            "UPDATE potential_activities SET sn = translate(id::text, '0123456789', '०१२३४५६७८९') "
            "WHERE sn IS NULL"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    for _ref, activities, *_rest in ROWS:
        # only remove a row nobody has planned yet
        bind.execute(
            sa.text(
                "DELETE FROM potential_activities p WHERE p.activities = :a "
                "AND NOT EXISTS (SELECT 1 FROM proposed_yearly_activities y WHERE y.potential_activity_id = p.id)"
            ),
            {"a": activities},
        )
