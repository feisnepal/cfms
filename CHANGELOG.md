# CHANGELOG - Purpose-First Geometry Import Feature

All notable changes to the Purpose-First Geometry Import feature.

## [Unreleased]

### Forest summary panel and plan decisions — release notes
*Owner's request, 2026-10-09: a forest-wide summary in the map workspace, readable by village users, DFOs and ministry or NGO staff. Plan: `FOREST_SUMMARY_PANEL_PLAN.md`.*
- **A floating Forest summary panel** over the map: drag it by its header (or the arrow keys), collapse it, close it, reopen it from the Analysis maps group; it stays on top of the map and other panels, and its place is remembered per user and forest. It follows the Forest / User group choice.
- **What it shows:** one sentence about the forest, eight headline figures (area, growing stock, carbon, CO₂e, allowable harvest, good-condition share, relatively-high landslide share, species) and five themes. Every figure is the Operational Plan's own, so the panel and the document cannot disagree. Anything not yet computed says so and names the step; nothing is guessed. Landslide classes are labelled *relative* everywhere.
- **Decisions needed tab:** the landslide-class method, each block's management orientation (when it differs from the suggestion) and how households are placed. The owner, a DFO of the owner's organisation, or a super admin can answer; each answer records who and when. Decisions are read-only once the DFO has approved the map (and while it is being calculated); only a super admin can unlock.
- **Step 12 (Sustainable FM)** shows "n plan decisions are still open" with a button to the panel. It never blocks the step.
- **The OP document** states the landslide decision (kept relative, or calibration requested) in its methodology.
- **Plain-text export** (Copy text / Download .txt) in English or Nepali, the same figures and wording as the panel, for readers outside the workspace.
- **Under the hood:** migration `116` (`forest_decisions`), `GET/PUT /calculations/{id}/decisions`, `GET /calculations/{id}/forest-summary`, `POST .../forest-summary/refresh`, `GET .../forest-summary/export`. A DFO's access is scoped to their own organisation (the older DFO approve/reject checks are not scoped; unchanged here). Both block-edit routes now write a block's orientation through one shared helper.

