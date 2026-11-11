"""One format for "what is wrong with this upload, and how to fix it" (UPLOAD_EXPERIENCE_PLAN.md, UP-2).

Every upload used to answer a bad file its own way: a raw library message ("File is not a zip file"), a Python error ("list index out of range"),
a database error with the SQL, a Nepali-only message with a developer code in front. A user cannot act on any of those.

A :class:`UploadFinding` carries what the user needs, in both languages:

* ``code``      stable id (also the key of the catalogue below)
* ``severity``  ``error`` (stops the upload) | ``warning`` (continues, tell the user) | ``info``
* ``where``     ``{file?, sheet?, row?, rows?, column?}`` so the screen can point at it
* ``found`` / ``expected``   what we saw and what we needed (plain text, may be empty)
* ``fix_en`` / ``fix_ne``    how to correct it
* ``auto_fix``  optional id of a fix the system can apply for the user (UP-3 uses it)

The catalogue is the single place where the wording lives; ``tests/services/test_upload_findings.py`` fails if an entry lacks a language, a fix, or if
the English and Nepali texts use different ``{placeholders}``. :func:`upload_error` turns a finding into the ``HTTPException`` the API raises; its
``detail`` is ``{code, message, message_np, findings:[...]}``, which the front end's ``readDetail`` already understands (code + message + message_np).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

# ── the catalogue ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# title = what is wrong (one sentence), fix = what to do. {placeholders} are filled from the finding's fields.
CATALOGUE: Dict[str, Dict[str, Dict[str, str]]] = {
    # ---- any file --------------------------------------------------------------------------------------------------------------------
    "file.empty": {
        "title": {"en": "The file is empty.", "ne": "फाइल खाली छ।"},
        "fix": {"en": "Choose the file you meant to upload; this one has no content.", "ne": "तपाईंले अपलोड गर्न खोजेको फाइल छान्नुहोस्; यसमा केही छैन।"},
    },
    "file.no_rows": {
        "title": {"en": "The file has column names but no data rows.", "ne": "फाइलमा स्तम्भका नाम छन् तर तथ्याङ्क पङ्क्ति छैन।"},
        "fix": {"en": "Add your data below the column names and upload again.", "ne": "स्तम्भका नामको तल तथ्याङ्क थपेर फेरि अपलोड गर्नुहोस्।"},
    },
    "file.wrong_type": {
        "title": {"en": "This file type cannot be used here ({found}).", "ne": "यो प्रकारको फाइल यहाँ प्रयोग गर्न मिल्दैन ({found})।"},
        "fix": {"en": "Save it as {expected} and upload again.", "ne": "यसलाई {expected} मा सुरक्षित गरेर फेरि अपलोड गर्नुहोस्।"},
    },
    "file.corrupt": {
        "title": {"en": "The file could not be opened. It may be damaged, password-protected or not really a {expected} file.",
                  "ne": "फाइल खोल्न सकिएन। यो बिग्रिएको, पासवर्ड भएको, वा वास्तवमा {expected} फाइल नभएको हुन सक्छ।"},
        "fix": {"en": "Open it on your computer to check it, remove any password, save it again as {expected} and upload again.",
                "ne": "आफ्नो कम्प्युटरमा खोलेर जाँच गर्नुहोस्, पासवर्ड हटाउनुहोस्, {expected} मा फेरि सुरक्षित गरेर अपलोड गर्नुहोस्।"},
    },
    "file.too_large": {
        "title": {"en": "This file is larger than the {expected} limit.", "ne": "यो फाइल {expected} को सीमाभन्दा ठूलो छ।"},
        "fix": {"en": "Split the data into smaller files, remove columns you do not need, or save it as a zipped file, and upload again.",
                "ne": "तथ्याङ्कलाई साना फाइलमा बाँड्नुहोस्, चाहिने नभएका स्तम्भ हटाउनुहोस्, वा ZIP फाइलमा सुरक्षित गरेर फेरि अपलोड गर्नुहोस्।"},
    },
    "file.encoding": {
        "title": {"en": "The text in this file could not be read (it is not saved as UTF-8).", "ne": "यो फाइलको पाठ पढ्न सकिएन (UTF-8 मा सुरक्षित गरिएको छैन)।"},
        "fix": {"en": "In Excel choose Save As, then \"CSV UTF-8 (Comma delimited)\", and upload that file.",
                "ne": "Excel मा Save As मा गई \"CSV UTF-8 (Comma delimited)\" छानेर सुरक्षित गर्नुहोस् र त्यो फाइल अपलोड गर्नुहोस्।"},
    },
    "file.unreadable": {
        "title": {"en": "The file could not be read.", "ne": "फाइल पढ्न सकिएन।"},
        "fix": {"en": "Check that it opens normally on your computer and is one of: {expected}. If it still fails, send us the file.",
                "ne": "यो तपाईंको कम्प्युटरमा सामान्य रूपमा खुल्छ र {expected} मध्ये एक हो भनेर जाँच गर्नुहोस्। फेरि पनि भएन भने हामीलाई फाइल पठाउनुहोस्।"},
    },
    # ---- household -------------------------------------------------------------------------------------------------------------------
    "household.duplicate_house_no": {
        "title": {"en": "House number {found} appears more than once (rows {rows_text}).", "ne": "घर नम्बर {found} एकभन्दा बढी पटक छ (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Give each household its own house number, or delete the repeated row. The first one was kept.",
                "ne": "हरेक घरधुरीलाई आफ्नै घर नम्बर दिनुहोस्, वा दोहोरिएको पङ्क्ति मेटाउनुहोस्। पहिलो राखिएको छ।"},
    },
    "household.row_invalid": {
        "title": {"en": "{count} rows have a problem: {found}", "ne": "{count} पङ्क्तिमा समस्या छ: {found}"},
        "fix": {"en": "Correct these rows (rows {rows_text}) in your file and upload it again. Households already saved are simply updated.",
                "ne": "यी पङ्क्ति (पङ्क्ति {rows_text}) आफ्नो फाइलमा सच्याएर फेरि अपलोड गर्नुहोस्। सुरक्षित भइसकेका घरधुरी केवल अद्यावधिक हुन्छन्।"},
    },
    "household.no_rows": {
        "title": {"en": "No household rows were found in this file.", "ne": "यो फाइलमा कुनै घरधुरी पङ्क्ति भेटिएन।"},
        "fix": {"en": "Use the template: the first row holds the column names, the second row their English names, and the households start on row 3.",
                "ne": "टेम्प्लेट प्रयोग गर्नुहोस्: पहिलो पङ्क्तिमा स्तम्भका नाम, दोस्रोमा तिनका अङ्ग्रेजी नाम, र घरधुरी तेस्रो पङ्क्तिबाट सुरु हुन्छ।"},
    },
    # ---- user group ------------------------------------------------------------------------------------------------------------------
    "user_group.no_coordinates": {
        "title": {"en": "We could not find latitude and longitude columns. The columns we found: {found}.",
                  "ne": "अक्षांश र देशान्तरका स्तम्भ भेटिएन। भेटिएका स्तम्भ: {found}।"},
        "fix": {"en": "Name the two columns \"latitude\" and \"longitude\" (or lat / lon), or give a WKT geometry column, and upload again.",
                "ne": "दुई स्तम्भलाई \"latitude\" र \"longitude\" (वा lat / lon) नाम दिनुहोस्, वा WKT ज्यामिति स्तम्भ दिनुहोस्, र फेरि अपलोड गर्नुहोस्।"},
    },
    "user_group.too_few_points": {
        "title": {"en": "These points cannot form an area: they are in a line or too close together.", "ne": "यी बिन्दुले क्षेत्र बनाउन सक्दैनन्: ती एउटै रेखामा वा धेरै नजिक छन्।"},
        "fix": {"en": "Give at least 3 points that go around the area (not in a straight line), or upload a polygon file.",
                "ne": "क्षेत्र घेर्ने कम्तीमा ३ बिन्दु दिनुहोस् (सीधा रेखामा होइन), वा बहुभुज फाइल अपलोड गर्नुहोस्।"},
    },
    "user_group.no_shapefile": {
        "title": {"en": "The ZIP file has no shapefile (.shp) inside.", "ne": "ZIP फाइलभित्र शेपफाइल (.shp) छैन।"},
        "fix": {"en": "Zip together the .shp, .shx, .dbf and .prj files of your layer and upload the ZIP again.",
                "ne": "आफ्नो तहको .shp, .shx, .dbf र .prj फाइल एकैसाथ ZIP गरेर फेरि अपलोड गर्नुहोस्।"},
    },
    "user_group.outside_nepal": {
        "title": {"en": "The coordinates are not in Nepal ({found}).", "ne": "निर्देशाङ्क नेपालभित्र छैनन् ({found})।"},
        "fix": {"en": "Check the projection (CRS) of the file. Nepal is longitude 80 to 88.3 and latitude 26.3 to 30.5; values like 343500 are metres (UTM), not degrees.",
                "ne": "फाइलको प्रक्षेपण (CRS) जाँच गर्नुहोस्। नेपाल देशान्तर ८० देखि ८८.३ र अक्षांश २६.३ देखि ३०.५ मा पर्छ; ३४३५०० जस्ता मान डिग्री होइन, मिटर (UTM) हुन्।"},
    },
    "user_group.no_geometry": {
        "title": {"en": "The file has no usable shapes.", "ne": "फाइलमा प्रयोग गर्न मिल्ने आकृति छैन।"},
        "fix": {"en": "Upload a file with polygons, lines or points that mark the user group area.", "ne": "उपभोक्ता समूहको क्षेत्र जनाउने बहुभुज, रेखा वा बिन्दु भएको फाइल अपलोड गर्नुहोस्।"},
    },
    # ---- field inventory / stem mapping ----------------------------------------------------------------------------------------------
    "field_inventory.required_column_missing": {
        "title": {"en": "The required column \"{found}\" is missing.", "ne": "आवश्यक स्तम्भ \"{found}\" छुटेको छ।"},
        "fix": {"en": "Add a column named \"{found}\" (or a column with that meaning) to your file and upload again.",
                "ne": "आफ्नो फाइलमा \"{found}\" (वा त्यही अर्थको) स्तम्भ थपेर फेरि अपलोड गर्नुहोस्।"},
    },
    # ---- UP-3: smart reading ---------------------------------------------------------------------------------------------------
    "coordinates.utm_converted": {
        "title": {"en": "Your coordinates were in UTM metres (zone {found}N); we converted them to latitude and longitude.", "ne": "तपाईंका निर्देशाङ्क UTM मिटर (क्षेत्र {found}N) मा थिए; हामीले तिनलाई अक्षांश र देशान्तरमा बदल्यौं।"},
        "fix": {"en": "Nothing to do. Check the shape on the map. Next time you can also upload latitude and longitude.", "ne": "केही गर्नुपर्दैन। नक्सामा आकार हेर्नुहोस्। अर्को पटक अक्षांश र देशान्तर पनि अपलोड गर्न सक्नुहुन्छ।"},
    },
    "coordinates.swapped_fixed": {
        "title": {"en": "Latitude and longitude looked swapped; we put them the right way round.", "ne": "अक्षांश र देशान्तर उल्टिएका जस्ता देखिए; हामीले सही क्रममा राख्यौं।"},
        "fix": {"en": "Nothing to do. Check the shape on the map.", "ne": "केही गर्नुपर्दैन। नक्सामा आकार हेर्नुहोस्।"},
    },
    "coordinates.looks_like_utm": {
        "title": {"en": "These coordinates look like UTM metres (zone {found}N), not degrees.", "ne": "यी निर्देशाङ्क डिग्री होइन, UTM मिटर (क्षेत्र {found}N) जस्ता देखिन्छन्।"},
        "fix": {"en": "Choose projection {expected} where you upload, or convert the file to longitude and latitude (WGS84), then upload again.",
                "ne": "अपलोड गर्ने ठाउँमा प्रक्षेपण {expected} छान्नुहोस्, वा फाइललाई देशान्तर र अक्षांश (WGS84) मा बदलेर फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.looks_swapped": {
        "title": {"en": "Longitude and latitude look swapped.", "ne": "देशान्तर र अक्षांश उल्टिएका जस्ता देखिन्छन्।"},
        "fix": {"en": "Put longitude (about 80 to 88) in the longitude column and latitude (about 26 to 30) in the latitude column, then upload again.",
                "ne": "देशान्तर (करिब ८० देखि ८८) देशान्तर स्तम्भमा र अक्षांश (करिब २६ देखि ३०) अक्षांश स्तम्भमा राखेर फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.rows_missing": {
        "title": {"en": "{count} row(s) have no usable coordinates (rows {rows_text}).", "ne": "{count} पङ्क्तिमा प्रयोग गर्न मिल्ने निर्देशाङ्क छैन (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Fill in longitude and latitude for these rows, or delete the rows, then upload again.",
                "ne": "यी पङ्क्तिमा देशान्तर र अक्षांश भर्नुहोस्, वा पङ्क्ति हटाएर फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.stray_points": {
        "title": {"en": "Rows {rows_text} have coordinates in a different form ({found}) from the rest of the file ({expected}).",
                  "ne": "पङ्क्ति {rows_text} का निर्देशाङ्क बाँकी फाइल ({expected}) भन्दा फरक रूप ({found}) मा छन्।"},
        "fix": {"en": "Check these rows: correct the values so they match the others, then upload again.",
                "ne": "यी पङ्क्ति जाँच्नुहोस्: मान सच्याएर बाँकीसँग मिल्ने बनाउनुहोस्, अनि फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.system_mismatch": {
        "title": {"en": "With the coordinate system you chose ({found}), {count} point(s) fall outside Nepal (rows {rows_text}).",
                  "ne": "तपाईंले छानेको निर्देशाङ्क प्रणाली ({found}) अनुसार {count} बिन्दु नेपालबाहिर पर्छन् (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Choose another coordinate system (the numbers look like {expected}), or check the zone with whoever collected the data, then upload again.",
                "ne": "अर्को निर्देशाङ्क प्रणाली छान्नुहोस् (संख्या {expected} जस्ता देखिन्छन्), वा तथ्याङ्क संकलकसँग जोन जाँच गरेर फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.looks_swapped_utm": {
        "title": {"en": "The X column holds 7-digit numbers and the Y column 6-digit ones: easting and northing look swapped.",
                  "ne": "X स्तम्भमा ७ अङ्कका र Y स्तम्भमा ६ अङ्कका संख्या छन्: पूर्वी र उत्तरी निर्देशाङ्क उल्टिएका जस्ता देखिन्छन्।"},
        "fix": {"en": "Put the 6-digit easting in the X (longitude) column and the 7-digit northing in the Y (latitude) column, then upload again.",
                "ne": "६ अङ्कको पूर्वी निर्देशाङ्क X (देशान्तर) स्तम्भमा र ७ अङ्कको उत्तरी निर्देशाङ्क Y (अक्षांश) स्तम्भमा राखेर फेरि अपलोड गर्नुहोस्।"},
    },
    "field_inventory.height_in_feet": {
        "title": {"en": "The {found} look like feet, not metres (a typical value is {expected} m if converted).",
                  "ne": "{found} मिटर होइन, फुट जस्ता देखिन्छन् (बदल्दा सामान्य मान {expected} मि.)।"},
        "fix": {"en": "If the heights are in feet, convert them to metres (divide by 3.28) and upload again. If they really are metres, you can ignore this.",
                "ne": "उचाइ फुटमा भए मिटरमा बदल्नुहोस् (३.२८ ले भाग गर्नुहोस्) र फेरि अपलोड गर्नुहोस्। साँच्चै मिटर नै भए यसलाई बेवास्ता गर्न सक्नुहुन्छ।"},
    },
    "user_group.far_from_forest": {
        "title": {"en": "The user group you uploaded lies about {found} km from the forest boundary.", "ne": "तपाईंले अपलोड गरेको उपभोक्ता समूहको क्षेत्र वन सीमाबाट करिब {found} कि.मी. टाढा छ।"},
        "fix": {"en": "If this is not intended, check the file's coordinates (projection, swapped columns) and upload it again. The group was saved as uploaded.",
                "ne": "यो जानाजानी होइन भने फाइलका निर्देशांक (प्रोजेक्सन, साटिएका स्तम्भ) जाँचेर फेरि अपलोड गर्नुहोस्। समूह अपलोड गरेकै रूपमा सुरक्षित गरिएको छ।"},
    },
    "field_inventory.dbh_in_mm": {
        "title": {"en": "The {found} look like millimetres, not centimetres (a typical value is {expected} cm if divided by 10).",
                  "ne": "{found} सेन्टिमिटर होइन, मिलिमिटर जस्ता देखिन्छन् (१० ले भाग गर्दा सामान्य मान {expected} से.मी.)।"},
        "fix": {"en": "Convert the diameters to centimetres (divide by 10) and upload again.", "ne": "व्यास सेन्टिमिटरमा बदल्नुहोस् (१० ले भाग गर्नुहोस्) र फेरि अपलोड गर्नुहोस्।"},
    },
    "field_inventory.species_suggestion": {
        "title": {"en": "{count} species names are not in our species list: {found}.", "ne": "{count} प्रजातिको नाम हाम्रो प्रजाति सूचीमा छैन: {found}।"},
        "fix": {"en": "Check the spelling against the suggestion shown, or use the scientific name. Other names are still imported as written.",
                "ne": "देखाइएको सुझावसँग हिज्जे जाँच गर्नुहोस्, वा वैज्ञानिक नाम प्रयोग गर्नुहोस्। अन्य नाम लेखिएकै रूपमा प्रविष्ट हुन्छन्।"},
    },
    "household.headers_not_recognised": {
        "title": {"en": "These columns were not understood and were left out: {found}.", "ne": "यी स्तम्भ बुझिएनन् र छोडिए: {found}।"},
        "fix": {"en": "Rename them as in the template if they hold household data, or ignore this if they are your own notes.",
                "ne": "यिनमा घरधुरी तथ्याङ्क छ भने टेम्प्लेटमा जस्तै नाम दिनुहोस्, तिनी तपाईंका आफ्नै टिपोट हुन् भने बेवास्ता गर्नुहोस्।"},
    },
    "household.headers_not_found": {
        "title": {"en": "We could not find the household column names in the first rows of the file. The columns we saw: {found}.", "ne": "फाइलका पहिलो केही पङ्क्तिमा घरधुरीका स्तम्भका नाम भेटिएन। हामीले देखेका स्तम्भ: {found}।"},
        "fix": {"en": "Use the household template (download it above): its column names must be on one of the first rows.", "ne": "घरधुरी टेम्प्लेट प्रयोग गर्नुहोस् (माथिबाट डाउनलोड गर्नुहोस्): यसका स्तम्भका नाम पहिलो केही पङ्क्तिमध्ये एकमा हुनुपर्छ।"},
    },
    "household.committee_not_imported": {
        "title": {"en": "The committee sheet \"{found}\" could not be read, so its members were not imported. The households were imported.", "ne": "समिति पाना \"{found}\" पढ्न सकिएन, त्यसैले यसका सदस्य आयात भएनन्। घरधुरी आयात भए।"},
        "fix": {"en": "Check that the sheet follows the template (same column names, one member per row), then upload the file again.", "ne": "पाना टेम्प्लेट अनुसार छ कि (उही स्तम्भका नाम, प्रति पङ्क्ति एक सदस्य) जाँच गर्नुहोस्, अनि फाइल फेरि अपलोड गर्नुहोस्।"},
    },
    "household.header_row_found": {
        "title": {"en": "Your column names were found on row {found}.", "ne": "तपाईंका स्तम्भका नाम पङ्क्ति {found} मा भेटिए।"},
        "fix": {"en": "Nothing to do. The households were read from the rows below it.", "ne": "केही गर्नुपर्दैन। घरधुरी त्यसको तलका पङ्क्तिबाट पढिए।"},
    },
    "field_inventory.columns_renamed": {
        "title": {"en": "We read these columns under the template's names: {found}.", "ne": "यी स्तम्भलाई हामीले टेम्प्लेटका नाममा पढ्यौँ: {found}।"},
        "fix": {"en": "Nothing to do if this is right. If a column was read wrongly, rename it to the template name and upload again.", "ne": "यो ठीक छ भने केही गर्नुपर्दैन। कुनै स्तम्भ गलत पढिएको भए टेम्प्लेटको नाममा परिवर्तन गरेर फेरि अपलोड गर्नुहोस्।"},
    },
    "field_inventory.units_converted": {
        "title": {"en": "Units written in your column names were applied: {found}.", "ne": "तपाईंका स्तम्भका नाममा लेखिएका एकाइ लागू गरियो: {found}।"},
        "fix": {"en": "Nothing to do if the units in the column names are right. Diameters are stored in cm and heights in m; if a unit was written wrongly, correct the column name and upload again.",
                "ne": "स्तम्भका नामका एकाइ ठीक छन् भने केही गर्नुपर्दैन। व्यास से.मी. र उचाइ मिटरमा राखिन्छ; एकाइ गलत लेखिएको भए स्तम्भको नाम सच्याएर फेरि अपलोड गर्नुहोस्।"},
    },
    "field_inventory.corrections_proposed": {
        "title": {"en": "{count} value(s) were refused (rows {rows_text}). Replacements inside each column's own size class are proposed below.",
                  "ne": "{count} मान अस्वीकृत भए (पङ्क्ति {rows_text})। प्रत्येक स्तम्भको आफ्नै आकार वर्गभित्रका प्रतिस्थापन तल प्रस्ताव गरिएका छन्।"},
        "fix": {"en": "Review the proposed values. Apply them to import now, or correct your file yourself and upload again. A value that belongs to another class (a pole of 50 cm is a tree) is better moved to that class's columns.",
                "ne": "प्रस्तावित मान हेर्नुहोस्। अहिले आयात गर्न लागू गर्नुहोस्, वा आफ्नो फाइल आफैँ सच्याएर फेरि अपलोड गर्नुहोस्। अर्को वर्गमा पर्ने मान (५० से.मी.को खाँवा रुख हो) त्यही वर्गका स्तम्भमा सार्नु राम्रो।"},
    },
    "field_inventory.corrections_applied": {
        "title": {"en": "{count} refused value(s) were replaced with the proposed values: {found}.", "ne": "{count} अस्वीकृत मान प्रस्तावित मानले बदलिए: {found}।"},
        "fix": {"en": "Nothing to do if you accepted them. Your original file is unchanged.", "ne": "तपाईंले स्वीकार गर्नुभएको हो भने केही गर्नुपर्दैन। तपाईंको मूल फाइल जस्ताको तस्तै छ।"},
    },
    "field_inventory.species_resolved": {
        "title": {"en": "{count} species given as a code or a local name were read as scientific names: {found}.", "ne": "कोड वा स्थानीय नाममा दिइएका {count} प्रजाति वैज्ञानिक नामका रूपमा पढिए: {found}।"},
        "fix": {"en": "Nothing to do. Check the list; next time you can write the scientific name.", "ne": "केही गर्नुपर्दैन। सूची जाँच्नुहोस्; अर्को पटक वैज्ञानिक नाम लेख्न सक्नुहुन्छ।"},
    },
    "field_inventory.stand_types_found": {
        "title": {"en": "Stand types found in the file: {found}.", "ne": "फाइलमा भेटिएका स्ट्यान्ड प्रकार: {found}।"},
        "fix": {"en": "Nothing to do. Stand types with no columns in the file are simply not part of this inventory.",
                "ne": "केही गर्नुपर्दैन। फाइलमा स्तम्भ नभएका स्ट्यान्ड प्रकार यो इन्भेन्टरीमा समावेश हुँदैनन्।"},
    },
    # ---- forest details ---------------------------------------------------------------------------------------------------------
    "forest_metadata.nothing_found": {
        "title": {"en": "No forest details were found in the file.", "ne": "फाइलमा वनको विवरण भेटिएन।"},
        "fix": {"en": "Use the Forest_Metadata template: one row under the column names (forest_name, group_name, province, district ...), then upload again.",
                "ne": "Forest_Metadata टेम्प्लेट प्रयोग गर्नुहोस्: स्तम्भका नामको तल एउटा पङ्क्ति (forest_name, group_name, province, district ...), अनि फेरि अपलोड गर्नुहोस्।"},
    },
    "forest_metadata.several_rows": {
        "title": {"en": "The file has {count} filled rows; only the first (row {found}) was used.", "ne": "फाइलमा {count} भरिएका पङ्क्ति छन्; पहिलो (पङ्क्ति {found}) मात्र प्रयोग गरियो।"},
        "fix": {"en": "A forest has one set of details. Keep one row.", "ne": "एउटा वनको विवरण एउटै हुन्छ। एउटा पङ्क्ति मात्र राख्नुहोस्।"},
    },
    "forest_metadata.too_long": {
        "title": {"en": "The value of {found} is longer than {expected} characters (row {rows_text}).", "ne": "{found} को मान {expected} अक्षरभन्दा लामो छ (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Shorten the value and upload again.", "ne": "मान छोटो बनाएर फेरि अपलोड गर्नुहोस्।"},
    },
    "forest_metadata.fy_order": {
        "title": {"en": "The plan starts after it ends ({found}).", "ne": "योजना सकिएपछि सुरु हुन्छ ({found})।"},
        "fix": {"en": "Check fy_start and fy_end (for example 2083/84 and 2092/93), then upload again.", "ne": "fy_start र fy_end जाँच्नुहोस् (जस्तै २०८३/८४ र २०९२/९३), अनि फेरि अपलोड गर्नुहोस्।"},
    },
    "forest_metadata.imported": {
        "title": {"en": "{count} forest detail(s) were saved: {found}. Details the file left empty keep their saved value.", "ne": "वनका {count} विवरण सुरक्षित गरियो: {found}। फाइलमा खाली विवरणले आफ्नो सुरक्षित मान राख्छ।"},
        "fix": {"en": "Nothing to do. Check them in Forest details.", "ne": "केही गर्नुपर्दैन। 'वनको विवरण' मा जाँच्नुहोस्।"},
    },
    # ---- declared coordinate system ----------------------------------------------------------------------------------------------
    "coordinates.declared_mixed": {
        "title": {"en": "The file declares more than one coordinate system ({found}).", "ne": "फाइलले एकभन्दा बढी निर्देशाङ्क प्रणाली ({found}) घोषणा गरेको छ।"},
        "fix": {"en": "Use one value in the coordinate_system_epsg column on every row, then upload again.",
                "ne": "प्रत्येक पङ्क्तिको coordinate_system_epsg स्तम्भमा एउटै मान राखेर फेरि अपलोड गर्नुहोस्।"},
    },
    "coordinates.declared_unsupported": {
        "title": {"en": "The file declares EPSG:{found}, which is not supported yet.", "ne": "फाइलले EPSG:{found} घोषणा गरेको छ, जुन अहिले समर्थित छैन।"},
        "fix": {"en": "Use 4326, 32644 or 32645, or convert the coordinates and upload again.",
                "ne": "4326, 32644 वा 32645 प्रयोग गर्नुहोस्, वा निर्देशाङ्क बदलेर फेरि अपलोड गर्नुहोस्।"},
    },
    # ---- sample plots ------------------------------------------------------------------------------------------------------------
    "sample_plots.coordinates_not_degrees": {
        "title": {"en": "{count} sample plot(s) have coordinates that are not in Nepal (rows {rows_text}).", "ne": "{count} नमुना प्लटका निर्देशाङ्क नेपालभित्र पर्दैनन् (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Check these rows (longitude about 80 to 88, latitude about 26 to 30), or state the coordinate system, then upload again.",
                "ne": "यी पङ्क्ति जाँच्नुहोस् (देशान्तर करिब ८० देखि ८८, अक्षांश करिब २६ देखि ३०), वा निर्देशाङ्क प्रणाली जनाएर फेरि अपलोड गर्नुहोस्।"},
    },
    "sample_plots.number_invalid": {
        "title": {"en": "{count} row(s) have a plot number that is not a whole number of 1 or more (rows {rows_text}).", "ne": "{count} पङ्क्तिको प्लट नम्बर १ वा सोभन्दा ठूलो पूर्णाङ्क होइन (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Give each plot a whole number, or delete the plot_number column to number them in file order.",
                "ne": "प्रत्येक प्लटलाई पूर्णाङ्क दिनुहोस्, वा फाइलको क्रममा नम्बर दिन plot_number स्तम्भ हटाउनुहोस्।"},
    },
    "sample_plots.number_duplicated": {
        "title": {"en": "These plot numbers appear more than once: {found} (rows {rows_text}).", "ne": "यी प्लट नम्बर एकभन्दा बढी पटक छन्: {found} (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Each plot needs its own number. Correct the repeated numbers and upload again.", "ne": "प्रत्येक प्लटको आफ्नै नम्बर चाहिन्छ। दोहोरिएका नम्बर सच्याएर फेरि अपलोड गर्नुहोस्।"},
    },
    "sample_plots.numbers_not_consecutive": {
        "title": {"en": "The plot numbers run {found}, but {count} plots need the numbers {expected} with none missing.", "ne": "प्लट नम्बर {found} छन्, तर {count} प्लटलाई बीचमा नछुटाई {expected} नम्बर चाहिन्छ।"},
        "fix": {"en": "Renumber the plots 1 to {count} in order, or let us do it. Field inventory rows refer to plots by number, so check them after renumbering.",
                "ne": "प्लटलाई क्रमशः १ देखि {count} सम्म पुन:नम्बर दिनुहोस्, वा हामीलाई गर्न दिनुहोस्। इन्भेन्टरी पङ्क्तिहरूले नम्बरले प्लट जनाउँछन्, त्यसैले पुन:नम्बर पछि जाँच्नुहोस्।"},
    },
    "sample_plots.renumbered": {
        "title": {"en": "{count} plot(s) were renumbered in order: {found}.", "ne": "{count} प्लटलाई क्रमानुसार पुन:नम्बर दिइयो: {found}।"},
        "fix": {"en": "Use the new numbers in your field inventory file.", "ne": "आफ्नो इन्भेन्टरी फाइलमा नयाँ नम्बर प्रयोग गर्नुहोस्।"},
    },
    "sample_plots.numbered_in_file_order": {
        "title": {"en": "The file has no plot numbers; the {count} plots were numbered in file order.", "ne": "फाइलमा प्लट नम्बर छैन; {count} प्लटलाई फाइलको क्रममा नम्बर दिइयो।"},
        "fix": {"en": "Nothing to do.", "ne": "केही गर्नुपर्दैन।"},
    },
    "sample_plots.outside_forest": {
        "title": {"en": "{count} sample plot(s) lie outside the forest (rows {rows_text}).", "ne": "{count} नमुना प्लट वनबाहिर पर्छन् (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Check these coordinates and the coordinate system, then upload again.", "ne": "यी निर्देशाङ्क र निर्देशाङ्क प्रणाली जाँचेर फेरि अपलोड गर्नुहोस्।"},
    },
    "sample_plots.block_differs": {
        "title": {"en": "{count} plot(s) lie in a different block than the file says ({found}).", "ne": "{count} प्लट फाइलमा लेखिएभन्दा फरक ब्लकमा पर्छन् ({found})।"},
        "fix": {"en": "The block where the plot lies was used. Correct the file if the coordinates are wrong.", "ne": "प्लट पर्ने ब्लक प्रयोग गरियो। निर्देशाङ्क गलत भए फाइल सच्याउनुहोस्।"},
    },
    "sample_plots.radius_invalid": {
        "title": {"en": "{count} row(s) have a plot radius outside 1 to 50 m (rows {rows_text}).", "ne": "{count} पङ्क्तिको प्लट त्रिज्या १ देखि ५० मि. बाहिर छ (पङ्क्ति {rows_text})।"},
        "fix": {"en": "Enter the radius in metres (a 500 m² circle is 12.62 m), then upload again.", "ne": "त्रिज्या मिटरमा लेख्नुहोस् (५०० वर्ग मि. को वृत्त १२.६२ मि.), अनि फेरि अपलोड गर्नुहोस्।"},
    },
    "sample_plots.radius_differs": {
        "title": {"en": "The plots have different radii ({expected}); one radius, {found} m, is used for all.", "ne": "प्लटहरूको त्रिज्या फरक छ ({expected}); सबैका लागि एउटै त्रिज्या {found} मि. प्रयोग गरियो।"},
        "fix": {"en": "A sampling design stores one radius. Use the same radius on every row.", "ne": "नमुना डिजाइनले एउटै त्रिज्या राख्छ। प्रत्येक पङ्क्तिमा उही त्रिज्या राख्नुहोस्।"},
    },
}

# severity applied when a caller does not pass one
_DEFAULT_SEVERITY = {"field_inventory.species_resolved": "info", "forest_metadata.imported": "info", "forest_metadata.several_rows": "warning", "sample_plots.renumbered": "info", "sample_plots.numbered_in_file_order": "info", "sample_plots.block_differs": "warning",
                     "sample_plots.radius_differs": "warning", "file.corrupt": "error", "household.row_invalid": "warning", "household.duplicate_house_no": "warning",
                     "field_inventory.stand_types_found": "info", "coordinates.utm_converted": "info", "coordinates.stray_points": "warning", "coordinates.system_mismatch": "error", "coordinates.swapped_fixed": "info",
                     "household.header_row_found": "info", "field_inventory.columns_renamed": "info", "field_inventory.corrections_applied": "info", "field_inventory.corrections_proposed": "error", "field_inventory.units_converted": "info", "user_group.far_from_forest": "warning", "field_inventory.height_in_feet": "warning", "household.committee_not_imported": "warning", "field_inventory.species_suggestion": "warning", "household.headers_not_recognised": "warning"}


@dataclass
class UploadFinding:
    code: str
    severity: str  # error | warning | info
    title_en: str
    title_ne: str
    fix_en: str
    fix_ne: str
    where: Dict[str, Any] = field(default_factory=dict)
    found: str = ""
    expected: str = ""
    auto_fix: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _fmt(template: str, fields: Dict[str, Any]) -> str:
    # str.format with missing keys left visible would leak "{x}" to the user; fill unknown ones with an empty string instead
    return re.sub(r"\{(\w+)\}", lambda m: str(fields.get(m.group(1), "")), template)


def _rows_text(rows: List[int], limit: int = 12) -> str:
    shown = ", ".join(str(r) for r in rows[:limit])
    return shown + (f" … (+{len(rows) - limit})" if len(rows) > limit else "")


def finding(code: str, *, severity: Optional[str] = None, found: Any = "", expected: Any = "", rows: Optional[List[int]] = None,
            count: Optional[int] = None, auto_fix: Optional[str] = None, **where: Any) -> UploadFinding:
    """Build a finding from the catalogue. Unknown codes are a programming error (the catalogue test keeps the list honest)."""
    entry = CATALOGUE[code]
    fields: Dict[str, Any] = {"found": found, "expected": expected, "count": count if count is not None else (len(rows) if rows else ""),
                              "rows_text": _rows_text(rows or [])}
    w = {k: v for k, v in where.items() if v not in (None, "")}
    if rows:
        w["rows"] = list(rows)
    return UploadFinding(
        code=code,
        severity=severity or _DEFAULT_SEVERITY.get(code, "error"),
        title_en=_fmt(entry["title"]["en"], fields),
        title_ne=_fmt(entry["title"]["ne"], fields),
        fix_en=_fmt(entry["fix"]["en"], fields),
        fix_ne=_fmt(entry["fix"]["ne"], fields),
        where=w,
        found=str(found) if found != "" else "",
        expected=str(expected) if expected != "" else "",
        auto_fix=auto_fix,
    )


def upload_error(status_code: int, *findings: UploadFinding) -> HTTPException:
    """The HTTPException an upload endpoint raises: ``detail = {code, message, message_np, findings}`` (readDetail-compatible).

    ``message`` / ``message_np`` read as "<what is wrong> <how to fix>" so a screen that shows only the message is still useful."""
    first = findings[0]
    return HTTPException(
        status_code=status_code,
        detail={
            "code": first.code,
            "message": f"{first.title_en} {first.fix_en}".strip(),
            "message_np": f"{first.title_ne} {first.fix_ne}".strip(),
            "findings": [f.to_dict() for f in findings],
        },
    )
