"""
Canonical backend error-code registry — code → bilingual {en, ne}.

Phase 2 of the Nepali-first i18n initiative (`IMPLEMENTATION_PLAN_NEPALI_FIRST_I18N.md`
section 5). Every entry is an authoritative code key with both language variants so
API responses can carry `{"code", "message", "message_np"}`. The super-admin
translation editor (Phase 3) mirrors this exact shape in the DB `translations` table.

Usage:
    from app.core.i18n_messages import MESSAGES, i18n_error
    raise i18n_error(400, "auth.invalid_credentials")
    raise i18n_error(404, "calculations.not_found", calculation_id=…)
    # -> HTTPException(status, detail={"code":…, "message": en, "message_np": ne, ...fields})

Rules:
  1. Category = first dotted segment (must exist in the registry below).
  2. `{name}` style placeholders are resolved via ``str.format`` into BOTH languages.
  3. Every code MUST have both `en` and `ne` — enforced by
     `backend/tests/test_i18n_messages.py`.
  4. Nepali text already present in the codebase (validators, services) is kept
     verbatim as the `ne` seed; the matching `en` is authored here.
"""

from typing import Any

MESSAGES: dict[str, dict[str, dict[str, str]]] = {
    # ---------------------------------------------------------------- auth ----
    "auth": {
        # H2.1 / S1-01 — admin approval flow for self-registered accounts.
        "cannot_suspend_self": {
            "en": "You cannot suspend your own account",
            "ne": "तपाईं आफ्नै खाता निलम्बन गर्न सक्नुहुन्न",
        },
        "cannot_change_own_role": {
            "en": "You cannot change your own role",
            "ne": "तपाईं आफ्नै भूमिका परिवर्तन गर्न सक्नुहुन्न",
        },
        "registration_pending_approval": {
            "en": "Account created. An administrator must approve it before you can sign in.",
            "ne": "खाता सिर्जना भयो। साइन इन गर्नु अघि प्रशासकले स्वीकृत गर्नुपर्नेछ।",
        },
        "email_already_registered": {
            "en": "Email already registered",
            "ne": "इमेल पहिले नै दर्ता भइसकेको छ",
        },
        # Sign-up verification, recovery and Facebook login.
        "phone_invalid": {
            "en": "Enter a valid mobile number (for Nepal: 98XXXXXXXX)",
            "ne": "मान्य मोबाइल नम्बर राख्नुहोस् (नेपालका लागि: 98XXXXXXXX)",
        },
        "phone_already_registered": {
            "en": "This phone number is already registered",
            "ne": "यो फोन नम्बर पहिले नै दर्ता भइसकेको छ",
        },
        "code_wrong": {"en": "Wrong code", "ne": "कोड गलत छ"},
        "code_expired": {
            "en": "The code has expired or was never sent. Ask for a new one.",
            "ne": "कोडको समय सकियो वा पठाइएको छैन। नयाँ कोड माग्नुहोस्।",
        },
        "code_too_many_attempts": {
            "en": "Too many wrong attempts. Ask for a new code.",
            "ne": "धेरै पटक गलत प्रयास भयो। नयाँ कोड माग्नुहोस्।",
        },
        "code_resend_wait": {
            "en": "Please wait a minute before asking for another code",
            "ne": "अर्को कोड माग्नु अघि एक मिनेट पर्खनुहोस्",
        },
        "too_many_codes": {
            "en": "Too many codes requested today. Try again tomorrow.",
            "ne": "आज धेरै कोड मागियो। भोलि फेरि प्रयास गर्नुहोस्।",
        },
        "link_invalid": {
            "en": "This link is invalid or has expired",
            "ne": "यो लिङ्क अमान्य छ वा समय सकिएको छ",
        },
        "designation_required": {
            "en": "Choose Forest guard, Forester, Ranger or Office",
            "ne": "वन रक्षक, फरेस्टर, रेञ्जर वा कार्यालय छान्नुहोस्",
        },
        "type_field_invalid": {
            "en": "Please fill in '{field}' correctly",
            "ne": "कृपया '{field}' सही रूपमा भर्नुहोस्",
        },
        "read_only_account": {
            "en": "Your account is read-only: you can look at your forests but not change them",
            "ne": "तपाईंको खाता हेर्न मात्र मिल्ने छ: वन हेर्न सकिन्छ, परिवर्तन गर्न मिल्दैन",
        },
        "access_expired": {
            "en": "Your access has ended. Ask an administrator to renew it",
            "ne": "तपाईंको पहुँचको अवधि सकिएको छ। प्रशासकसँग नवीकरण गर्न अनुरोध गर्नुहोस्",
        },
        "type_locked": {
            "en": "Your account type was approved and can only be changed by an administrator",
            "ne": "तपाईंको खाताको प्रकार स्वीकृत भइसक्यो; प्रशासकले मात्र परिवर्तन गर्न सक्छ",
        },
        "not_org_owner": {
            "en": "Only the owner of a verified organization can vouch for its members",
            "ne": "प्रमाणित संस्थाको मालिकले मात्र सदस्यलाई प्रमाणित गर्न सक्छ",
        },
        "approval_required": {
            "en": "This needs your account to be approved by an administrator first",
            "ne": "यसका लागि पहिले प्रशासकले तपाईंको खाता स्वीकृत गर्नुपर्छ",
        },
        "social_required": {
            "en": "Give your Facebook account or your Instagram handle",
            "ne": "आफ्नो फेसबुक खाता वा इन्स्टाग्राम ह्यान्डल दिनुहोस्",
        },
        "facebook_already_linked": {
            "en": "This Facebook account is already used by another user",
            "ne": "यो फेसबुक खाता अर्को प्रयोगकर्ताले प्रयोग गरिसकेको छ",
        },
        "phone_not_verified": {
            "en": "Verify your phone number first",
            "ne": "पहिले आफ्नो फोन नम्बर प्रमाणित गर्नुहोस्",
        },
        "facebook_unavailable": {
            "en": "Facebook sign-in is not set up yet",
            "ne": "फेसबुक साइन इन अहिलेसम्म सेटअप भएको छैन",
        },
        "facebook_invalid": {
            "en": "Facebook could not confirm this sign-in",
            "ne": "फेसबुकले यो साइन इन पुष्टि गर्न सकेन",
        },
        "no_contact_to_reset": {
            "en": "This account has no verified phone or email to send a reset to",
            "ne": "यो खातामा रिसेट पठाउन प्रमाणित फोन वा इमेल छैन",
        },
        "invalid_credentials": {
            "en": "Incorrect email or password",
            "ne": "इमेल वा पासवर्ड गलत छ",
        },
        "account_status_inactive": {
            "en": "User account is {status}. Please contact administrator.",
            "ne": "प्रयोगकर्ता खाता {status} छ। कृपया व्यवस्थापकलाई सम्पर्क गर्नुहोस्।",
        },
        "account_inactive": {
            "en": "Account is {status}. Please contact administrator.",
            "ne": "खाता {status} छ। कृपया व्यवस्थापकलाई सम्पर्क गर्नुहोस्।",
        },
        "logged_out": {
            "en": "Signed out",
            "ne": "साइन आउट भयो",
        },
        "session_revoked": {
            "en": "Session has been revoked. Please sign in again.",
            "ne": "सत्र रद्द गरिएको छ। कृपया पुनः साइन इन गर्नुहोस्।",
        },
        "refresh_token_required": {
            "en": "A refresh token is required",
            "ne": "रिफ्रेस टोकन आवश्यक छ",
        },
        "refresh_token_invalid": {
            "en": "Refresh token is invalid or expired. Please sign in again.",
            "ne": "रिफ्रेस टोकन अमान्य वा म्याद सकिएको छ। कृपया पुनः साइन इन गर्नुहोस्।",
        },
        "refresh_token_reused": {
            "en": "This session was signed out for security reasons. Please sign in again.",
            "ne": "सुरक्षा कारणले यो सत्र बन्द गरिएको छ। कृपया पुनः साइन इन गर्नुहोस्।",
        },
        "wrong_current_password": {
            "en": "Incorrect current password",
            "ne": "हालको पासवर्ड गलत छ",
        },
        "new_password_same": {
            "en": "New password must be different from current password",
            "ne": "नयाँ पासवर्ड हालको पासवर्डभन्दा फरक हुनुपर्छ",
        },
        "password_changed": {
            "en": "Password changed successfully",
            "ne": "पासवर्ड सफलतापूर्वक परिवर्तन भयो",
        },
        "invalid_token": {
            "en": "Invalid token",
            "ne": "अमान्य टोकन",
        },
        "invalid_token_type": {
            "en": "Invalid token type",
            "ne": "अमान्य टोकन प्रकार",
        },
        "invalid_token_payload": {
            "en": "Invalid token payload",
            "ne": "अमान्य टोकन डाटा",
        },
        "user_not_found_or_inactive": {
            "en": "User not found or inactive",
            "ne": "प्रयोगकर्ता फेला परेन वा निष्क्रिय छ",
        },
        "user_not_found": {
            "en": "User not found",
            "ne": "प्रयोगकर्ता फेला परेन",
        },
        "could_not_validate_credentials": {
            "en": "Could not validate credentials",
            "ne": "प्रमाणहरू प्रमाणित गर्न सकिएन",
        },
        "invalid_auth_credentials": {
            "en": "Invalid authentication credentials",
            "ne": "अमान्य प्रमाणीकरण प्रमाणहरू",
        },
        "insufficient_permissions": {
            "en": "Insufficient permissions. Required roles: {roles}",
            "ne": "अपर्याप्त अनुमतिहरू। आवश्यक भूमिकाहरू: {roles}",
        },
        "insufficient_scope": {
            "en": "Insufficient scope for this operation",
            "ne": "यो कार्यका लागि अपर्याप्त पहुँच",
        },
    },
    # ------------------------------------------------------------ boundary ----
    "boundary": {
        "unsupported_geometry_type": {
            "en": "Unsupported geometry type: {geom_type}",
            "ne": "समर्थन नगरिएको ज्यामिति प्रकार: {geom_type}",
        },
        "resolved_geometry_must_be_polygon": {
            "en": "Resolved geometry must be a polygon",
            "ne": "टुंग्याइएको ज्यामिति बहुभुज हुनुपर्छ",
        },
        "overlap_detected_relock": {
            "en": "Overlap detected after locking — re-run preview",
            "ne": "लक गरेपछि अतिव्यापन फेला पर्यो — पूर्वावलोकन फेरि चलाउनुहोस्",
        },
        "at_least_3_points": {
            "en": "At least 3 points required",
            "ne": "कम्तिमा ३ वटा बिन्दु आवश्यक छ",
        },
        "invalid_polygon": {
            "en": "Invalid polygon: {error}",
            "ne": "अमान्य बहुभुज: {error}",
        },
        "only_dfo_can_change_status": {
            "en": "Only DFO can change boundary status",
            "ne": "सिमाना स्थिति परिवर्तन गर्न एक मात्र DFO सक्छ",
        },
        "forest_not_found": {
            "en": "Forest not found",
            "ne": "वन फेला परेन",
        },
        "forest_or_boundary_not_found": {
            "en": "Forest or boundary not found",
            "ne": "वन वा सिमाना फेला परेन",
        },
        "only_validated_can_be_disputed": {
            "en": "Only validated forests can be disputed",
            "ne": "प्रमाणित वनहरूमा मात्र विवाद दायर गर्न सकिन्छ",
        },
        "no_overlapping_forest_found": {
            "en": "No overlapping forest found for current user",
            "ne": "हालको प्रयोगकर्ताका लागि अतिव्यापी वन फेला परेन",
        },
        "no_gap_forest_found": {
            "en": "No neighbouring forest with a gap found for current user",
            "ne": "हालको प्रयोगकर्ताका लागि ग्याप भएको छिमेकी वन फेला परेन",
        },
        "invalid_dispute_reason_type": {
            "en": "Dispute reason type must be 'overlap' or 'gap'",
            "ne": "विवाद कारण प्रकार 'overlap' वा 'gap' हुनुपर्छ",
        },
        "only_owner_can_edit": {
            "en": "Only the owner or a DFO can edit this forest's boundary",
            "ne": "यस वनको सिमाना सम्पादन गर्न मालिक वा DFO मात्र सक्छ",
        },
        "only_dfo_access": {
            "en": "Only DFO can access this endpoint",
            "ne": "यो एन्डप्वाइन्ट पहुँच गर्न एक मात्र DFO सक्छ",
        },
        "dispute_not_found": {
            "en": "Dispute not found",
            "ne": "विवाद फेला परेन",
        },
        "dispute_already_resolved": {
            "en": "Dispute already resolved",
            "ne": "विवाद पहिले नै टुंगिएको छ",
        },
        "boundary_empty": {
            "en": "Boundary empty: no valid polygon geometry found in the collection",
            "ne": "BOUNDARY_EMPTY: GeometryCollection मा कुनै वैध बहुभुज ज्यामिति छैन",
        },
        "boundary_type_invalid": {
            "en": "Boundary must be a Polygon or MultiPolygon, got {geom_type}",
            "ne": "सीमा Polygon वा MultiPolygon हुनुपर्छ, पाइयो {geom_type}",
        },
        "boundary_check_failed": {
            "en": "Boundary check failed: {error}",
            "ne": "सीमा जाँच असफल: {error}",
        },
        "file_parse_failed": {
            "en": "Could not read the boundary file: {error}",
            "ne": "सिमाना फाइल पढ्न सकिएन: {error}",
        },
    },
    # -------------------------------------------------------------- blocks ----
    "blocks": {
        # VR-3 / Rule A — gated on this write path as well as edit-geometry.
        "boundary_locked_by_structure": {
            "en": "The forest boundary is locked because blocks or compartments exist. Edit those instead, or remove them first.",
            "ne": "ब्लक वा कम्पार्टमेन्ट भएकाले वनको सिमाना लक गरिएको छ। सट्टामा तिनीहरू सम्पादन गर्नुहोस्, वा पहिले हटाउनुहोस्।",
        },
        "not_authorized_calculation": {
            "en": "Not authorized to access this calculation",
            "ne": "यो गणनामा पहुँच गर्न अधिकृत हुनुहुन्न",
        },
        "no_boundary_geometry_calculation": {
            "en": "No boundary geometry found for this calculation",
            "ne": "यो गणनाका लागि कुनै सिमाना ज्यामिति फेला परेन",
        },
        "no_geometry": {
            "en": "Calculation has no boundary geometry",
            "ne": "गणनामा कुनै सिमाना ज्यामिति छैन",
        },
        "polygon_index_not_found": {
            "en": "Polygon index {index} not found",
            "ne": "बहुभुज अनुक्रमणिका {index} फेला परेन",
        },
        "polygon_index_invalid_area": {
            "en": "Polygon index {index} has invalid area ({area} ha)",
            "ne": "बहुभुज अनुक्रमणिका {index} को क्षेत्रफल अमान्य छ ({area} हे.)",
        },
        "geometry_required": {
            "en": "Geometry is required",
            "ne": "ज्यामिति आवश्यक छ",
        },
        "failed_update_boundary": {
            "en": "Failed to update boundary: {error}",
            "ne": "सिमाना अद्यावधिक गर्न असफल: {error}",
        },
        "geometry_edits_not_allowed": {
            "en": "Geometry updates are not allowed via this endpoint. Use POST /calculations/{id}/geometry/edit-geometry.",
            "ne": "यो एन्डप्वाइन्टबाट ज्यामिति अद्यावधिक गर्न अनुमति छैन। POST /calculations/{id}/geometry/edit-geometry प्रयोग गर्नुहोस्।",
        },
        "has_children_confirm_required": {
            "en": "This division has {count} sub-division(s) below it. Add confirm_children=true to delete them too, or move them out first.",
            "ne": "यो विभाजनमुनि {count} उप-विभाजन(हरू) छन्। तिनीहरू पनि मेटाउन confirm_children=true थप्नुहोस्, वा पहिले तिनीहरूलाई अन्तै सार्नुहोस्।",
        },
        "forest_division_not_found": {
            "en": "Forest division not found",
            "ne": "वन विभाजन फेला परेन",
        },
        "name_required": {
            "en": "Provide at least one of name, block_name or natural_name.",
            "ne": "नाम, ब्लक नाम वा प्राकृतिक नाममध्ये कम्तिमा एउटा प्रदान गर्नुहोस्।",
        },
        "not_authorized": {
            "en": "Not authorized",
            "ne": "अधिकृत हुनुहुन्न",
        },
        "no_blocks_defined": {
            "en": "No blocks defined",
            "ne": "कुनै ब्लक परिभाषित छैन",
        },
        "permission_denied": {
            "en": "Permission denied",
            "ne": "अनुमति अस्वीकृत",
        },
        "no_areas_defined": {
            "en": "Calculation has no areas defined yet. Create them first.",
            "ne": "गणनामा अझै कुनै क्षेत्र परिभाषित छैन। पहिले तिनीहरू सिर्जना गर्नुहोस्।",
        },
        "area_details_error": {
            "en": "Error calculating area details: {error}",
            "ne": "क्षेत्र विवरण गणना गर्दा त्रुटि: {error}",
        },
        "boundary_updated": {
            "en": "Boundary updated successfully",
            "ne": "सिमाना सफलतापूर्वक अद्यावधिक भयो",
        },
        "blocks_updated": {
            "en": "Updated {blocks} blocks. {clipped} sub-areas were clipped to fit within block boundaries.",
            "ne": "{blocks} ब्लकहरू अद्यावधिक गरियो। ब्लक सिमानाभित्र मिलाउन {clipped} उप-क्षेत्रहरू काटियो।",
        },
        "areas_recalculated": {
            "en": "Recalculated areas for {blocks} blocks and {subareas} sub-areas",
            "ne": "{blocks} ब्लक र {subareas} उप-क्षेत्रहरूको क्षेत्रफल पुन: गणना गरियो",
        },
        "no_boundary": {
            "en": "Forest boundary is required before auto-blocking.",
            "ne": "स्वतः-ब्लकिङ गर्नुअघि वन सिमाना आवश्यक छ।",
        },
        "blocks_exist": {
            "en": "Blocks/compartments already exist. Clear them before auto-generating.",
            "ne": "ब्लक/उप-विभाजनहरू पहिले नै अवस्थित छन्। स्वतः-सिर्जना गर्नुअघि तिनीहरू खाली गर्नुहोस्।",
        },
        "bad_level": {
            "en": "level must be 'blocks' or 'compartments'.",
            "ne": "स्तर 'blocks' वा 'compartments' हुनुपर्छ।",
        },
        "bad_source": {
            "en": "source must be 'mmu', 'slope', 'aspect', 'canopy', 'nasa_quality', 'forest_health', 'landcover', 'dem' or 'forest_type'.",
            "ne": "स्रोत 'mmu', 'slope', 'aspect', 'canopy', 'nasa_quality', 'forest_health', 'landcover', 'dem' वा 'forest_type' हुनुपर्छ।",
        },
        "layer_not_found": {
            "en": "This layer does not exist for this forest.",
            "ne": "यो तह यस वनका लागि अवस्थित छैन।",
        },
        "legacy_blocks_exist": {
            "en": "This forest already has blocks/compartments that do not belong to any layer (drawn, imported, or made before layers existed). Delete them before promoting a layer.",
            "ne": "यस वनमा कुनै तहमा नपर्ने (हातले कोरिएका, आयात गरिएका वा तहहरू सुरु हुनुअघि बनेका) ब्लक/उप-विभाजनहरू पहिल्यै छन्। तह पदोन्नति गर्नुअघि तिनीहरू मेटाउनुहोस्।",
        },
        "promoted_cannot_delete": {
            "en": "This layer is the forest's current blocks/compartments. Demote it to a trial layer before deleting it.",
            "ne": "यो तह अहिले वनको ब्लक/उप-विभाजनको रूपमा प्रयोग भइरहेको छ। मेटाउनुअघि यसलाई प्रयास तहमा फर्काउनुहोस्।",
        },
        "promoted_layer_exists": {
            "en": "Another layer is already the forest's blocks/compartments. Confirm to switch to this one instead.",
            "ne": "अर्को तह पहिले नै वनको ब्लक/उप-विभाजनको रूपमा प्रयोग भइरहेको छ। यसमा बदल्न पुष्टि गर्नुहोस्।",
        },
        "empty_layer": {
            "en": "This layer has no pieces left — they may have been deleted another way (e.g. deleting the compartment/block directly). Create the layer again before assigning it.",
            "ne": "यो तहमा कुनै खण्ड बाँकी छैन — तिनीहरू अन्य तरिकाले मेटिएको हुन सक्छ (जस्तै कम्पार्टमेन्ट/ब्लक सिधै मेटाउँदा)। तोक्नुअघि तह फेरि सिर्जना गर्नुहोस्।",
        },
        "no_slope_coverage": {
            "en": "No slope-regulation raster covers this forest, so slope-class blocks cannot be generated.",
            "ne": "यो वनलाई ढलान-नियमन रास्टरले समेट्दैन, त्यसैले ढलान-वर्ग अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_aspect_coverage": {
            "en": "No aspect raster covers this forest, so aspect-class blocks cannot be generated.",
            "ne": "यो वनलाई पक्ष (aspect) रास्टरले समेट्दैन, त्यसैले पक्ष-वर्ग अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_canopy_coverage": {
            "en": "No canopy-height data covers this forest, so canopy-class blocks cannot be generated (coverage is patchy for this product).",
            "ne": "यो वनलाई क्यानोपी-उचाइ डाटाले समेट्दैन, त्यसैले क्यानोपी-वर्ग अनुसार ब्लक सिर्जना गर्न सकिँदैन (यो डाटामा ठाउँ-ठाउँमा खाली भाग हुन्छ)।",
        },
        "no_nasa_quality_coverage": {
            "en": "No NASA 2020 forest-quality raster covers this forest, so forest-quality blocks cannot be generated.",
            "ne": "यो वनलाई NASA 2020 वन-गुणवत्ता रास्टरले समेट्दैन, त्यसैले वन-गुणवत्ता अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_forest_health_coverage": {
            "en": "No forest-health (NDVI) raster covers this forest, so forest-health blocks cannot be generated.",
            "ne": "यो वनलाई वन-स्वास्थ्य (NDVI) रास्टरले समेट्दैन, त्यसैले वन-स्वास्थ्य अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_landcover_coverage": {
            "en": "No ESA WorldCover land-cover raster covers this forest, so land-cover blocks cannot be generated.",
            "ne": "यो वनलाई ESA WorldCover भू-आवरण रास्टरले समेट्दैन, त्यसैले भू-आवरण अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_elevation_coverage": {
            "en": "No elevation (DEM) raster covers this forest, so elevation-band blocks cannot be generated.",
            "ne": "यो वनलाई उचाइ (DEM) रास्टरले समेट्दैन, त्यसैले उचाइ-ब्यान्ड अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_forest_type_coverage": {
            "en": "No FRTC forest-type raster covers this forest, so forest-type blocks cannot be generated.",
            "ne": "यो वनलाई FRTC वन-प्रकार रास्टरले समेट्दैन, त्यसैले वन-प्रकार अनुसार ब्लक सिर्जना गर्न सकिँदैन।",
        },
        "no_mmu_coverage": {
            "en": "No natural (river/ridge) units could be generated for this forest, so a Union layer cannot be built on top of them.",
            "ne": "यो वनको लागि प्राकृतिक (खोला/भिर) एकाइहरू सिर्जना गर्न सकिएन, त्यसैले तिनको माथि Union तह बनाउन सकिँदैन।",
        },
        "no_union_fusion_coverage": {
            "en": "None of the selected rasters (e.g. NASA 2020 forest quality) cover this forest, so a fused Union layer cannot be built. Try deselecting that attribute or picking a different source.",
            "ne": "छानिएका रास्टरहरू (जस्तै NASA 2020 वन-गुणवत्ता) मध्ये कुनैले पनि यो वनलाई समेट्दैन, त्यसैले मिश्रित Union तह बनाउन सकिँदैन। त्यो विशेषता हटाउनुहोस् वा फरक स्रोत छान्नुहोस्।",
        },
        "no_coverage_in_feature": {
            "en": "Nothing is left to divide here: this area is entirely private land or a protection unit.",
            "ne": "यहाँ विभाजन गर्न केही बाँकी छैन: यो क्षेत्र पूरै निजी जग्गा वा संरक्षण क्षेत्र हो।",
        },
        "empty_blocks": {
            "en": "At least one block geometry is required.",
            "ne": "कम्तिमा एउटा ब्लक ज्यामिति आवश्यक छ।",
        },
    },
    # -------------------------------------------------------- calculations ----
    "calculations": {
        "not_found": {
            "en": "Calculation not found",
            "ne": "गणना फेला परेन",
        },
        "dfo_only_approve": {
            "en": "Only a DFO can approve this calculation",
            "ne": "यो गणना डिभिजन वन अधिकृतले मात्र स्वीकृत गर्न सक्नुहुन्छ",
        },
        "dfo_only_reject": {
            "en": "Only a DFO can reject this calculation",
            "ne": "यो गणना डिभिजन वन अधिकृतले मात्र अस्वीकृत गर्न सक्नुहुन्छ",
        },
        "no_blocks": {
            "en": "Calculation has no management units",
            "ne": "गणनामा कुनै व्यवस्थापन एकाइ छैन",
        },
        "no_geometry": {
            "en": "Calculation has no boundary geometry",
            "ne": "गणनामा कुनै सिमाना ज्यामिति छैन",
        },
        "incomplete": {
            "en": "Analysis may not be complete",
            "ne": "विश्लेषण पूरा नभएको हुन सक्छ",
        },
        "already_exists": {
            "en": "Calculation already exists",
            "ne": "गणना पहिले नै अवस्थित छ",
        },
        "locked": {
            "en": "Calculation is locked and cannot be modified",
            "ne": "गणना लक गरिएको छ र परिमार्जन गर्न सकिँदैन",
        },
        "not_authorized": {
            "en": "Not authorized",
            "ne": "अधिकृत हुनुहुन्न",
        },
        "permission_denied": {
            "en": "Permission denied",
            "ne": "अनुमति अस्वीकृत",
        },
        "validation_error": {
            "en": "Validation error: {error}",
            "ne": "प्रमाणीकरण त्रुटि: {error}",
        },
    },
    # -------------------------------------------------------- compartments ----
    "compartments": {
        "not_found": {
            "en": "Compartment not found",
            "ne": "उप-विभाजन फेला परेन",
        },
        "can_only_delete_compartments": {
            "en": "Can only delete compartments",
            "ne": "केवल उप-विभाजनहरू मेटाउन सकिन्छ",
        },
        "can_only_subdivide_compartments": {
            "en": "Can only sub-divide existing sub-divisions",
            "ne": "केवल अवस्थित उप-विभाजनहरूलाई मात्र विभाजन गर्न सकिन्छ",
        },
        "mutually_exclusive": {
            "en": "Compartments are mutually exclusive with block-level sampling.",
            "ne": "उप-विभाजनहरू ब्लक-स्तरीय नमूनासँग परस्पर विशिष्ट छन्।",
        },
        "division_once_only": {
            "en": "This area already has sub-divisions. Delete them first or select a different area.",
            "ne": "यो क्षेत्रमा पहिले नै उप-विभाजनहरू छन्। पहिले तिनीहरू मेटाउनुहोस् वा फरक क्षेत्र चयन गर्नुहोस्।",
        },
        "sampling_mutex": {
            "en": "Cannot create compartments: this forest already has block-level sampling designs. Compartments are mutually exclusive with block-level sampling. Please delete existing sampling designs first if you want to switch to compartment mode.",
            "ne": "उप-विभाजनहरू सिर्जना गर्न सकिँदैन: यो वनमा पहिले नै ब्लक-स्तरीय नमूना योजनाहरू छन्। उप-विभाजनहरू ब्लक-स्तरीय नमूनासँग परस्पर विशिष्ट छन्। कृपया उप-विभाजन मोडमा स्विच गर्न पहिले अवस्थित नमूना योजनाहरू मेटाउनुहोस्।",
        },
        "compartment_already_in_use": {
            "en": "Only one block can have compartments at a time. Delete the existing compartments before dividing another block.",
            "ne": "एक पटकमा एउटा मात्र ब्लकमा उप-विभाजनहरू हुन सक्छन्। अर्को ब्लक विभाजन गर्नुअघि अवस्थित उप-विभाजनहरू मेटाउनुहोस्।",
        },
        "only_subdivide_compartments": {
            "en": "Can only sub-divide compartments.",
            "ne": "केवल उप-विभाजनहरूलाई मात्र उप-विभाजन गर्न सकिन्छ।",
        },
        "locked_from_division": {
            "en": "Block is locked from further division.",
            "ne": "ब्लक थप विभाजनबाट लक गरिएको छ।",
        },
        "parent_not_found": {
            "en": "Forest division not found",
            "ne": "वन विभाजन फेला परेन",
        },
        "only_blocks_dividable": {
            "en": "Only forest blocks (division_level 0, non-compartment) can be divided into compartments.",
            "ne": "केवल वन ब्लकहरू (division_level 0, उप-विभाजन नभएका) मात्र उप-विभाजनहरूमा विभाजन गर्न सकिन्छ।",
        },
        "over_coverage": {
            "en": "The proposed division over-covers the parent area and cannot be saved.",
            "ne": "प्रस्तावित विभाजन मूल क्षेत्रभन्दा बढी ढाक्छ र सुरक्षित गर्न सकिँदैन।",
        },
        "no_subdivisions_found": {
            "en": "No sub-divisions found for this area",
            "ne": "यो क्षेत्रका लागि कुनै उप-विभाजनहरू फेला परेनन्",
        },
        "no_divisions_for_calculation": {
            "en": "No forest divisions found for this calculation",
            "ne": "यो गणनाका लागि कुनै वन विभाजनहरू फेला परेनन्",
        },
        "split_method_invalid": {
            "en": "Invalid split method",
            "ne": "अमान्य विभाजन विधि",
        },
        "sampling_mutex_preview": {
            "en": "Cannot preview compartment split: this forest already has block-level sampling designs. Compartments are mutually exclusive with block-level sampling. Please delete existing sampling designs first if you want to switch to compartment mode.",
            "ne": "उप-विभाजनको पूर्वावलोकन गर्न सकिँदैन: यो वनमा पहिले नै ब्लक-स्तरीय नमूना योजनाहरू छन्। उप-विभाजनहरू ब्लक-स्तरीय नमूनासँग परस्पर विशिष्ट छन्। कृपया उप-विभाजन मोडमा स्विच गर्न पहिले अवस्थित नमूना योजनाहरू मेटाउनुहोस्।",
        },
        "compartment_name_updated": {
            "en": "Compartment name updated",
            "ne": "उप-विभाजनको नाम अद्यावधिक भयो",
        },
        "failed_get_divisions": {
            "en": "Failed to get forest divisions: {error}",
            "ne": "वन विभाजनहरू प्राप्त गर्न असफल: {error}",
        },
        "failed_process_areas": {
            "en": "Failed to process any areas. Check backend logs.",
            "ne": "कुनै पनि क्षेत्रहरू प्रशोधन गर्न असफल। ब्याकएन्ड लगहरू जाँच गर्नुहोस्।",
        },
    },
    # -------------------------------------------------------------- editing ----
    "editing": {
        # The forest boundary is not a block. When the client asks to edit
        # feature "boundary" while a block/compartment layer is active, the id
        # is not a UUID and the query used to die inside the driver.
        "boundary_is_not_a_division": {
            "en": "The forest boundary can't be edited from the block layer. Switch the active layer to Forest Boundary and try again.",
            "ne": "वन सिमानालाई ब्लक तहबाट सम्पादन गर्न मिल्दैन। सक्रिय तह 'वन सिमाना' मा बदलेर फेरि प्रयास गर्नुहोस्।",
        },
        "unknown_feature": {
            "en": "That feature could not be found — it may have been deleted or renumbered. Reload the map and try again.",
            "ne": "त्यो वस्तु फेला परेन — यो मेटिएको वा पुन: क्रमाङ्कित भएको हुन सक्छ। नक्सा पुन: लोड गरी फेरि प्रयास गर्नुहोस्।",
        },
        "split_failed": {
            "en": "Split produced no valid sub-divisions",
            "ne": "विभाजनले कुनै वैध उप-विभाजन उत्पादन गरेन",
        },
        "locked_from_division": {
            "en": "Block is locked from further division",
            "ne": "ब्लक थप विभाजनबाट लक गरिएको छ",
        },
        "not_found": {
            "en": "Resource not found",
            "ne": "स्रोत फेला परेन",
        },
        "not_authorized": {
            "en": "Not authorized",
            "ne": "अधिकृत हुनुहुन्न",
        },
        "invalid_geometry": {
            "en": "Invalid geometry",
            "ne": "अमान्य ज्यामिति",
        },
        "structure_locked": {
            "en": "Structure is locked — geometry edits are disabled.",
            "ne": "संरचना लक गरिएको छ — ज्यामिति सम्पादनहरू असक्षम छन्।",
        },
        "structure_locked_preview": {
            "en": "Structure is locked — sampling preview is unavailable.",
            "ne": "यो संरचना लक गरिएको छ — नमूना पूर्वावलोकन उपलब्ध छैन।",
        },
        # Equal-area divide guardrails (MAX_PIECES: / PIECE_AREA_*: prefixes
        # raised by geometry_edit_service → resolve_service_detail).
        "divide_too_many_pieces": {
            "en": "Cannot divide into {count} pieces — the maximum is {max} per division.",
            "ne": "{count} टुक्रामा विभाजन गर्न सकिँदैन — बढीमा {max} टुक्रा।",
        },
        "divide_area_too_large": {
            "en": "The per-piece area must be smaller than the total area of this feature.",
            "ne": "प्रति-टुक्रा क्षेत्रफल यो फिचरको कुल क्षेत्रफलभन्दा सानो हुनुपर्छ।",
        },
        "divide_area_too_small": {
            "en": "The per-piece area is below the minimum of {min} ha.",
            "ne": "प्रति-टुक्रा क्षेत्रफल न्यूनतम {min} हेक्टरभन्दा कम छ।",
        },
        "divide_area_split_failed": {
            "en": "This per-piece area does not produce a valid division. Increase or decrease it and try again.",
            "ne": "यो प्रति-टुक्रा क्षेत्रफलले मान्य विभाजन दिँदैन। यसलाई बढाएर वा घटाएर फेरि प्रयास गर्नुहोस्।",
        },
        "divide_count_required": {
            "en": "A piece count or an area-per-piece target is required to divide.",
            "ne": "विभाजन गर्न टुक्रा सङ्ख्या वा प्रति-टुक्रा क्षेत्रफल टार्गेट आवश्यक छ।",
        },
        "divide_too_few": {
            "en": "This division produced fewer than two usable units, so nothing was changed. Choose a different source, or divide a larger area.",
            "ne": "यो विभाजनले दुईभन्दा कम प्रयोगयोग्य इकाइ दिएकाले केही पनि परिवर्तन भएन। अर्को स्रोत छान्नुहोस्, वा ठूलो क्षेत्र विभाजन गर्नुहोस्।",
        },
        "invalid_map_state": {
            "en": "Geometry edits require map state in {states}, got '{state}'",
            "ne": "ज्यामिति सम्पादनका लागि नक्सा स्थिति {states} मा हुनुपर्छ, '{state}' प्राप्त भयो",
        },
        "topology_rejected": {
            "en": "Edit rejected: overlaps or creates a gap with an adjacent feature.",
            "ne": "सम्पादन अस्वीकृत: छेउछाउको फिचरसँग अतिव्यापन वा खाडल सिर्जना हुन्छ।",
        },
        # VR-3 server-side vertex guard.
        "vertex_locked": {
            "en": "That vertex sits on the outer boundary and is locked. Only vertices shared between two units can be moved.",
            "ne": "त्यो शीर्षबिन्दु बाहिरी सिमानामा भएकाले लक छ। दुई एकाइबीच साझा शीर्षबिन्दु मात्र सार्न मिल्छ।",
        },
        "boundary_locked_by_structure": {
            "en": "The forest boundary is locked because blocks or compartments exist. Edit those instead, or remove them first.",
            "ne": "ब्लक वा कम्पार्टमेन्ट भएकाले वनको सिमाना लक गरिएको छ। सट्टामा तिनीहरू सम्पादन गर्नुहोस्, वा पहिले हटाउनुहोस्।",
        },
        "topology_merge_not_adjacent": {
            "en": "Merge rejected: selected features are not adjacent.",
            "ne": "मर्ज अस्वीकृत: चयन गरिएका फिचरहरू छेउछाउका छैनन्।",
        },
        "topology_merge_outside": {
            "en": "Merge rejected: the merged feature lies outside the forest boundary.",
            "ne": "मर्ज अस्वीकृत: मर्ज गरिएको फिचर वन सिमानाभन्दा बाहिर छ।",
        },
        "merge_not_siblings": {
            "en": "Merge rejected: the selected units must be siblings — the same parent and the same type (block/compartment/sub-block/sub-compartment).",
            "ne": "मर्ज अस्वीकृत: चयन गरिएका एकाइहरू सहोदर हुनुपर्छ — एउटै अभिभावक र एउटै प्रकार (ब्लक/कम्पार्टमेन्ट/उप-ब्लक/उप-कम्पार्टमेन्ट)।",
        },
        # D12 (FS-4a.11) — paste into a unit layer.
        "paste_same_place": {
            "en": "Paste rejected: this shape occupies (nearly) the same ground as an existing unit. Move it before pasting, or edit the existing unit instead.",
            "ne": "पेस्ट अस्वीकृत: यो आकारले अवस्थित एकाइले ओगटेको (लगभग) उही जमिन ओगट्छ। पेस्ट गर्नुअघि सार्नुहोस्, वा सट्टामा अवस्थित एकाइ सम्पादन गर्नुहोस्।",
        },
        "paste_stream_not_empty": {
            "en": "This forest already uses the other stream (blocks or compartments). Pasting into this one is only allowed while it is completely empty.",
            "ne": "यो वनले पहिल्यै अर्को स्ट्रिम (ब्लक वा कम्पार्टमेन्ट) प्रयोग गरिरहेको छ। यसमा पेस्ट गर्न यो पूर्णतया खाली हुँदा मात्र मिल्छ।",
        },
        "topology_overlap_area": {
            "en": "Edit rejected: blocks would exceed the forest boundary area (overlapping blocks).",
            "ne": "सम्पादन अस्वीकृत: ब्लकहरू वन सिमाना क्षेत्रभन्दा बढी हुन्छन् (अतिव्यापी ब्लकहरू)।",
        },
        "topology_auto_overlap": {
            "en": "Auto-blocks would exceed the forest boundary area.",
            "ne": "स्वतः-ब्लकहरू वन सिमाना क्षेत्रभन्दा बढी हुनेछन्।",
        },
        "has_child_layers": {
            "en": "This division has sub-divisions below it. Merge or delete them first.",
            "ne": "यो विभाजनमा तल उप-विभाजनहरू छन्। पहिले तिनीहरू मर्ज वा मेटाउनुहोस्।",
        },
        "has_child_layers_variant": {
            "en": "This area contains sub-layers. Merge or delete them before splitting.",
            "ne": "यो क्षेत्रमा उप-लेयरहरू छन्। विभाजन गर्नुअघि तिनीहरू मर्ज वा मेटाउनुहोस्।",
        },
        "split_execution_failed": {
            "en": "Split execution failed: {error}",
            "ne": "विभाजन कार्य असफल भयो: {error}",
        },
        "export_failed": {
            "en": "Export failed: {error}",
            "ne": "निर्यात असफल भयो: {error}",
        },
        "drawn_outside_boundary": {
            "en": "Drawn block lies entirely outside the forest boundary.",
            "ne": "कोरिएको ब्लक पूर्ण रूपमा वन सिमानाभन्दा बाहिर छ।",
        },
        "drawn_overlap": {
            "en": "Drawn block overlaps an existing block.",
            "ne": "कोरिएको ब्लक अवस्थित ब्लकसँग अतिव्यापन हुन्छ।",
        },
        "drawn_exceeds_boundary": {
            "en": "Drawn block would exceed the forest boundary area (overlap).",
            "ne": "कोरिएको ब्लक वन सिमाना क्षेत्रभन्दा बढी हुनेछ (अतिव्यापन)।",
        },
        "geometry_parse_failed": {
            "en": "Drawn geometry could not be parsed.",
            "ne": "कोरिएको ज्यामिति पढ्न सकिएन।",
        },
    },
    # ------------------------------------------------------------- geometry ----
    "geometry": {
        "invalid": {
            "en": "Invalid geometry data",
            "ne": "अमान्य ज्यामिति डाटा",
        },
        "required": {
            "en": "Geometry is required",
            "ne": "ज्यामिति आवश्यक छ",
        },
        "not_found": {
            "en": "Geometry not found",
            "ne": "ज्यामिति फेला परेन",
        },
        "edit_error": {
            "en": "Error editing geometry: {error}",
            "ne": "ज्यामिति सम्पादन गर्दा त्रुटि: {error}",
        },
        "type_unsupported": {
            "en": "Unsupported geometry type: {geom_type}",
            "ne": "समर्थन नगरिएको ज्यामिति प्रकार: {geom_type}",
        },
    },
    # -------------------------------------------------------------- imports ----
    "imports": {
        "boundary_required_first": {
            "en": "You must import a Block or Compartment layer first before importing sub-layers or reference data",
            "ne": "उप-लेयर वा सन्दर्भ डाटा आयात गर्नुअघि पहिले ब्लक वा उप-विभाजन लेयर आयात गर्नुपर्छ",
        },
        "not_authorized": {
            "en": "You do not have permission to modify this {resource}",
            "ne": "यो {resource} परिमार्जन गर्न तपाईंसँग अनुमति छैन",
        },
        "duplicate_purpose": {
            "en": "A layer with purpose '{purpose}' already exists. Use replace_existing=true to overwrite.",
            "ne": "उद्देश्य '{purpose}' भएको लेयर पहिले नै छ। अधिलेखनका लागि replace_existing=true प्रयोग गर्नुहोस्।",
        },
        "max_features_exceeded": {
            "en": "Too many features: {count} (max: {max_count})",
            "ne": "धेरै फिचरहरू: {count} (अधिकतम: {max_count})",
        },
        "max_vertices_exceeded": {
            "en": "Too many vertices: {count} (max: {max_count})",
            "ne": "धेरै शीर्षबिन्दुहरू: {count} (अधिकतम: {max_count})",
        },
        "area_limit_exceeded": {
            "en": "Polygon area {area} ha exceeds max {max} ha",
            "ne": "बहुभुज क्षेत्रफल {area} हे. अधिकतम {max} हे.भन्दा बढी छ",
        },
        "invalid_crs": {
            "en": "Unsupported CRS: EPSG:{epsg}",
            "ne": "समर्थन नगरिएको CRS: EPSG:{epsg}",
        },
        # H3.4: the declared CRS would not parse AND the coordinates are outside
        # the degree range, so WGS84 cannot be assumed. Distinct from
        # `invalid_crs`, which is a CRS we read and do not support.
        "crs_unreadable": {
            "en": (
                "The coordinate system of this file could not be read, and its "
                "coordinates are not longitude/latitude. Re-export it with a "
                "valid .prj file, or convert it to EPSG:4326 before importing."
            ),
            "ne": (
                "यस फाइलको निर्देशांक प्रणाली पढ्न सकिएन, र यसका निर्देशांकहरू "
                "देशान्तर/अक्षांश होइनन्। मान्य .prj फाइलसहित पुनः निर्यात गर्नुहोस्, "
                "वा आयात गर्नुअघि EPSG:4326 मा रूपान्तरण गर्नुहोस्।"
            ),
        },
        "duplicate_draft": {
            "en": "A draft layer with purpose '{purpose}' already exists. Finish & Save or Cancel & Discard it first.",
            "ne": "उद्देश्य '{purpose}' भएको ड्राफ्ट लेयर पहिले नै छ। पहिले Finish & Save वा Cancel & Discard गर्नुहोस्।",
        },
    },
    # ------------------------------------------------------------ inventory ----
    "inventory": {
        "forest_required": {
            "en": "A forest (calculation_id) is required for this upload",
            "ne": "यो अपलोडका लागि वन (calculation_id) आवश्यक छ",
        },
        "forest_not_found": {
            "en": "Forest not found",
            "ne": "वन फेला परेन",
        },
        "forest_not_yours": {
            "en": "You do not have permission to upload to this forest",
            "ne": "यो वनमा अपलोड गर्न तपाईंसँग अनुमति छैन",
        },
        "invalid_format": {
            "en": "Invalid inventory data format",
            "ne": "अमान्य सूची डाटा ढाँचा",
        },
        "invalid_block_areas": {
            "en": "Invalid block_areas JSON format",
            "ne": "अमान्य block_areas JSON ढाँचा",
        },
        "no_field_inventory": {
            "en": "No field inventory data found",
            "ne": "कुनै क्षेत्र सूची डाटा फेला परेन",
        },
        "species_not_found": {
            "en": "Species not found in reference database",
            "ne": "प्रजाति सन्दर्भ डाटाबेसमा फेला परेन",
        },
        "read_failed": {
            "en": "Error reading file: {error}",
            "ne": "फाइल पढ्दा त्रुटि: {error}",
        },
        "unsupported_format": {
            "en": "Could not read file. Supported formats: CSV, Excel (.xlsx/.xls), GeoPackage (.gpkg).",
            "ne": "फाइल पढ्न सकिएन। समर्थित ढाँचाहरू: CSV, Excel (.xlsx/.xls), GeoPackage (.gpkg)।",
        },
        "geopackage_read_failed": {
            "en": "Could not read GeoPackage file. Ensure the file is valid and geopandas is installed.",
            "ne": "GeoPackage फाइल पढ्न सकिएन। फाइल मान्य छ र geopandas स्थापित छ भनी सुनिश्चित गर्नुहोस्।",
        },
        "file_empty": {
            "en": "File is empty",
            "ne": "फाइल खाली छ",
        },
        "analyze_failed": {
            "en": "Error analyzing columns: {error}",
            "ne": "स्तम्भहरू विश्लेषण गर्दा त्रुटि: {error}",
        },
        "mapping_invalid": {
            "en": "Invalid mapping JSON format",
            "ne": "अमान्य म्यापिङ JSON ढाँचा",
        },
        "mapping_apply_failed": {
            "en": "Error applying column mapping: {error}",
            "ne": "स्तम्भ म्यापिङ लागू गर्दा त्रुटि: {error}",
        },
        "tree_mapping_exists": {
            "en": "Tree mapping already exists for this calculation. Please delete the existing tree mapping first.",
            "ne": "यो गणनाका लागि रूख म्यापिङ पहिले नै अवस्थित छ। कृपया पहिले अवस्थित रूख म्यापिङ मेटाउनुहोस्।",
        },
        "not_found": {
            "en": "Inventory not found",
            "ne": "सूची फेला परेन",
        },
        "processing_failed": {
            "en": "Processing failed: {error}",
            "ne": "प्रशोधन असफल भयो: {error}",
        },
    },
    # ------------------------------------------------------------- sampling ----
    "sampling": {
        "calculation_not_found": {
            "en": "Calculation {calculation_id} not found",
            "ne": "गणना {calculation_id} फेला परेन",
        },
        "cannot_delete_plot_field_data_exists": {
            "en": "This forest already has field inventory data uploaded, so individual sample plots can no longer be deleted here (it would break the field data's plot numbering).",
            "ne": "यो वनमा क्षेत्रीय वन सूची डाटा पहिले नै अपलोड गरिएको छ, त्यसैले यहाँ व्यक्तिगत नमूना प्लट मेटाउन सकिँदैन (यसले क्षेत्रीय डाटाको प्लट क्रमांकनलाई बिगार्छ)।",
        },
        "cannot_delete_last_plot": {
            "en": "Cannot delete the last remaining sample plot here — delete the whole sampling design instead.",
            "ne": "यहाँ अन्तिम बाँकी नमूना प्लट मेटाउन सकिँदैन — सट्टामा सम्पूर्ण नमूना डिजाइन मेटाउनुहोस्।",
        },
        "point_outside_boundary": {
            "en": "That location is outside the forest boundary — a sample plot cannot be placed or moved there.",
            "ne": "त्यो स्थान वनको सीमा बाहिर छ — नमूना प्लट त्यहाँ राख्न वा सार्न सकिँदैन।",
        },
        "plot_shape_required": {
            "en": "Plot shape and dimensions must be specified",
            "ne": "प्लटको आकार र आयामहरू उल्लेख गर्नुपर्छ",
        },
        "no_accessible_forest": {
            "en": "No forest pixels matching the filter were found: {filters}",
            "ne": "फिल्टरसँग मेल खाने वन पिक्सेलहरू फेला परेनन्: {filters}",
        },
        "no_points_generated": {
            # SFM tracker P6. The old wording only said "check the polygon and its
            # perimeters", which is what made P1 invisible: the message described a
            # geometric fault when the usual cause is that EVERY unit is MMU-exempt
            # (the 8.1 rule) - i.e. a policy outcome, not a broken polygon. Naming
            # the likeliest cause first is the difference between a user who knows
            # what to do and a user who re-draws a polygon that was never the problem.
            "en": (
                "No sampling points could be generated. The most common cause is that "
                "every unit is below the minimum size (MMU-exempt), so no unit is "
                "eligible for points. Check the unit sizes on the unit-size review, "
                "then the polygon and its perimeters."
            ),
            "ne": (
                "नमूना बिन्दुहरू जनरेट भएनन्। सबैभन्दा सामान्य कारण सबै एकाइ न्यूनतम आकारभन्दा सानो भएर MMU-मा छुटे हुनु हो, जसैले कुनै एकाइले पनि बिन्दु योग्य छैन। पहिले एकाइ-आकार समीक्षामा आकार जाँच गर्नुहोस्, त्यसपछि बहुभुज र परिमितिहरू।"
            ),
        },
"design_locked": {
            "en": "Structure is locked — sampling preview is unavailable.",
            "ne": "यो संरचना लक गरिएको छ — नमूना पूर्वावलोकन उपलब्ध छैन।",
        },
        "coordinate_none": {
            "en": "Enter a latitude, a longitude, a UTM easting or a UTM northing.",
            "ne": "अक्षांश, देशान्तर, UTM इस्टिङ वा UTM नर्दिङ मध्ये एउटा लेख्नुहोस्।",
        },
        "coordinate_both": {
            "en": "Change either the latitude / longitude or the UTM easting / northing, not both at once.",
            "ne": "अक्षांश / देशान्तर वा UTM इस्टिङ / नर्दिङ मध्ये एउटा मात्र परिवर्तन गर्नुहोस्, दुवै एकसाथ होइन।",
        },
        "coordinate_not_a_number": {
            "en": "The {field} you typed is not a number.",
            "ne": "तपाईंले लेख्नुभएको {field} संख्या होइन।",
        },
        "coordinate_lat_range": {
            "en": "A latitude of {value} is not valid: it must be between -90 and 90.",
            "ne": "{value} अक्षांश मान्य छैन: यो -९० र ९० बीच हुनुपर्छ।",
        },
        "coordinate_lon_range": {
            "en": "A longitude of {value} is not valid: it must be between -180 and 180.",
            "ne": "{value} देशान्तर मान्य छैन: यो -१८० र १८० बीच हुनुपर्छ।",
        },
        "coordinate_easting_range": {
            "en": "A UTM easting of {value} is not valid in zone {zone}: it must be between 0 and 1,000,000 metres.",
            "ne": "UTM जोन {zone} मा {value} इस्टिङ मान्य छैन: यो ० र १,०००,००० मिटर बीच हुनुपर्छ।",
        },
        "coordinate_northing_range": {
            "en": "A UTM northing of {value} is not valid in zone {zone}: it must be between 0 and 10,000,000 metres.",
            "ne": "UTM जोन {zone} मा {value} नर्दिङ मान्य छैन: यो ० र १०,०००,००० मिटर बीच हुनुपर्छ।",
        },
        "point_outside_boundary_typed": {
            "en": "The point you typed ({point}) is outside the forest boundary, so it was not saved. Check the numbers: the plot keeps its old position.",
            "ne": "तपाईंले लेख्नुभएको बिन्दु ({point}) वनको सीमाभन्दा बाहिर छ, त्यसैले सुरक्षित गरिएन। अङ्कहरू जाँच्नुहोस्: प्लट पुरानै ठाउँमा रहन्छ।",
        },
        "point_outside_boundary_typed_two_zones": {
            "en": "The point you typed ({point}) is outside the forest boundary, so it was not saved. This forest crosses two UTM zones: type UTM values in the zone shown in that plot's own row (UTM Zone column). The plot keeps its old position.",
            "ne": "तपाईंले लेख्नुभएको बिन्दु ({point}) वनको सीमाभन्दा बाहिर छ, त्यसैले सुरक्षित गरिएन। यो वन दुई UTM जोनमा पर्छ: त्यही प्लटको पङ्क्तिको (UTM Zone स्तम्भ) जोनमा UTM मान लेख्नुहोस्। प्लट पुरानै ठाउँमा रहन्छ।",
        },
        "unit_already_sampled": {
            "en": "These polygons already have sample plots: {units}. To sample a polygon again, first delete its plots.",
            "ne": "यी बहुभुजमा पहिले नै नमूना प्लट छन्: {units}। फेरि नमूना लिन पहिले यसका प्लटहरू मेटाउनुहोस्।",
        },
        "add_no_unit_selected": {
            "en": "Tick at least one polygon that does not have plots yet.",
            "ne": "अहिलेसम्म प्लट नभएको कम्तिमा एउटा बहुभुज छान्नुहोस्।",
        },
        "cannot_add_units_field_data_exists": {
            "en": "Field inventory data already exists for this forest, so plots cannot be added or removed. Delete the field inventory first.",
            "ne": "यो वनको वन तथ्याङ्क पहिले नै छ, त्यसैले प्लट थप्न वा हटाउन सकिँदैन। पहिले वन तथ्याङ्क मेटाउनुहोस्।",
        },
        "unit_has_no_plots": {
            "en": "This polygon has no sample plots.",
            "ne": "यो बहुभुजमा नमूना प्लट छैन।",
        },
        "cannot_delete_unit_plots_last": {
            "en": "These are the only plots in the design. Delete the whole design instead.",
            "ne": "यी योजनाका एकमात्र प्लट हुन्। बरु पूरै योजना मेटाउनुहोस्।",
        },
        "design_already_exists": {
            "en": "A sampling design already exists for this calculation. Please delete the existing design (ID: {design_id}) before creating a new one.",
            "ne": "यो गणनाका लागि पहिले नै नमूना योजना अवस्थित छ। नयाँ सिर्जना गर्नुअघि कृपया अवस्थित योजना (आईडी: {design_id}) मेटाउनुहोस्।",
        },
        "invalid_design": {
            "en": "Invalid sampling design",
            "ne": "अमान्य नमूना योजना",
        },
        "insufficient_area": {
            "en": "Insufficient forest area for requested sampling intensity",
            "ne": "माग गरिएको नमूना तीव्रताका लागि अपर्याप्त वन क्षेत्र",
        },
        "boundary_error": {
            "en": "Too many sample plots are outside the forest boundary",
            "ne": "धेरै सेम्पल प्लट सीमा बाहिर छन्",
        },
        "boundary_warning": {
            "en": "{count} sample plots are outside the boundary (within 20% tolerance)",
            "ne": "{count} सेम्पल प्लट सीमा बाहिर छन् (२०% सहनशीलता भित्र)",
        },
        "intensity_below_floor": {
            "en": "Sampling intensity for {unit} ({stratum} stratum) must be at least {floor}% per कार्यविधि §16. Submitted: {value}%.",
            "ne": "{unit} ({stratum} stratum) को नमूना सघनता कम्तीमा {floor}% हुनुपर्छ (कार्यविधि §१६)। पेश गरिएको: {value}%।",
        },
        "stratum_production": {
            "en": "Production",
            "ne": "उत्पादन",
        },
        "stratum_conservation": {
            "en": "Conservation",
            "ne": "संरक्षण",
        },
        "stratum_protection": {
            "en": "Protection",
            "ne": "संरक्षित क्षेत्र",
        },
        "floor_plot_size_production": {
            "en": "Production plot size: {sqm} m²",
            "ne": "उत्पादन प्लट आकार: {sqm} वर्ग मि।",
        },
        "floor_plot_size_conservation": {
            "en": "Conservation plot size: {sqm} m²",
            "ne": "संरक्षण प्लट आकार: {sqm} वर्ग मि।",
        },
        "floor_plot_size_protection": {
            "en": "Protection plot size: {sqm} m²",
            "ne": "संरक्षित प्लट आकार: {sqm} वर्ग मि।",
        },
        "min_plots_per_unit": {
            "en": "At least {count} sample plots per block/compartment/sub-compartment",
            "ne": "प्रत्येक ब्लक/कम्पार्टमेन्ट/उप-कम्पार्टमेन्टमा कम्तीमा {count} नमूना प्लटहरू",
        },
    },
    # -------------------------------------------------- operational_plan ------
    "yearly_plan": {
        "sub_areas_need_plan": {
            "en": "{count} sub-area(s) have no activity plan yet: {names}. Give each one an activity in the yearly plan (only private land is exempt), then try again.",
            "ne": "{count} उप-क्षेत्रको लागि वार्षिक कार्ययोजनामा कुनै कार्य छैन: {names}। प्रत्येकलाई वार्षिक योजनामा कार्य तोक्नुहोस् (निजी जग्गा मात्र छुट), त्यसपछि फेरि प्रयास गर्नुहोस्।",
        },
        "sub_area_has_plan_lines": {
            "en": "This sub-area is tied to {count} line(s) of the yearly plan ({names}). Choose what happens to them: delete them with the sub-area, or keep them as forest-wide lines.",
            "ne": "यो उप-क्षेत्र वार्षिक योजनाका {count} कार्यसँग जोडिएको छ ({names})। ती कार्यहरू उप-क्षेत्रसँगै मेटाउने कि सम्पूर्ण वनको कार्यको रूपमा राख्ने भन्ने छान्नुहोस्।",
        },
        "sub_area_not_found": {
            "en": "That sub-area was not found in this forest.",
            "ne": "यो उप-क्षेत्र यस वनमा फेला परेन।",
        },
        "sub_area_no_unit": {
            "en": "This sub-area does not lie inside any block or compartment, so it cannot be planned yet. Redraw it inside the forest.",
            "ne": "यो उप-क्षेत्र कुनै ब्लक वा कम्पार्टमेन्टभित्र पर्दैन, त्यसैले अहिले योजना बनाउन सकिँदैन। यसलाई वनभित्र पुनः कोर्नुहोस्।",
        },
        "activity_not_found": {
            "en": "That activity is not in the activity list.",
            "ne": "यो कार्य कार्यसूचीमा छैन।",
        },
    },
    "operational_plan": {
        "generation_failed": {
            "en": "Operational plan generation failed",
            "ne": "कार्ययोजना निर्माण असफल भयो",
        },
        "template_not_found": {
            "en": "OP template not found",
            "ne": "कार्ययोजना टेम्पलेट फेला परेन",
        },
        "variable_not_found": {
            "en": "Template variable not found",
            "ne": "टेम्पलेट चर फेला परेन",
        },
    },
    # ---------------------------------------------------------- translations ----
    "translations": {
        "not_found": {
            "en": "Translation key not found",
            "ne": "अनुवाद कुञ्जी फेला परेन",
        },
        "key_required": {
            "en": "Translation key is required",
            "ne": "अनुवाद कुञ्जी आवश्यक छ",
        },
        "permission_denied": {
            "en": "Only super admin can manage translations",
            "ne": "अनुवाद व्यवस्थापन गर्न केवल सुपर एडमिन सक्छ",
        },
    },
    # ------------------------------------------------------- forest_metadata ----
    # WORKSPACE_FLOW_NAV_PLAN D5. Authored facts about a forest, stored 1:1 with
    # a calculation in `forest_metadata` (migration 098). These are validation
    # and lookup failures -- saving the form and generating the .docx.
    "rasters": {
        "unknown_layer": {
            "en": "Unknown raster layer '{layer}'",
            "ne": "अज्ञात रास्टर तह '{layer}'",
        },
        "no_boundary": {
            "en": "This forest has no boundary yet, so raster coverage cannot be checked",
            "ne": "यस वनको अझै सीमा छैन, त्यसैले रास्टर कभरेज जाँच्न सकिँदैन",
        },
    },
    "forest_metadata": {
        "calc_not_found": {
            "en": "Calculation not found",
            "ne": "गणना फेला परेन",
        },
        "not_found": {
            "en": "No metadata has been recorded for this forest yet",
            "ne": "यस वनको लागि अझै कुनै विवरण दर्ता गरिएको छैन",
        },
        "saved": {
            "en": "Forest details saved",
            "ne": "वनका विवरण सुरक्षित गरियो",
        },
        "empty_update": {
            "en": "Nothing to save",
            "ne": "सुरक्षित गर्नुपर्ने कुनै विवरण छैन",
        },
        "field_too_long": {
            "en": "{field} is too long (max {max} characters)",
            "ne": "{field} धेरै लामो छ (बढीमा {max} अक्षर)",
        },
        "fy_order": {
            "en": "The start of the fiscal year must not come after its end",
            "ne": "आर्थिक वर्षको सुरु अन्त्य भन्दा पछि हुनु हुँदैन",
        },
        "no_forest_name": {
            "en": "A forest name is needed before the report can be generated",
            "ne": "प्रतिवेदन बनाउन वनको नाम आवश्यक छ",
        },
        "no_sections": {
            "en": "Select at least one section to include",
            "ne": "कम्तीमा एउटा खण्ड छान्नुहोस्",
        },
    },
    # ----------------------------------------------------------- user_group ----
    "user_group": {
        "not_found": {
            "en": "User group not found",
            "ne": "उपभोक्ता समूह फेला परेन",
        },
        "user_not_found": {
            "en": "User not found",
            "ne": "प्रयोगकर्ता फेला परेन",
        },
        "invalid_data": {
            "en": "Invalid user group data",
            "ne": "अमान्य उपभोक्ता समूह डाटा",
        },
        # Owner decision D2 (2026-10-12): a group over the analysis limit is refused, nothing is saved.
        "too_large": {
            "en": "The user group would cover {area_ha} ha, but the limit is {limit_ha} ha, so it was not saved and nothing was changed. "
                  "Draw or upload a smaller boundary, for example only the part the group actually uses.",
            "ne": "उपभोक्ता समूहको क्षेत्रफल {area_ha} हेक्टर हुन्छ, तर सीमा {limit_ha} हेक्टर हो, त्यसैले यो सुरक्षित गरिएन र केही पनि परिवर्तन भएन। "
                  "सानो सीमा कोर्नुहोस् वा अपलोड गर्नुहोस्, जस्तै समूहले वास्तवमा प्रयोग गर्ने भाग मात्र।",
        },
    },
    "translations": {
        "key_empty": {
            "en": "Translation key cannot be empty",
            "ne": "अनुवाद कुञ्जी खाली हुन सक्दैन",
        },
        "placeholder_missing": {
            "en": "This wording drops {placeholders}, which the message needs. Keep it in the text, in the right place.",
            "ne": "यो पाठले {placeholders} छोडेको छ, जुन सन्देशलाई चाहिन्छ। यसलाई पाठमा उपयुक्त ठाउँमा राख्नुहोस्।",
        },
        "nothing_to_update": {
            "en": "Provide at least one of en/ne to update",
            "ne": "अद्यावधिक गर्न कम्तीमा en/ne मध्ये एउटा प्रदान गर्नुहोस्",
        },
        "key_not_found": {
            "en": "Translation key not found",
            "ne": "अनुवाद कुञ्जी फेला परेन",
        },
    },
    # --------------------------------------------------------------- general ----
    "general": {
        "bad_request": {
            "en": "Bad request",
            "ne": "अमान्य अनुरोध",
        },
        "not_found": {
            "en": "Resource not found",
            "ne": "स्रोत फेला परेन",
        },
        "internal_error": {
            "en": "Internal server error",
            "ne": "आन्तरिक सर्भर त्रुटि",
        },
        "service_unavailable": {
            "en": "Service temporarily unavailable",
            "ne": "सेवा अस्थायी रूपमा अनुपलब्ध छ",
        },
        "validation_error": {
            "en": "Validation error",
            "ne": "प्रमाणीकरण त्रुटि",
        },
        "not_authorized": {
            "en": "Not authorized",
            "ne": "अधिकृत हुनुहुन्न",
        },
        # Read by the catch-all handler in `main.py`, so this is the sentence a
        # user sees for any failure nobody anticipated. It names the reference
        # code because that is the one thing that turns "it broke" into a
        # report someone can actually trace in the log.
        # H8.6 / S2-67. The natural-key constraints answer 409 like any other
        # IntegrityError, but "Bad request" leaves the user with no idea what to
        # change. These say which record already exists, because the usual cause
        # is an honest one -- a retried upload, or two enumerators entering the
        # same house -- and the fix is obvious once it is named.
        "duplicate_household": {
            "en": "A household with this house number already exists for this forest. "
                  "Use a different house number, or edit the existing record.",
            "ne": "यस वनको लागि यो घर नम्बर भएको घरधुरी पहिले नै छ। "
                  "अर्को घर नम्बर प्रयोग गर्नुहोस्, वा भएकै विवरण सम्पादन गर्नुहोस्।",
        },
        "duplicate_measurement": {
            "en": "A measurement with this serial number already exists for this "
                  "sample plot and stand type.",
            "ne": "यस नमुना प्लट र स्ट्यान्ड प्रकारको लागि यो क्रम संख्या भएको "
                  "नाप पहिले नै छ।",
        },
        # One field-inventory record per calculation (UNIQUE calculation_id).
        "duplicate_field_inventory": {
            "en": "This forest already has a field inventory analysis. "
                  "Delete the existing analysis first, then upload the new file.",
            "ne": "यस वनको फिल्ड इन्भेन्टरी विश्लेषण पहिले नै छ। "
                  "नयाँ फाइल अपलोड गर्नुअघि अवस्थित विश्लेषण मेटाउनुहोस्।",
        },
        "unexpected_error": {
            "en": "Something went wrong at our end. Your work has not been saved. Please try again — if it keeps happening, quote the reference code below.",
            "ne": "हाम्रो तर्फबाट केही गडबड भयो। तपाईंको काम सुरक्षित भएको छैन। कृपया फेरि प्रयास गर्नुहोस् — पटक-पटक भइरहेमा तलको सन्दर्भ कोड उल्लेख गर्नुहोस्।",
        },
        # A database rejected the VALUE we sent it (bad UUID, out-of-range
        # number, malformed date). Before this existed the driver's exception
        # went to the browser verbatim — full SQL, column list and parameters —
        # which is unreadable to a user and a schema disclosure to everyone else.
        "invalid_value": {
            "en": "Something in that request wasn't in a form the system could use. Please reload the page and try again.",
            "ne": "अनुरोधमा भएको कुनै मान प्रणालीले प्रयोग गर्न मिल्ने ढाँचामा थिएन। कृपया पृष्ठ पुन: लोड गरी फेरि प्रयास गर्नुहोस्।",
        },
    },
    # --------------------------------------------------------------- success ----
    "success": {
        "tree_cover_calculated": {
            "en": "Tree cover areas calculated and stored successfully",
            "ne": "रूख आवरण क्षेत्रहरू सफलतापूर्वक गणना र भण्डारण गरियो",
        },
        "geometry_updated": {
            "en": "Geometry updated successfully",
            "ne": "ज्यामिति सफलतापूर्वक अद्यावधिक भयो",
        },
        "geometry_updated_reanalyzed": {
            "en": "Geometry updated successfully and re-analysis completed",
            "ne": "ज्यामिति सफलतापूर्वक अद्यावधिक भयो र पुनः-विश्लेषण सम्पन्न भयो",
        },
        "sub_area_updated": {
            "en": "Sub-area updated successfully",
            "ne": "उप-क्षेत्र सफलतापूर्वक अद्यावधिक भयो",
        },
        "boundary_updated": {
            "en": "Boundary updated successfully",
            "ne": "सिमाना सफलतापूर्वक अद्यावधिक भयो",
        },
        "no_sub_areas_to_delete": {
            "en": "No sub-areas to delete.",
            "ne": "मेटाउन कुनै उप-क्षेत्रहरू छैनन्।",
        },
        "tree_mapping_deleted": {
            "en": "Tree mapping deleted successfully",
            "ne": "रूख म्यापिङ सफलतापूर्वक मेटियो",
        },
        "sampling_design_deleted": {
            "en": "Sampling design deleted successfully",
            "ne": "नमूना योजना सफलतापूर्वक मेटियो",
        },
        "tree_export_deleted": {
            "en": "All-tree export deleted successfully",
            "ne": "सबै-रूख निर्यात सफलतापूर्वक मेटियो",
        },
        "field_inventory_deleted": {
            "en": "Field inventory deleted successfully",
            "ne": "क्षेत्र सूची सफलतापूर्वक मेटियो",
        },
        "species_removed": {
            "en": "Species removed successfully",
            "ne": "प्रजाति सफलतापूर्वक हटाइयो",
        },
        "household_deleted": {
            "en": "Household deleted successfully",
            "ne": "परिवार सफलतापूर्वक मेटियो",
        },
        "committee_member_deleted": {
            "en": "Committee member deleted successfully",
            "ne": "समिति सदस्य सफलतापूर्वक मेटियो",
        },
        "advisory_member_deleted": {
            "en": "Advisory committee member deleted successfully",
            "ne": "सल्लाहकार समिति सदस्य सफलतापूर्वक मेटियो",
        },
        "financial_member_deleted": {
            "en": "Financial committee member deleted successfully",
            "ne": "आर्थिक समिति सदस्य सफलतापूर्वक मेटियो",
        },
        "committee_data_deleted": {
            "en": "All committee data deleted successfully",
            "ne": "सबै समिति डाटा सफलतापूर्वक मेटियो",
        },
        "year_detail_deleted": {
            "en": "Year detail deleted",
            "ne": "वर्ष विवरण मेटियो",
        },
        "spatial_assignment_deleted": {
            "en": "Spatial assignment deleted",
            "ne": "स्थानिक असाइनमेन्ट मेटियो",
        },
        "drawn_feature_deleted": {
            "en": "Drawn feature deleted",
            "ne": "कोरिएको फिचर मेटियो",
        },
        "template_deleted": {
            "en": "Template deleted",
            "ne": "टेम्प्लेट मेटियो",
        },
        "template_deleted_permanently": {
            "en": "Template deleted permanently. Copies keep working, but their credit chain now starts at the copy",
            "ne": "टेम्प्लेट स्थायी रूपमा मेटियो। प्रतिलिपिहरू चलिरहन्छन्, तर तिनको श्रेय शृङ्खला अब प्रतिलिपिबाटै सुरु हुन्छ",
        },
        "template_withdrawn": {
            "en": "Template withdrawn: it is off everyone's shelf, and your name stays on the copies others made",
            "ne": "टेम्प्लेट फिर्ता गरियो: यो सबैको सूचीबाट हट्यो, र अरूले बनाएका प्रतिलिपिमा तपाईंको नाम रहन्छ",
        },
        "category_deleted": {
            "en": "Category deleted",
            "ne": "श्रेणी मेटियो",
        },
    },
}


def get_message(code: str) -> dict[str, str]:
    """Return `{en, ne}` for a dotted `category.code` key (or `category.sub.code`)."""
    parts = code.split(".")
    # Walk nesting (categories are flat here, but keep sub-namespacing tolerant).
    node: Any = MESSAGES
    for part in parts[:-1]:
        node = node.get(part, {})
    entry = node.get(parts[-1]) if isinstance(node, dict) else None
    if entry is None:
        raise KeyError(f"Unknown i18n message code: {code!r}")
    return entry