### Field book: the outer boundary first, internal boundaries after, each point says what it separates — release notes
*Owner's specification, 2026-10-04: outer points first in one direction, remarked `outer` with the unit(s) they separate; internal points remarked with every unit sharing them (2, 3 or more).*
- **Outer boundary first, clockwise, from the north-west-most vertex.** Outer points are labelled `O1, O2, …`; internal points follow as `I1, I2, …`. Spacing is the 50 m tape from the previous point. Sub-areas (excluded land and similar) take part in the same book.
- **Every point records what it separates.** The `remarks` text reads `outer: ब्लक १, ब्लक २` or `internal (junction of 3): A, B, C`; the structured fields are `boundary_class`, `junction_degree`, `is_junction`, `adjacent_units`, `next_point_label` (migration `110_add_fieldbook_boundary_class`). A surveyor's own remark edit does not touch the classification.
- **A walkable route.** Each point's azimuth/distance now lead to the point named in `next_point_label`. Before, 36 of 305 steps in a five-compartment forest pointed somewhere other than the next number.
- **A shared edge is generated once.** Each unit used to measure its own 50 m from its own corner, so a shared edge got two sets of points that never coincided (48 near-duplicate pairs in the same forest, now 0). A three-way point where one unit has no vertex (a T-junction) is now found.
- **Exports.** CSV/Excel/GPX/GeoJSON carry the label, outer/internal, junction, adjacent units and next point; Excel gains a `Junctions` sheet and shades outer and junction rows; the summary reports the outer perimeter.
- **Fixed in the CSV:** a debug column (`TEST_NEW_CODE_LOADED = YES`) on every row, latitude and longitude under each other's heading, and an azimuth/distance of exactly 0 shown as blank.
- **The Field Book tab and map layer** show the label, an outer/internal badge, the junction marker, the units a point separates and the next point, with All / Outer / Internal / Junctions filters.
- **Points are grouped into lines, so nothing has to guess which to join.** The outer points form ONE closed line (`O-1`; its last point connects back to the first, so it draws as a polygon outline). Each internal edge is its own OPEN line (`I-1`, `I-2`, …): it never closes and never joins another edge, even though `I5` and `I6` can be the end of one edge and the start of a different one. A junction belongs to every line that meets there. The one internal exception is a free-standing loop with no ends, such as a sub-area inside a unit (`L-1`), which is closed because it is a polygon. Stored as `line_id` and `lines` (migration `111_add_fieldbook_lines`).
- **Lines are drawn.** On the map the outer outline is a solid blue closed line and internal edges are dashed violet open lines; markers now read `O1` / `I7` (internal points are violet, junctions have an amber ring). GeoJSON gains `LineString` features (`closed: true` for the outer ring, `false` for internal edges), GPX gains one `<rte>` per line (only the outer one repeats its first point), and Excel gains a `Lines` sheet listing each line, whether it closes, its length and its point sequence.
- **Hairline slivers no longer double an edge.** Two neighbours whose shared edge differs by a few centimetres used to come out as two parallel edges; neighbouring outlines are now welded (up to ~3 cm). On the test forest this turned 20 lines into 11.
- **One column says what a point is, and every output shows the same row.** The `Block`, `Separates` and `Remark` columns all said the same thing, so only **Remark** is shown (`outer: ब्लक १, ब्लक २`, `internal (junction of 3): A, B, C`); the structured fields (`adjacent_units`, `block_name`, `lines`) stay in the database and the API. The Field Book tab, CSV, Excel, GeoJSON, GPX and the `{{fieldbook_points}}` document table are all built from one definition (`services/fieldbook_record.py`), so they can no longer disagree. Fixed on the way: the tab searched for the nearest ridge/river within a 100 m buffer and the files within 200 m (the same point could name different features); a distance was truncated in the CSV and rounded in the tab; GeoJSON and GPX left the nearby feature out. `tests/services/test_fieldbook_consistency.py` generates one book and checks every format against the same row. **Breaking for anyone reading the files:** CSV/Excel no longer have `Block No`, `Block Name` or `Adjacent Units` columns (use `Remarks`); GeoJSON properties are now the same keys as the CSV columns (`point`, `boundary`, `remarks`, …) and `properties.layer` is `point` or `line`; the document table's `ब्लकको_नाम` column became `कैफियत`.
- **A field note can no longer wipe out the units.** Saving a remark through the API adds the note after the generated text (`outer: Block-1; stone pillar`); clearing it restores the generated text.
- **Existing field books are not rewritten.** They keep their `P1…Pn` numbers and show without the new columns until regenerated. The geometry is `services/fieldbook_sequence.py`.

### The Sub-compartment / Sub-block layer now shows every unit that is not divided further — release notes
*Owner's rule, 2026-10-03: the sub-compartment total always equals the compartment total, which always equals the forest outer-boundary area. Plan: `SUBCOMPARTMENT_LAYER_TRACKER.md`.*
- **What you see.** The Sub-Compartments layer lists every undivided unit of the forest: the children of a divided compartment, plus the compartments that were never divided (परिक्षण: 8 rows, 129.75 ha, instead of 5). A divided compartment is replaced by its children and is never listed beside them, so the layer never counts ground twice. The Sub-Blocks layer works the same way for blocks. Editing, renaming and deleting an undivided unit works the same from either layer (it is one record shown in two places). Moving its corner points is still done in the Compartments / Blocks layer.
- **Selecting a feature in one layer now highlights its attribute-table row in the other.**
- **Fixed — five ways the area rule could be broken.** Found by a new test suite that applies every operation to a forest and checks that the undivided units still tile the boundary exactly once: (1) *Polygon from points* on a block/compartment/sub-block/sub-compartment layer inserted the polygon as it was, overlapping neighbours and sticking out of the boundary — it now carves its ground out of the unit it lies in, like Paste; (2) *Paste into a sub layer* covered only part of its parent and left the rest uncovered — the rest now becomes a remainder sub-unit; (3) *Pasting over a divided unit* shrank the unit but not its own sub-units, which then overlapped the pasted one — they now shrink with it; (4) *Undo of a delete* put the unit back on top of the Remainder the delete had created — the restored unit now takes its ground back; (5) *Assigning an Auto-Block layer as sub-units* when the layer reached only part of the parent left a gap — the rest becomes a remainder sub-unit.
- **A blank/"Remainder" unit can appear** after these operations when only part of a unit was covered. That is intended: it is the ground nothing else claims, and it keeps the totals equal.
- **Fixed — editing a promoted Auto-Block layer, then demoting it, left orphan units and blocked the layer.** Equal-area divide, cut, merge and top-level paste on a unit that belonged to a layer made new units with no layer. Demoting the layer then left those units visible as orphans (children of a hidden parent), and promoting again was refused with "This forest already has blocks/compartments created before layers existed". New units now inherit their source unit's layer, so demote hides the whole set and promote brings it back. The message now says what it means (units that belong to no layer: drawn, imported, or made before layers existed). `backend/scripts/backfill_layer_descendants.py` repairs forests already in that state (dry run by default; `--apply` writes an undo file; `--rollback FILE` undoes it).
- **Forests created before this system** (e.g. DBG, बृन्दाबन) do not satisfy the rule and are not changed; the layer shows their units as they are. `backend/scripts/report_unit_coverage.py` lists which forests tile their boundary.

### Deleting a forest now deletes everything that belongs to it (replaces the "archive" rule)
*Owner's rule, 2026-09-21: if a forest is deleted, all data associated with it is deleted. This replaces the 2026-08-27 rule that archived a deleted forest and destroyed nothing.*
- **No archive any more.** Deleting a forest no longer copies it into `deleted_calculations`. The module that wrote the archive (`services/calculation_archive.py`) and its tests were removed. **On the owner's instruction ("delete them all") the 79 records already in the archive — copies of forests deleted between 2026-08-27 and 2026-09-17 — were deleted, and so were the archive table (migration `093_drop_deleted_calculations`; `downgrade` recreates it empty), the `DeletedCalculation` model and the two super-admin endpoints that listed and exported it (`GET /api/v1/calculations/archived`, `.../archived/{id}/export`).** Nothing in the frontend used them.
- **Migration `092_forest_delete_cascades`.** 30 of the 33 links to a forest already cascaded; the rest did not, and that is how 77,560 trees outlived their forests. Now `inventory_calculations` and `field_inventory_calculations` **cascade and are `NOT NULL`** (an inventory can no longer exist without a forest), `transactions` cascades (it would have blocked a delete), and `op_data_cache` gets a real foreign key with cascade. A working `downgrade` is included.
- **Files go with the forest.** New `services/forest_purge.py` removes the export files and the per-forest cache folders (`maps_cache`, `soil_erosion_cache`, `hazard_vuln_cache`) — after the delete has committed, so a failed delete never loses a file.
- **A tree inventory must name a forest.** `POST /api/inventory/upload` and `/confirm-mapping` answer **422** (bilingual) without one, 404 for a forest that does not exist, 403 for someone else's. The upload page's optional free-text "boundary link" is now a required list of your own forests.
- **Guarded against regression.** `tests/test_forest_delete_removes_everything.py` builds a forest with data in every kind of table, walks the live foreign-key graph, deletes it through the API and asserts that not one row or folder survives (and that another forest is untouched); `tests/test_forest_delete_schema_rule.py` fails if any link to a forest stops cascading or a `calculation_id` column has no foreign key. Two tables are documented exceptions kept on purpose (`document_issuances` — append-only provenance; `household_access_log` — audit trail), listed in `app/core/forest_delete_rules.py`.
- **New read-only tool** `backend/scripts/report_orphans.py` lists any leak (non-cascading links, rows with no forest, stray folders). On the development database it reports clean.

### Yearly activities — release notes (P0a–P6): what changes for you
*Each visible change, separately, as the plan asks. The details are in the phase entries below.*
- **A year can now be 0.** Quantity 0 and budget 0 means *nothing is planned that year* (a dimmed dash); 0 in only one of the two is a real, chosen value (voluntary work; money with no countable output). Before, a 0 could not be saved and was quietly turned back into a number.
- **The plan is planned from the map or from the yearly-activities pages, the same way.** A guided card adds an activity one question at a time; you can find any activity by typing a word in Nepali or English; numbers save at once with Undo; there is no "Save All".
- **The first number you type for an activity is used for every year that still has the starting value** (never a year you changed, never a 0) — and the screen says so.
- **Only the owner of a forest plans its yearly activities** — a super-admin is not the owner and sees a plain message.
- **The "before we create your plan" check** lists what is unfinished (starting numbers, no place, an out-of-date cost-benefit analysis) before a plan document is created or a file is exported. It only warns; you decide.
- **The yearly-plan CSV changed:** column headings follow the language you use; quantities are no longer rounded to whole numbers; activities that need no map have an empty location; an activity with a place drawn now says where the place is (or "Drawn on the map") instead of "No specific location".
- **The cost-benefit analysis follows the plan more closely.** A cost row is written for each run of equal yearly budgets (so costs are counted in the years they are spent, not spread over ten), and an activity set to 0 no longer keeps a stale cost row. **The NPV / IRR / payback of an existing scenario therefore change once, more accurately, the next time you press *Auto-populate*.** A banner on the cost-benefit tab says when the plan changed after the analysis.
- **Fixed in the operational plan document:** the variables *Total budget per year* (`ya_total_budget_by_year`) and *Budget trend by year* (`ya_budget_year_trend`) listed only year 10 instead of all ten years. Plan documents made before this fix have them wrong; regenerate to correct them.

### Map workspace — divide a selected block / compartment by a natural feature
- **"Auto-create" is still once-only** (it builds the *first* set of blocks / compartments and is switched off once any exist). New: right-click **Compartments** (to divide a selected **block**) or **Sub-compartments** (to divide a selected **compartment**) → **Divide by natural feature…**. It opens the same designer on that one feature, with the same four bases — **rivers & ridges, slope, aspect, canopy height** — and the same slider, lock, merge and minimum-area controls; **Create** saves the pieces as its children (`Block-1-C1…`, `C-1-SC1…`).
- Each child records its **own** dominant slope / aspect / canopy class and river-ridge name. Private land and protection units stay a permanent hole, exactly as in the equal-area divide, and the pieces are clipped to the chosen feature even if the request says otherwise.
- **Every block may be divided**, each on its own basis (the equal-area divide still lets only one block own compartments; this action does not). What still holds: a feature that already has children must have them deleted first, no compartments once a sampling design exists, and nothing changes when the structure is locked. Because the forest analysis uses compartments as soon as any exist, saving a division warns how many blocks still have no compartments — they are left out of the analysis until divided too. Children smaller than 1 ha are absorbed (changeable with the minimum-area box).
- Backend: `POST /calculations/{id}/blocks/{feature_id}/auto-divide/preview` and `.../commit`. No migration.

### Yearly activities — the map's "Next step" bar follows its layer
- The **Next step** bar on the map workspace now appears only while the **Activity Features** layer is the active one and is ticked on; on any other layer the map is not crowded by it. The header **Yearly plan** button and the plan view still open the plan and the guided *Add activity* card from any layer.

### Yearly activities — P6: check before creating, quantity from the drawing, and the numbers agree (plan §4.3, §5.4)
- **A "before we create your plan" check** appears before an operational plan document is created (from the template page and the plan page) and before either yearly-plan CSV is exported. It lists each unfinished activity with its reason and an *Open* button, plus an empty plan or an out-of-date cost-benefit analysis. *Go back and fix* or *Create the plan anyway* / *Export anyway* — it never blocks.
- **The quantity the drawn places measure is offered** under an activity's usual quantity (*Drawn on the map: 2.35 km — Use this*): hectares of areas, kilometres of lines, or the number of places. It is only shown when it differs from the quantity, and never applied unless you press *Use this*.
- A live end-to-end check proves that one edit made in the browser gives the same total in the plan, the table, the CSV export and the operational plan's own variables.

### Yearly activities — P5: one planner on the yearly-activities pages (plan §4.9, §5.3)
- **Both yearly-activities screens (the page and the Reports tab) now open on "Your plan"** — the same editable table as on the map. **There is no "Save All":** each change saves at once, with *Undo*, and a change made elsewhere (the map, another tab) is never overwritten — a stale save is refused with a plain explanation and the table shows what is there now.
- **"Browse all activities"** is the finder (search in Nepali or English, browse by group, filters). **Adding an activity uses the same questions as the map**; an activity that needs no map goes straight in. Places are drawn on the map — the pages offer *Edit on map*, and the map's plan table offers *Open full plan*.
- **Where an activity applies** is chosen in one dialog: the whole forest, or chosen blocks / compartments / sub-areas. The dialog now lists the forest's real blocks and compartments (it could not before), choosing "all blocks" makes the table say *Whole forest*, and chosen blocks are named in the table and no longer trigger "has no place on the map yet".
- The page's totals and the charts that preview the operational plan are read from the same numbers the table shows.

### Yearly activities — P4: the yearly plan as a table on the map
- **A "Places on the map / Yearly plan" switch above the map's table** (shown while the Activity Features layer is active). *Yearly plan* lists one row per activity in the plan — including activities that need no map — with its programme, unit, usual quantity and budget, one column for each of the ten years (quantity above, budget below), how many places are drawn, and its total budget. A year with quantity 0 and budget 0 shows as a dimmed “—”: nothing is planned that year. It has *Add activity* and the export menu, and refreshes when a place is drawn or the wizard saves. Numbers are read-only in this step. A **Location** column appears only where it applies: the number of places and the blocks or compartments they are in (press it to select them on the map), “Whole forest”, or “Not shown on the map yet” with a *Show on the map* link — and nothing at all for an activity that needs no map.
- **A "Review" column:** a line whose numbers are still the ones the system started with is tagged **Starting numbers** with a button **These numbers are right**; once confirmed it shows **Confirmed**. The yearly totals in the table equal those in the operational plan.
- **A "Yearly plan" button in the workspace header** opens the table from anywhere, without needing the Activity Features layer; the Next-step bar's *Open the yearly plan* now opens it right there instead of a new browser tab. *Add activity* in that table adds any activity — one that needs no map goes straight into the plan and its row appears at once.
- **You can change the numbers right in the table, and each change saves at once.** Press the usual quantity or budget of an activity, or a year, and type. The first number you type for an activity is used for every year that still has the starting value (never a year you changed, and never a 0) and the table says so — *Used for all years — change any year if it differs* — with an **Undo** button. Type 0 in both fields of a year to leave it unplanned. A number that does not make sense is refused on the spot; a failed save keeps what you typed.
- **Only the owner plans a forest's yearly activities.** Anyone else (a super-admin included) sees a plain message — *Only the owner of this forest can see and change its yearly plan* — and none of the planning buttons; a save that is refused says so in plain words and that nothing was changed.
- **A "Wider view" button** opens the table in a large panel, because it has many columns and the side panel is narrow. In the narrow panel the Activity column is no longer pinned, so it cannot cover the columns you scroll to.
- **The places table shows each place's quantity** (with its unit). The quantity belongs to the activity, so when several places of one activity share it, each shows a small “shared ×3” tag.

### Yearly activities — P3: add an activity with one question at a time (plan §4.4)
- **A card on the map walks you through adding an activity:** what → where → when → how much → name → confirm, one question at a time, with *Back*, *Skip* and *Save and add another*. Choose an activity by typing or browsing (the finder); say whether it is shown on the map, applies to the whole forest, or is decided later; pick the years (*This year / Years 1–5 / Every year*); type the quantity (already filled from what you drew, with its unit) and the budget in NPR, the same every year or different each year; see the total and a plain sentence before you save. A very large amount is flagged before saving.
- **Activities that need no map skip the place question entirely** and go straight into the plan from the map — no need to open the yearly-plan page.
- **You can draw first:** draw a point, line or area with the map tools and the card opens and asks what it is for. **Drawing a place for an activity works now** — before, the drawing tool never actually started.
- **The Next-step bar's "Show it on the map"** opens the card at the place question for that activity; an **Add activity** button sits in the bar and in the Activity Features table's toolbar.
- Adding a plan line without a place is one all-or-nothing request (`POST /yearly-activities/calculations/{id}/yearly-plan`); a line the person typed is created reviewed.

### Yearly activities — P2: edit and export from the map (plan §4.6, §5.3)
- **The Activity Features table is editable.** Rename a place (double-click the name), change its map symbol from a drop-down, or choose the plan years it belongs to (ten year chips; at least one). Each saved change can be undone with Ctrl+Z. If you give a place a year its activity is not planned in, you are asked whether to plan that year too — nothing is planned without a yes.
- **A "Next step" bar on the map** says the one thing to do next in the yearly plan, with the right button (show the Activity Features layer, or open the yearly plan). Fold it away with ✕; it comes back as a small pill.
- **One Export menu, two named files, on both screens** (the map's table and the yearly-activities page): *Yearly plan (CSV)* and *Activity features (CSV)*, made by the same server exporter so they are identical wherever you press the button. On the page, unsaved changes are asked about first ("Save your changes first?"). The table's own quick export is now named `…_view.csv` / `…_view.geojson`, so it can never be mistaken for the full file.

### Yearly activities — P1b: find any activity easily (plan §4.11)
- **A finder above the plan on both yearly-activities screens.** Type any word in Nepali or English (*nursery*, *fire line*, *नर्सरी*), or browse by group with a plain description of each programme. The usual Nepali spelling variants are ignored (वन finds बन), and a one-letter typo still finds it. Filters: can be shown on the map / needs no map, map symbol, measured in, already in my plan, recently used. Each result shows the full name, the English name, how it can be shown on the map, what it is measured in and whether it is already in the plan (with its years). A search that finds nothing offers three suggestions and the full list — never a blank panel.
- **English names and search words for all 135 activities** (`potential_activities.name_en` / `search_terms`, seeded by `python -m scripts.seed_activity_search_terms`, reversible). The unused test row "Program A / Plantation Work" is switched off.
- **The standalone yearly-activities page now opens with its forest:** `/calculations/:id/yearly-activities` used to render an empty page because the route never passed the forest's id.
- The table below the finder lists only the activities that are already in the plan.

### Yearly activities — P1: the system says what to do next (plan: `YEARLY_ACTIVITIES_WORKSPACE_PLAN.md`)
- **A "Your plan" card on the yearly-activities page and on the Reports-tab screen:** how many activities are ready, the ONE thing to do next in plain Nepali / English with one button, and a list of what else needs attention. The wording lives in the `yearlyPlan.*` messages and is edited on the Translation page; it is switched off with `VITE_YEARLY_PLAN_GUIDANCE=false`.
- **"These numbers are right":** an activity that still has the starting numbers (1 and NPR 5,000) can be confirmed as it is.
- **Plain error messages:** a failed save or load now says whether the data is safe and what to do (connection lost, value not accepted, changed on another page) instead of the server's raw sentence or "Unknown error occurred".
- **Quantities are never rounded** on either screen or in the CSV (0.5 ha used to show as 1).
- **Both screens re-read the plan** when you come back to them (the map may have changed it) — without a spinner, and never over unsaved edits.
- **The `{{ya_…}}` template tags** are shown to template designers only.
- **Translation page:** each message shows where it appears and what its placeholders mean, and an edit that drops a `{{placeholder}}` is refused with a reason instead of breaking the message.
- **Cost-benefit page:** a banner says when the yearly plan changed after the analysis was last updated (with an *Update from plan* button — never automatic) and when the costs still include starting numbers.

### Cost-benefit analysis — cost rows follow when the money is spent (D28)
- **Auto-populate now writes one cost row per run of equal yearly budgets** instead of one row averaged over ten years. An activity budgeted NPR 60,000 for Years 1–3 was entered as 18,000 in each of ten years (the same total, but discounted as if spent later and lighter); it is now one row for years 1–3.
- **Existing scenarios change once:** the NPV, IRR and payback of a scenario shift to the more accurate figure the next time it is Auto-populated. Rows are matched by a new key (`activity:{id}:{from}-{to}`); the old averaged rows are replaced, manual rows are never touched.
- A manual ("locked") row named like an activity that is now also added automatically is **reported as a warning** (it may be counted twice) — never deleted.

### Yearly activities — P0b: the plan foundations (plan: `YEARLY_ACTIVITIES_WORKSPACE_PLAN.md`)
- **Migration `091`** (applied): plan-line `version` (optimistic lock) and `reviewed_at`, three partial unique indexes so an activity can be added to a forest only once per location level (the legacy duplicate check compared `block_id == NULL` and never matched), and nullable `potential_activities.name_en` / `search_terms` (used later by the activity search).
- **New calculation-scoped routes** under `/api/yearly-activities/calculations/{id}`: `POST/PATCH/DELETE activity-features` (the plan line, its ten year rows and the feature are created in one transaction), `GET yearly-plan`, `PUT yearly-plan/{line}` (all-or-nothing, version-checked), `POST yearly-plan/{line}/confirm`, `GET yearly-plan/health` (what is missing, as codes), and `GET yearly-plan/export` / `activity-features/export` (one CSV builder for both screens: unrounded quantities, translated headers, blank location for activities that need no map).
- **The first value typed fills the other years** (only years still at the starting 1 / NPR 5,000 of an unreviewed line; a changed year and any 0 are never overwritten) and a line counts as reviewed only when neither quantity nor budget is still a starting value.
- **Two screens can no longer overwrite each other silently:** a stale save is refused with a 409 carrying both versions; the legacy routes take the same lock.
- **Cost-benefit analysis:** `GET /api/cba/{id}/plan-drift` says whether an Auto-populate would change anything (read-only, it writes nothing); the plan-health document reports it as `CBA_OUT_OF_DATE`.
- **The workspace's Activity Features layer** now calls the new routes (its old create / update / delete called routes that never existed).
- `POST /proposed-activities` twice for the same activity is now a 400 (it used to make a duplicate for a forest-level line).

### Yearly activities — P0a: zero years are real (plan: `YEARLY_ACTIVITIES_WORKSPACE_PLAN.md`)
- **A year can now be saved as quantity 0 / budget 0** ("not planned that year"). The API used to refuse it (422), the legacy page turned a saved 0 back into 1 / the default on reload, and one refused year aborted "Save All". A plan line's *default budget* may also be 0 (a wholly voluntary activity); the default quantity stays above 0.
- **Totals treat a stored 0 as 0**, not as "use the default": the proposed-activities list, `/summary`, and the plan-map figures.
- **Legacy page:** editing the default quantity / budget changes only the years still planned; "Save All" now names the activities that failed and still saves the others.
- **Plan maps (`opsmap:`):** the years an activity is planned now come from its year values (effective quantity or budget above 0), as the operational-plan tables already did. Before, an activity without a stored `year_numbers` looked like Year 1 only, so map budgets and felling years of *existing* plans can change.
- **Per-activity routes are owner-only** (spatial assignments, drawn features, year details): a user who knew an activity's UUID could read or change another forest's plan. A super-admin gets the same 404 (decision D9).
- **Operational-plan data stays fresh:** editing only a year row or a spatial assignment now refreshes the OP variables (`ya_*`, `cba_*`); before, the cache was not cleared.
- **Cost-benefit analysis:** re-populate now removes an activity's cost row when its budget becomes 0 (it used to keep the old amount).


### Added
- **Geometry Processing Fix** (`file_processor.py`): Direct polygon import preserves all features without partitioning/merging. 5 polygon features now import as 5 blocks instead of being merged.
- **Overwrite Confirmation Dialog** (`ImportPurposeDialog.tsx`): Modal confirmation when re-importing to builtin layers with existing data. Shows "This forest already has Blocks data. Importing will replace all existing Blocks with the new data."
- **Context Menu Delete Action** (`LayerContextMenu.tsx`, `LayerPanel.tsx`): "Delete Blocks Data" option on builtin layer context menu with confirmation modal and danger-style button.
- **Backend Delete All Blocks Endpoint** (`forests.py`): `DELETE /calculations/{id}/blocks` to clear all blocks for a calculation.
- **Frontend Delete API** (`api.ts`): `forestApi.deleteBlocks(calculationId)` for calling the delete endpoint.

### Fixed
- **Geometry Count Mismatch**: Shapefile with 5 polygon features now imports as 5 blocks (was 2 due to partitioning/merging in `_polygonise`).
- **Context Menu Import**: Right-click builtin layer → "Import Blocks" now works correctly with auto-purpose and auto-naming.
- **Re-import Behavior**: Now shows overwrite confirmation instead of silently appending or failing.
- **Conversion 400 Errors**: Fixed `calculate_area_geodesic` tuple return, missing `json` and `flag_modified` imports.
- **Backend Model Import**: Fixed `WorkspaceLayer` import path.

### Changed
- **Import Flow**: Re-import to builtin layers now requires explicit user confirmation before overwriting.
- **Builtin Layer Management**: Users can now delete all data for a builtin layer (Blocks, Compartments, etc.) via context menu.

---

## [2026-08-06] - Major Feature Completion

### Backend Changes
- `backend/app/api/workspace.py`: Added `convert_imported_to_builtin` endpoint with proper error handling, logging, and geometry version bump
- `backend/app/api/forests.py`: Added `delete_all_blocks` endpoint (`DELETE /calculations/{id}/blocks`)
- `backend/app/services/file_processor.py`: Added direct polygon preservation logic for ready-to-use blocks (bypasses `_polygonise` partitioning)
- `backend/app/api/workspace.py`: Fixed geometry area calculation using `calculate_area_geodesic_from_shapely` (returns tuple)
- Added missing imports: `json`, `flag_modified`, `calculate_area_geodesic_from_shapely`

### Frontend Changes
- `frontend/src/components/ImportPurposeDialog.tsx`: 
  - Overwrite confirmation Modal with existing data detection
  - `checkExistingBlocks()` API call before conversion
  - `doConversion()` and `handleOverwriteConfirm()` handlers
- `frontend/src/components/LayerContextMenu.tsx`: 
  - Added `onDeleteBuiltin` prop
  - "Delete [Layer] Data" context menu action with danger styling
- `frontend/src/components/LayerPanel.tsx`:
  - `handleDeleteBuiltin` with Modal.confirm
  - Wired `onDeleteBuiltin` to `LayerContextMenu`
- `frontend/src/services/api.ts`: Added `deleteBlocks` API call
- `frontend/src/components/AddLayerMenu.tsx`: Purpose-specific import options (Import as Blocks, Compartments, etc.)

---

## [2026-08-05] - Initial Implementation

### Backend
- `POST /workspace/{id}/import-layers/{layerId}/convert-to-builtin` endpoint
- `POST /calculations/{id}/import-blocks` endpoint
- `BlockCreateFromGeometryRequest` schema

### Frontend
- `ImportPurposeDialog`: Auto-purpose locking, auto-naming (Block 1, Block 2...)
- `LayerContextMenu`: "Import [Layer]" action with auto-purpose mapping
- `AddLayerMenu`: Purpose-specific import options
- `LayerPanel`: Context menu wiring, file input always available
- `useImportLayer`: `replaceExisting` option for builtin imports

---

## Testing

All tests passing:
- Frontend: 386/386 tests ✅
- Backend import tests: ✅
- Backend name-first drafts: 23/23 ✅
- Build: ✅ (only pre-existing unrelated MapWorkspace error)

---

## Future Work

- [ ] Extend delete endpoint to Compartments, Sub-areas, Activity Features
- [ ] Extend overwrite confirmation to Compartments, Sub-areas, Activity Features
- [ ] Add import preview (show features on map before confirming)
- [ ] Attribute mapping UI for shapefile fields
- [ ] Undo conversion (restore imported layer)