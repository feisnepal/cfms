# CURRENT PLAN — READ THIS FIRST

> **Single source of truth for "what are we working on right now".**
> Any AI session or contributor MUST start here before touching code or reading other plan files.

## 🆕 PLANNED (2026-11-10) — AI CHATBOT (approval-gated, token-capped; nothing built)

**Plan:** [`CHATBOT_PLAN.md`](CHATBOT_PLAN.md) · **Tracker:** [`CHATBOT_TRACKER.md`](CHATBOT_TRACKER.md) (phases C0–C7, pilot gate P1 after C3, decisions D1–D13; D13: hosted providers see only a synthetic forest, real-forest tools need a local model; open: O2 provider, O8) · background: [`AI_CHATBOT_REPORT.md`](AI_CHATBOT_REPORT.md).
Signed-in users approved by a super admin, daily token cap, answers through our own tools and a 50–100 query library; only the super admin gets free text-to-SQL; exports, slides (`python-pptx`) and guided uploads later. **Subscription = approval for now; payment may come later.** Waiting for the owner to say "proceed" for C0 (provider interface and benchmark). Alembic head is **147** (chatbot tables: access, usage, messages, settings). **State 2026-11-10:** C0.1–C0.3 and C1.1 done; C0.4 benchmark running (provider not chosen); `feature/chatbot` branch, nothing committed. Other plans above are unaffected.

---

## 🆕 CURRENT (2026-10-05) — OPERATIONAL PLAN DOCUMENT, generated from workflow steps 1–13

The data steps are built. The work now is the OP document that is generated from them. Which step feeds which section,
the entry points and the rules the OP depends on are in `CLAUDE.md` → "The OP document (current work)". Steps 14 (management plan)
and 15 (issue & submit) come after it.

**Done on 2026-10-05 (all committed in `b59abe0`, pushed):** summary-only household entry (migration 112); caste spelling
जनजाती (113); user-group analysis runs automatically on every polygon change and covers all polygons; hazard / soil-loss
caches are checked against the grid (they used to make the chapter say "data not available"); households are placed on building
footprints, survey lat/lon unused, and a forest with no household data ranks one stand-in per building; the Field Book progress
step reads the `fieldbook` table.

**Open:** (1) four progress-bar steps (Detail Description, Analysis, Hazard & Erosion, Cost-Benefit) turn green when data is
*available*, not when the work is *done*; (2) documents built from household totals do not yet say they are based on summary data;
(3) editing user-group vertices re-analyses in the background, so the page may need a refresh to show it.

**Previous plan, paused:** Raster Layers as Natural Features (below) — P0–P2 built, P2.5 agreed and unbuilt.

---

## 🆕 STARTED (2026-10-09) — FOREST SUMMARY PANEL & DECISIONS (workspace)

**Plan (verified, read first):** [`FOREST_SUMMARY_PANEL_PLAN.md`](FOREST_SUMMARY_PANEL_PLAN.md) — a floating, movable forest-wide summary panel in the map workspace (verdict, 8 tiles, 5 themes), a **Decisions needed** tab (DFO of the same organisation can answer; locked when the map is `locked`), and a plain-text export. Tasks `FP-0 … FP-12`; mock-up `FOREST_SUMMARY_PANEL_MOCKUP.html`. New migration is **116** (head was 115). Backup branch `backup/20261009-before-FP`. Same branch `wip/sublayer-and-raster-p25`; commits only when asked.

---

## ⏸ PAUSED (2026-09-29) — RASTER LAYERS AS NATURAL FEATURES (carve from the rasters, not by hand)

**Plan:** [`RASTER_SOURCES_IMPLEMENTATION_PLAN.md`](RASTER_SOURCES_IMPLEMENTATION_PLAN.md) (why/how, one row per task) · **Tracker:** [`RASTER_SOURCES_TRACKER.md`](RASTER_SOURCES_TRACKER.md) — one row per task, decisions D1–D51, evidence, change log. **Start there; next task = `RS-2.11` (needs an owner decision) or `RS-4.1a` (owner domain input).** Do not trust this line alone — the tracker's **Session brief** at the top is authoritative, because this file is a pointer, not the state.
**Evidence / decisions:** [`RASTER_NATURAL_FEATURES_REPORT.md`](RASTER_NATURAL_FEATURES_REPORT.md) (analysis; **§0b** records what changed once implementation started) · **§11** test matrix.
**Purpose:** a compartment should be carved from the **forest on the ground**, not drawn by hand. Four shippable rasters each propose a *geometry* — **NASA 2020** (forest quality), **NDVI / forest health**, **ESA WorldCover** (the only source that gives a real forest **edge**), **DEM** (elevation — **attributes only, no longer a carve source**, D51/RS-2.19). Forest type (FRTC) is a **fifth**: **no longer blocked on data** — the owner supplied the authoritative FRTC 2015 legend on 2026-09-30 and RS-0.2 applied it (D50). It is now gated on **RS-4.1a**, a question only the owner can answer (see below).
**Status 2026-09-30 (rev. 43):** **P0 gate MET** — RS-0.1 baseline, RS-0.3 source-registry SSOT, RS-0.4 coverage probe, RS-0.5 `raster_zonal` registration, RS-0.6 floor measured on 14 real boundaries (D38), **RS-0.2 FRTC legend applied + owner-green (D50)**. **P1 done** (§0b). **P8 done** — `rasters.slope` → `slope_regulation`, no DEM-derived slope/aspect; **RS-8.7 still open** (accessible-area engine still derives slope from the DEM; it changes coverage numbers the owner has been checking). **P2 largely done** — migrations **105 and 106 both applied**, RS-2.10 → RS-2.14 closed, **RS-2.14 owner-green**, and RS-0.2 owner-green. **⚠ THE OPEN QUESTION, RS-4.1a:** the owner's legend calls FRTC class 26 **"Non forest"**, but this plan’s own §0.1 measurement says class 26 is **~90% co-located with ESA class 10 = Tree cover**, i.e. *inside* closed-canopy forest. Both are true statements in this plan and they contradict each other. **Only the owner can settle what FRTC means by "Non forest" at ~63% of the country. Do not build the FRTC spec past it.** **New phase P2.5 — Independent Auto-Block layers (D51, agreed, unbuilt):** every source creates its **own layer-panel layer** carrying only its own attributes, and blocks-vs-compartments is assigned by **promoting exactly one of them**. This replaces the old model where sources overwrote one shared block set — which is what made the attribute table "not independent". Rows RS-2.16 → RS-2.20. **Cancelled:** RS-3.5.1–RS-3.5.6 (DEM as a carve source) and **RS-4.3 REVERSED** — its original gate would have displayed the fabricated name "Tropical Sal Forest" beside the real one. **Resolved 2026-10-03/05:** migrations 105–113 are committed and pushed on `wip/sublayer-and-raster-p25` (commits `ab0fb73`, `b59abe0`); the earlier warning that migration 106 was applied but uncommitted no longer applies. `master` still lacks this work, so a branch switch would still leave the DB ahead of the code. Sequence now: **RS-2.16 → 2.20** (P2.5) → P3 (NDVI) → P3.7 (ESA) → P5 (frontend/legends/i18n) → P6 → P7; FRTC waits on RS-4.1a. Standing permissions inherited from the Forest Structure section: servers and migrations without asking; **commits only when asked**; the plan/tracker/report files are **git-ignored and local-only** (`*.md` rule). They were briefly un-ignored on 2026-09-30 so they would get version history, then **reverted before the push** because `origin` is a public repo and this repo is deliberately code-first: these are internal working memory (44 revisions of decisions, audit findings, incident records), not publication material. **`AGENTS.md` and this file carry the Session brief that points at them**, which works on this machine; a fresh *clone* gets dangling links to those three files — accepted. **Forest Structure is paused, not abandoned** — next task still `FS-0.1`, and it must land its `094`/`095` after our `105`/`106`.
**Carry these three forward (they will bite again otherwise):** (1) on this PostGIS build `ST_AddBand` **ignores** its NoData argument, so every import must call `ST_SetBandNoDataValue` — NASA is 83.5 % zeros and NoData pixels are dropped, so a trusted `ST_AddBand` silently deletes four fifths of the raster (D39); (2) **each raster spec needs its own label vocabulary** — health's code `1` and NASA's code `1` are different classes, and a shared table re-creates the legend/renderer split D32 documented; (3) the **5 ha floor is not a default** — slope/aspect/canopy keep it, the new class mosaics use the D38 area-aware floor, because a source that returns nothing is indistinguishable from a broken one.
**Global rules that constrain the work (plan "Rules for this plan"):** never exclude a raster class from geometry — a NoData class carves exactly but has no dominant value; a new source's minimum unit is **5 ha**; the scoped clip (rule 19) must be built into the engine from the start, not retrofitted; ~~all seven persisted fields and 28 frontend columns ship together~~ — **superseded by D51**: a source no longer adds columns to everyone else’s row, it adds a **layer**. The discipline survives (wire the migration, the model, **both** commit paths, both API serialisers and the frontend registry, or it silently persists NULL — that was RS-2.10) but plan §5.1 is **obsolete**; read §P2.5.

### 🆕 2026-10-03 — Sub-compartment / Sub-block layer = every undivided unit (decided, nothing built)

**Report:** [`SUBCOMPARTMENT_LAYER_COVERAGE_REPORT.md`](SUBCOMPARTMENT_LAYER_COVERAGE_REPORT.md) · **Tracker:** [`SUBCOMPARTMENT_LAYER_TRACKER.md`](SUBCOMPARTMENT_LAYER_TRACKER.md) (rows SL-1…SL-8).
**Rule (owner):** the sub layer shows every unit that is not divided further, so sub-compartment total = compartment total = forest boundary area, always (test forest परिक्षण: 4 + 5 rows today → 8 rows, 129.75 ha). Undivided rows are editable; no tag; same for Sub-block. Display rule only — no migration. No backend change needed (`child_count` is already sent). SL-2/SL-3 written; next SL-5 (vertex-edit shell for undivided units). SL-0 audit done: the 4 forests whose units ≠ boundary are legacy (pre-date this system) — no repair; बृन्दाबन never edit. SL-6a audits every unit-creation path before SL-6b fixes any.

---

## ▶️ PREVIOUS PLAN (2026-09-21, planned — nothing built) — FOREST STRUCTURE RULE (Blocks→Sub-blocks **or** Compartments→Sub-compartments)

**Plan:** [`FOREST_STRUCTURE_IMPLEMENTATION_PLAN.md`](FOREST_STRUCTURE_IMPLEMENTATION_PLAN.md) (why/how) · **Tracker:** [`FOREST_STRUCTURE_TRACKER.md`](FOREST_STRUCTURE_TRACKER.md) — one row per task, resume protocol. **Start there; next task = `FS-0.1`.**
**Evidence / decisions:** [`FOREST_STRUCTURE_RULE_AUDIT_REPORT.md`](FOREST_STRUCTURE_RULE_AUDIT_REPORT.md) (decisions §14.7, sequence §15, production SQL Appendix C).
**Purpose:** the forest boundary is the root; beneath it a forest has **one** stream — blocks (→ sub-blocks) **or** compartments (→ sub-compartments), never both. Today the code models a chain, allows mixing (a mixed forest silently loses area from analysis; sampling double-counts a parent and its children), and has no sub-block level. Private land is physically excluded from units (100 − 10 = 90 ha); effective area = tree-cover part of (forest area − protected forest); all six operations (auto-create, equal-area, cut, copy, paste, merge) work on all four unit types; the OP report follows the stream.
**Status 2026-09-21:** all decisions recorded (D1–D13, C1–C6′, G2); plan and tracker written; **owner said "proceed" (after work package FD) and chose the LEAN plan (2026-09-21) — P0 in progress**; lean = no aliases / dual-write, no shadow release or rule flags, old block → compartment flows removed in P4a, no restore-copy rehearsals (plan §1, L1–L6). Sequence: P0 → P1a → P1b → P1c (migration 094) → P1d (095) → P3a-1 → P4a → P2 (096) → P3 → P3a-2 → P4b → P6 (097); P7 continuous. Standing permissions: servers and migrations without asking; commits only when asked. The plan/tracker/report files are git-ignored (`*.md` rule) — local unless the owner asks to version them.

### ✅ 2026-09-29 — UX-1 / UX-2 / UX-3 (owner requests) — **USER GREEN**

**Three reported problems, all real, all with the same shape: two sources of truth where there should have been one, and no test on either.** Tracker section **UX** in `FOREST_STRUCTURE_TRACKER.md`.

- **UX-1 — the layer panel's order and default show/hide.** The panel sorted on `layerOrder[id] ?? 0` but only **4 of 11** layers were ever seeded, so **7 tied at 0** and their real position came from a hardcoded array literal. That reproduces the owner's reported "existing order" exactly, including Sub-Blocks sitting after Blocks (a v4-persisted `sub_blocks: 1.5`). The registry was never the source of the panel's order, and `activity_features` carried `order: 3`, colliding with `sub_compartments`. Order **and** show/hide now live once, in `LAYER_REGISTRY[].order` / `.defaultVisible`, seeded for all 11 layers, persisted as store **v5**. `MapCanvas`'s JSX order was realigned to match — all 11 built-ins share Leaflet's default pane, so document order *is* the z-order. `moveLayerUp`/`moveLayerDown` and show-all/hide-all, which were dead for 7 of 11 layers, now work.
- **UX-2 — the "forest's structure changed" ribbon.** It was written for **all three domains on every structural edit and never cleared**, so a forest with no analysis, sampling design or field inventory was told to re-run them, and one that *had* been re-analysed kept being told for the rest of its life. It now marks only the domains the forest actually holds data for, clears each when that domain is recomputed (re-analyse / sampling create / field-inventory process), and is a one-line dismissible strip with the explanation in a tooltip. This is the banner-only slice of **FS-2.2**, which remains ⬜ for the conversion flow.
- **UX-3 — the missing context notes.** The 7 were the activity-place draw confirm bar; all 7 already had Nepali, so nothing was untranslated — only the reviewer hint was missing. 7 notes added to `translations/yearly_plan_context.json`, plus 37 in a new `translations/workspace_context.json` for the whole drawing family. **The Translation page cannot supply these** (the PUT schema has no `context`; `note` goes to `history`; the test reads the files).

**Not covered by that signal:** **FS-4a.19 is still ⬜**, awaiting its own user green. The 2 remaining backend reds sit in its files and were proven pre-existing for each of these three rows.

## ▶️ PREVIOUS PLAN (2026-09-20) — YEARLY ACTIVITIES PLANNER (map workspace + legacy page, one guided experience)

**Plan:** [`YEARLY_ACTIVITIES_WORKSPACE_PLAN.md`](YEARLY_ACTIVITIES_WORKSPACE_PLAN.md) (why/how, §12 = tracking rules)
**Tracker:** [`YEARLY_ACTIVITIES_TRACKER.md`](YEARLY_ACTIVITIES_TRACKER.md) — one row per task, decision log, resume protocol. **Start there.**
**Purpose:** plan yearly activities from the map workspace's *Activity Features* layer **or** the legacy page, with the
same easy, guided experience on both — the system says what to do next, asks one question at a time, exports are
identical from both screens, and a year with quantity 0 / budget 0 is a real "not planned" year (today it cannot be saved).

**Status 2026-09-20: all 30 decisions recorded (D29–D30 approved); final review done; "find any activity easily" added (rev. 11); "proceed" given 2026-09-20 — P0a (zero years, ownership, CBA-link fixes) is BUILT and tested; nothing committed; save point `backup/20260920-before-yearly-plan-P0a`.**
P0a, P0b, the CBA step (D28), P1, P1b, P2, P3, P4 and P5 are built and committed; **P6** (the check before creating a plan or exporting, the measured quantity, the live proof that the numbers agree from the edit to the operational plan, release notes) is built and tested, awaiting commit. **What remains is the usability test with 3–5 real users** (`YEARLY_ACTIVITIES_USABILITY_TEST.md`), which only the owner can run. Phases: P0a → P0b (migration `091`,
ask before applying) → P1 guidance → P2 map table edit → P3 wizard → P4 Plan table → P5 legacy adoption + instant save → P6 usability test
(≈ 48 days, incl. P1b "find any activity easily"). Key decisions: non-spatial activities are planned **from the workspace too** (Plan view + wizard, all 136 — D7); **only the
owner edits, never a super-admin** (D9); two named exports — yearly plan (all) + activity features (spatial) — on both screens (D10/D11);
**not locked after OP submission** (D14); **the first value entered fills the other years** (D15); activities that need no map show **no
location** anywhere (§4.4b); Nepali written by Claude, edited by the super admin on the **Translation page** (`yearlyPlan.*`), no gate (D22).
**The Cost-Benefit Analysis reads this plan** (`services/cost_benefit/repopulate.py`) — the link must not break: plan §5.8 fixes two existing defects (a zero-budget activity keeps a stale CBA cost row; the OP data cache does not clear on year-row writes), adds a read-only CBA drift check + "plan changed" banner, and one decided, separate step, **D28** (CBA rows per run of equal budgets — `YA-CBA.1`, after P0b, released on its own; until then the CBA keeps averaging).
The plan/tracker files are git-ignored (`*.md` rule) — local unless the owner asks to version them.

## ▶️ PREVIOUS PLAN (2026-09-14) — SFM STRATUM SAMPLING FLOORS

**Plan:** [`map_design_ui_impl/IMPLEMENTATION_PLAN_SFM_STRATUM_SAMPLING.md`](map_design_ui_impl/IMPLEMENTATION_PLAN_SFM_STRATUM_SAMPLING.md)
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — SFM STRATUM SAMPLING" section
**Purpose:** enforce कार्यविधि §16 in **every sampling design** — Production ≥ 2 % / Conservation ≥ 1 % /
Protection ≥ 0.5 % floors (below-floor = 400), per-stratum plot size 500/500/100 m², and ≥ 5 plots per
block/compartment/sub-compartment. Owner answered 2026-09-14; **Phase 1 (SFM Variants) green deferred** —
retested together after this plan. Work continues on branch `feature/sfm-variants-P1`.

**Status 2026-09-14: SS-1.1 … SS-1.7 all IMPLEMENTED — IN REVIEW, awaiting owner green** (both engines enforce
the floors/plot-sizes/min-5; the SamplingTab per-unit stratum card is always on; targeted suite ~150 tests
green + full frontend vitest 1401/1401 green; full backend pytest has a 13-15-test pre-existing failure
cluster confirmed unrelated via A/B revert — see `PROGRESS.md` SS-1.7 log for detail). **Retest together with
SV-1.12** (Phase 1, SFM Variant & Compare — already awaiting green from earlier the same day).

## 🔴 CI IS NOT ENFORCING ANYTHING [corrected 2026-09-29] — was "🟢 CI IS LIVE — 10 of 11 jobs green [2026-08-25]"

> **Correction, 2026-09-29 (owner asked me to check).** The heading above was true on
> 2026-08-25 and is **false now**. `ci.yml` is valid and all 13 jobs are built from it, but
> **not one step has executed** on any recent push. Every job starts and completes in **3–5
> seconds with zero steps**, and GitHub's own annotation says why:
>
> > "The job was not started because recent account payments have failed or your spending
> > limit needs to be increased. Please check the 'Billing & plans' section in your settings"
>
> **It is not a slow build and not a queue — nothing has run.** It affects `6d68809`,
> `29d0e84` and `1bba6b6` identically, so it is independent of any commit. **The fix is in
> GitHub's web UI only** (Settings → Billing and licensing → Budgets and alerts: retry a
> failed payment, raise the Actions spending limit, or re-enable Actions). The REST API
> returns 404 for billing with the current token scopes (`repo`, `read:org`, `gist`); it
> would need the `user` scope, and even then the change cannot be made through the API.
>
> **What this invalidates below:** every claim of the form "the gates are enforced in CI",
> "CI turned the build red", "CI caught it", and the `10 of 11 jobs green` headline. Those
> were true when written and must not be read as current. **What it does not invalidate:**
> the gates themselves still run locally, and the work in this repository was verified by
> running them there. The difference is *enforcement*, not correctness — which is exactly
> the failure mode this file has repeatedly caught in the codebase: a mechanism that looks
> like it is checking something and is not.
>
> Also corrected here: the remote is **`rakuri2026/september_enjoy`**, not `rakuri2026/cfms`
> — the repository was re-initialised on/around 2026-09-17 (see branch
> `backup/20260917-before-september_enjoy-reinit`). Any note saying "this repository has no
> git remote" (there is one, dated 2026-08-24, further down) is stale.

**The repository is on GitHub (private) and `ci.yml` runs — when billing allows it.**
Before 2026-08-25 it had never executed once, so roughly a dozen gates built across
Phases 1-5 had never enforced anything.

**Three of the four failures were real defects, not CI plumbing.** That is the
pattern of this whole plan: nothing found was new, it was old and silent
because the thing that would have caught it was switched off.

**The one still red is `security-scan`, and it needs a decision, not a fix:**
`fiona` 1.9.5 carries a CRITICAL (CVE-2023-45853, MiniZip) and a HIGH. It is a
direct pin in `requirements.in`, so fixing it means a version bump plus the
two-round Linux lock cycle, and fiona is the core of the geospatial stack.
**Note the inconsistency:** `pip-audit`'s baseline already accepts these exact
two advisories (`--ignore-vuln GHSA-q5fm-55c2-v6j9 GHSA-g4m4-9q4c-mfw6`), while
Trivy has no baseline and fails. Two scanners, one finding, opposite verdicts —
that is the thing to resolve. Owner's call, not urgent: it is a zlib flaw
reachable only through malformed archive parsing.

### What each failure actually was

| Job | The real cause | Fixed in |
|---|---|---|
| `compose-smoke` | **Not slow startup — an unimportable app.** `translation_service.py` ran `TRANSLATIONS_DIR.mkdir()` at module scope, so creating a directory was a side effect of *importing* the app. H5.1 made the container non-root (uid 10001) against a host-owned bind mount, so it raised `PermissionError` twelve frames into an import chain and uvicorn never started. **The hardening caused this**, and compose-smoke was the only thing exercising it. Prod compose already used named volumes; dev did not, and the worker had no `uploads`/`exports` mounts at all | `a015cdc` |
| `alembic-check` | **Had never run, once.** `needs: test-backend` was red every time, so it was skipped every time; the first green test-backend let it execute and it failed in two seconds with "Database is not at head" — it goes straight from `pip install` to querying an unmigrated database. **A skipped job reads as absence, not failure**, which is how G-DB-3 was cited as enforced while nothing enforced it | `56c9f26` |
| `test-frontend` | **Not pollution — no timeout margin.** 864ms alone, 1966ms with coverage, 9036ms under full-suite load, against the 5000ms default. Twenty tests already exceed 5s and pass (reported duration includes hooks; the timeout covers only the body). Which test loses is a coin flip — the job passed on the very next run with no change | `374bdbd` |
| `security-scan` | Trivy HIGH in `wheel`, which is **not in the lock** — it ships with the Python installation. Purged from both interpreters in the runtime stage, with a build-time assertion because there is no Docker here to test it | `6682dae` |
| `test-backend` | Was the G-SEC-1 stale allowlist, fixed in `d508a533` | ✅ confirmed green |

**Two more found while fixing the above**, both the same shape as everything
else today — a guarantee everyone assumed and nothing checked:

- **A test asserted `heads == ["051_..."]`,** pinning the name of whatever
  migration happened to be last. Migration 052 turned `test-backend` red, which
  skipped `alembic-check`, whose finding 052 exists to fix. Three jobs from one
  over-specific assert. It now checks that the chain has not FORKED, which is
  the property worth protecting — this repo has a "Merge all migration heads"
  revision cleaning up six of them.
- **A test promoted the shared fixture account.** conftest's `auth_headers`
  uses a FIXED email and ignores the 409, so the account is shared by the whole
  suite; `test_calculation_lifecycle_routes.py` promoted it to ORG_ADMIN and did
  not restore it. Four authorisation tests in two unrelated files then failed
  under `-n auto -p randomly`. **The direction that failed is the harmless one** —
  a test asserting an admin CAN act would have passed for the wrong reason and
  said nothing. Restoring in teardown is not enough: xdist workers are separate
  processes on one database. The module now uses its own user, and
  `auth_headers` asserts the account it returns really is an ordinary USER.

**Correction worth keeping:** `test-frontend` was diagnosed here this morning as
"cross-file test pollution". That was wrong, and self-inflicted — the
measurement was taken while a recursive `C:\` filesystem search was running in
the background. Kill competing I/O before timing anything.

### How to read CI from a session

`gh` lives at `C:\Users\Rajkumar\tools\gh\bin\gh.exe` — **not on PATH, and not
installed via a package manager: this machine has no `winget`.** It was
re-installed 2026-08-25 as a portable extract after the previous copy vanished
(most likely a temp directory that got cleaned). Auth is in the Windows
keyring and survives reinstalls; `hosts.yml` holds no token, and reading it is
blocked by the sandbox anyway.

    $gh = "C:\Users\Rajkumar\tools\gh\bin\gh.exe"
    & $gh run list --branch master --limit 3 --json databaseId,headSha,status,conclusion
    & $gh run view <id> --log-failed

PowerShell note: `gh ... | ConvertFrom-Json` piped straight into `Format-Table`
prints `System.Object[]`. Assign to a variable and loop.

### The one workflow worth knowing

**The lock can only be regenerated on Linux.** `pip-compile` resolves per
platform, so a lock built here carries `colorama`, omits `uvloop`, and can
never match CI. `deps-lock` publishes the correct one as the
`requirements-lock-linux` artifact — `gh run download <id> -n
requirements-lock-linux`, then commit it. **Every new dependency needs another
turn of that cycle**, which cost two rounds today.

---

## 🟠 RESUME HERE — session of 2026-08-27

**Branch: `hardening/20260826-idempotency-natural-keys-correlation`** (15 commits,
not merged). Backup of the previous `master` tip: `backup/20260826-before-hardening`.
Merge with `git merge --no-ff` when ready.

**`cf_db` is at `060`.** `053`–`055` applied 2026-08-26; `056`–`060` on 2026-08-27.

**45 done · 5 in review · 7 written-unproven · 1 blocked · 39 not started** (97 rows).
Exactly **one** row is genuinely waiting on you — 3.11 — and it cannot be
scheduled: it needs a 500 to happen naturally. See the tracker's "What the 5 🟡
rows actually need".

### Built 2026-08-27

| Row | One line | State |
|---|---|---|
| **8.7** | `log_geometry_audit` had **four stacked defects** and had never once succeeded — dead route, a `::jsonb` cast SQLAlchemy parses as a bind parameter, a `metadata` column that does not exist, and 3 of 5 live layer types rejected *while raising*. Wired at `_write_geometry`: one funnel, 12 endpoints. Migration `058` | `27b72d7` |
| **7.4** | Statutory documents now carry a SHA-256, a provenance record binding them to `geometry_version` and the inventory runs, and an **unauthenticated** verification endpoint — the person checking a printed plan in a district office does not have an account. Migration `059` | `d75dd48` |
| **6.2** | Ten quantities were stored `Float` on one table and `Numeric` on another **while feeding the same statutory totals**. Migration `060` converts all ten; 113,451 rows | uncommitted |

### The mobile app does not exist (confirmed with the user, 2026-08-27)

`industry_grade_report.md`'s single largest scope caveat — the 3.1/10 score, and
S1-60, "the primary data-entry surface has not been audited" — describes an
Android/iOS client that **is not built**. `Offline_mobile_tool_preparation_report.md`
(2026-08-20) is a recommendation awaiting go/no-go, not a shipped app; its own
status line says so. All 35 `inventory_calculations` rows in `cf_db` arrived by
CSV/Excel/GPKG upload (`stem_map.xlsx`, `rame_tree.csv`, one `.gpkg`) — that is
the real primary data-entry surface, and it is already in scope.

**8.0 is void, not blocked**, and 2.16 / 8.1 / 8.4 / 8.5 move with it (⏸️ in
the tracker) — a device table, a sync cursor and a fleet dashboard have nothing
to attach to. 8.3 (chunked bulk-write) stays open: it is upload-side, on the
path that is real.

Re-open 8.0 the day (a) the go/no-go on the mobile report lands and (b) a repo
exists to point the audit at.

### Two things found on the way, neither fixed

* **`alembic check` crashes partway on this machine.** It emits 112 differences,
  then dies: `NoReferencedTableError: Foreign key associated with column
  'calculations.application_id' could not find table 'applications'`. So
  `check_schema_drift.py`'s "53 new differences" is computed from a **truncated
  run**, and tables late in the walk are never compared at all. Proved by
  reverting `inventory_trees.dia_cm` to `Float` against the now-`Numeric`
  column and watching the gate stay silent. Same family as the venv gap below —
  a gate that reports a number nobody has checked is worse than no gate.
* **A ~29-hour stray uvicorn** on port 8002 under system Python
  (`C:\Python314`), not the venv — PID 17488, up since 2026-08-26 07:50.

### The environment was not the declared one, and every earlier measurement was taken in it

**Six of the 43 packages in `requirements.in` were missing from `venv/`:**
`pytest-asyncio`, `pytest-randomly`, `pytest-xdist`, `pytest-timeout`,
`pytest-cov`, `CairoSVG`. All four test-integrity plugins that H1.7/H1.9 added
specifically, plus coverage. Installed at their pinned versions; `pip check` is
clean and all 43 are present.

This is a **G-ENV-1 gap**, and the tracker records Phase 1 as ✅ 18/18. The
lock is hashed and CI installs from it, so CI was unaffected — the drift is
local, which is exactly the "results differ by machine" failure H1.2 exists to
prevent. **Check this before trusting any local suite run.**

What it cost, concretely:

* `--timeout=300` in `addopts` was rejected as an unrecognised argument, so the
  suite could only be run with `-o addopts=""` — which also disabled
  `--ignore=tests/test_op_api.py`. Two of the "pre-existing failures" reported
  earlier in the session were artifacts of that workaround, not real:
  `test_op_api.py::test` (a file `addopts` ignores) and
  `test_shapefile_in_zip_yields_json_serializable_blocks` (an `async` test that
  was never awaited, because `pytest-asyncio` was absent — the
  `PytestUnknownMarkWarning` was the tell).
* With no timeout, `tests/test_feature_to_polygon_case_d.py::test_property_hull_never_invalid`
  **hung for 77 minutes on one core** inside `shapely.concave_hull`
  (`file_processor.py:1559`), with zero database activity. It is a Hypothesis
  property test, so this is **seed-dependent** — it passed on the next run.
  `requirements.in:79` already carries the comment "a hung test used to hang the
  job forever"; the fix was in the lock and not in this machine's venv.
  **`--timeout=300` now bounds it locally.** Whether the underlying input is a
  real `concave_hull` pathology is not yet investigated, and is worth a task.

**Honest suite result, correct environment, 2026-08-26:**
**9 failed · 1,664 passed · 360.87s.** The nine are pre-existing and confined to
two files — `test_route_authentication.py` (3) and
`test_calculation_lifecycle_routes.py` (6). They reproduced on a clean stash
before any of today's work.

**Also seen in the log, unrelated and unfixed:** `PostgreSQL 18.0 is not the
supported major (16). Dev, CI and Compose are expected to agree.` The database
warns about itself; nobody has acted on it.

---

## 🔴 PRESENT PLAN — INDUSTRY-GRADE HARDENING [2026-08-20 → present]

**Plan:** [`HARDENING_PLAN.md`](HARDENING_PLAN.md) — the "how", task by task
**Tracker:** [`HARDENING_TRACKER.md`](HARDENING_TRACKER.md) — **the "where are we", one row per task. Start here.**
**Source:** [`industry_grade_report.md`](industry_grade_report.md) — the "why", 96 tasks across 8 phases

**Everything below this section is superseded.** The feature plans — vertex editing,
Nepali-first i18n, auto-block MMU, map display refresh — are all on hold. They are kept
for their history, not as instructions. Do not resume one without the user saying so.

**Where we are (2026-08-27):** **45 done · 2 awaiting your test · 7 written-unproven · 1 blocked · 42 not started** (97 rows; the "96 tasks" headline is one out). **3.1 + 3.4 went user-green 2026-08-26** — map drawing, layer menu, vertex editing and shapefile import all tested working, which closes the highest-risk pair in the plan.

See [`HARDENING_TEST_GUIDE.md`](HARDENING_TEST_GUIDE.md) for what those 17 need. They are not one job: **six** need the app (~1 hour), **five** are a terminal one-liner, **five** (all of Phase 5) cannot be tested by anyone on this machine because there is no VPS and no Docker, and **one** (3.5) needs a trigger script written first. Labelling the Phase 5 rows "awaiting your test" was wrong — there is no test for the user to run; they are *written, unproven*.

| Phase | State |
|---|---|
| 1 Ground truth | ✅ **18/18** |
| 2 Security | ✅ 13/18 · 2.12 🟡 · **2.17 🟡 (2026-08-26)** · remaining: 2.13, 2.14 ⚖️, 2.16 |
| 3 Correctness | 🟡 **8 in review** (3.1, 3.2, 3.3-part, **3.4**, 3.5, 3.7, 3.8, 3.11) — **every L0 done** |
| 5 Operations | 🟡 **all 7 written**, none proven — no VPS exists yet |
| 4, 6, 7, 8 | not started |

### What this session built, and what it needs from you

**Nothing here is ✅ yet — every row above stops at 🟡 until you test it** (`AGENTS.md` §3a).

Highest-value things to try, roughly in order:

1. **Are you still being randomly logged out?** H3.7 should have stopped it. `cf_db`
   held **six** browser token families revoked `reuse_detected` — the client racing
   itself into H2.5's theft detection. That was a real bug with live evidence.
2. **The layer menu.** Right-click and the ⋮ button now open the same menu everywhere,
   including imported rows, which never had a ⋮ at all. Wording changed throughout.
3. **Ordinary map work** — draw, edit, import, export. H3.1 changed **290 route
   handlers** from `async def` to `def`. The suite says it is behaviour-neutral, but
   it is the largest mechanical change in the session.
4. **A calculation with a failing block.** It now reports `failed` with a reason
   instead of `completed` with wrong totals (H3.5).
5. **H3.4 — ⚠️ its behaviour changes are POSTPONED [2026-08-25].** You reported
   it "not working as expected" and chose to postpone them. **All five are off**;
   the ~182 log lines and the gate stay, and each site carries the code to
   restore. **H3.4 has no visible output by design** — 182 of 187 changes only
   add a log line, so "nothing new appeared" is correct, not broken. The symptom
   behind the report was never identified; if it recurs it is worth tracing.

   Postponed: (1) the 400 on unreadable geometry, (2) dropping stale `geo_*`,
   (3) the operational-plan rollback, (4) `area_sqm` raising instead of
   returning 0.0, (5) refusing an import whose `.prj` is unreadable AND whose
   coordinates are not lat/lon. **Re-enable 4 and 5 first** — both put a
   fabricated number into statutory figures, and their detection still works.

   Found while reverting, and more serious: **every log assertion in the suite
   was vacuous.** `alembic/env.py` called `fileConfig(...)` with the default
   `disable_existing_loggers=True`, and `conftest.py` runs Alembic in-process,
   so all `app.*` loggers imported before it were disabled for the session —
   H3.4's log lines emitted nothing under test. Production was unaffected
   (migrations run separately), which is why it went unseen. Fixed.

   ~~The other 184 changes only add a log line, but these three change what
   happens:~~ (kept below for the record — all now postponed)
   - **Edit a feature's geometry in the workspace.** If the geometry cannot be
     read, you now get a **400 saying so** instead of a 200 and a silently
     discarded edit. Normal edits must still save exactly as before — that is
     the thing to check.
   - **Create an operational plan.** If auto-population fails it now rolls back
     and logs, rather than returning a plan that claims to be populated.
   - **Anything showing area/perimeter.** A failed `geo_*` recompute now drops
     those fields rather than leaving the *previous* geometry's numbers on the
     new shape.

   Beyond that: draw, import, export, build an operational plan, render maps.
   187 handlers across 58 files were touched, so the risk is breadth, not depth.

### Waiting on you, not on engineering

| | Why it matters |
|---|---|
| **Provision a staging VPS** | Converts seven Phase-5 rows from written to verified. No image has ever been built anywhere. **This is the biggest single de-risking action available.** |
| **Commission the mobile audit (8.0)** | Blocks all of Phase 8; the client is not in this repo |
| **Send `PII_DECISION_BRIEF.md`** | 2.13/2.14; the pre-launch data wipe is a one-time free schema window |
| **Rotate the database password** | Outstanding since Phase 1 |
| **One Python 3.11 session** | Three things now queue behind it: `python-multipart` 0.0.7→0.0.31 (16 advisories), gunicorn (3.3's other half), and the other dependency bumps. **Do them in one lock regeneration.** |
| **Pick an alerting channel** | Alertmanager is deliberately blank; Sentry is unconfigured. Two half-configured paths is how alerts get ignored |
| **Decide which of 17 `docs/` files belong in git** | They exist only on this machine |

### Next session should start with

**2.17 is built (2026-08-26) — L0, ⭐, and the reach was the whole finding.**
The durable Postgres service was already written and tested when this session
started, and it still protected **2 of 194 mutating routes** — the same two the
Redis version had. Fixing the mechanism had not fixed anything, because the
guard had to be remembered at each call site. It now travels with the router
(`route_class=IdempotentRoute`) and covers **67 routes across nine field
modules**, with `check_idempotency_coverage.py --gate` failing the build on an
unguarded field write *or on a new API module classified as neither*. 33 tests.

**Two things it does NOT do, deliberately:**
* `IDEMPOTENCY_REQUIRE_KEY` is **false**. The web frontend calls these same
  endpoints with no key today, so requiring one would break the live app to
  protect a mobile client that does not exist yet. Unprotected writes are
  logged by name, so the gap is visible rather than assumed. Flipping it is a
  launch-day step taken with 8.0.
* The natural-key UNIQUE constraints — step 3 of 2.17's own spec — are **8.6**,
  and belong in the pre-launch wipe window.

**`cf_db` is at `060` as of 2026-08-27.** `053` and `054` applied after a
targeted `pg_dump` of the two tables `054` rewrites (`backups/`). The full
database is **12 GB** — almost all raster layers — and a whole-database dump
was killed at 2.3 GB after ten minutes; the two affected tables are 10 MB and
dump in seconds. Worth knowing before the next migration that touches data.

**8.6 is built too (2026-08-26), and the report's key was wrong.**
It specifies `UNIQUE (sample_plot_id, sn)`. The upload layout carries four
independent serials — `regen_sn`, `sapling_sn`, `pole_sn`, `tree_sn` — each
numbered from 1, and **1,092 of the 1,105 live plots hold more than one stand
type**. A rolled-back dry run against `cf_db` found **7,174 groups that violate
the specified key**: it would have failed on the first upload after deployment.
Shipped as `UNIQUE (sample_plot_id, stand_type, sn)`, which applied cleanly to
all 25,948 rows in that same dry run.

`sn` is **NOT NULL**, and that is the part that makes it real rather than
decorative: PostgreSQL treats NULLs as distinct, so the constraint over a
nullable column would have been satisfied by every one of the 25,948 legacy
NULLs while stopping nothing — `MAX_UPLOAD_SIZE_MB` and the empty
`geometry_audits` all over again.

**What the backfill is honest about:** no upload has ever mapped an SN column
(0 of 20 stored `column_mapping`s), so there is no source serial to recover.
The numbers are positional, ordered by `created_at, id`. They make the
constraint enforceable from today; they do **not** make historical duplication
detectable, and the migration says so rather than leaving it to be assumed.

**4.1 was already done — this file's pointer was stale.** It said "the whole
`ruff check` step is still `|| true`, so nothing enforces them yet". It is not:
`lint-backend` runs `check_ruff_baseline.py` and `check_black_baseline.py` as
hard steps, and the tracker row for 4.1 has carried the full completion note
since it landed. Do not re-do it. **The black ratchet earns its keep** — it
caught all four files added across today's three tasks and refused them until
they were formatted, which is exactly the "a new file must be formatted from
the start" rule working. Its baseline shrank 249 → 248 because the deleted
`idempotency_service.py` was an entry in it.

**3.9 is built (2026-08-26), and it was another inert feature.**
`middleware/correlation.py` documented "available in logging via
LogRecord.correlation_id"; `logging_config.py` was written to read exactly that
attribute; **nothing anywhere set it**, so the `hasattr` guard was false on
every record ever emitted. The ID reached a response header and
`request.state`, and no further. A support engineer holding an
`X-Correlation-ID` from a failed request could not find one log line for it.

That matters most for H3.4's work: roughly 182 log lines describing exactly
which record was dropped and what is therefore wrong with the numbers, none of
which could be tied back to the request that produced them.

Built as a **log-record factory**, not the handler filter the report names — a
filter on one handler leaves Sentry's, uvicorn's and any handler added later
unstamped, and the text format's `%(correlation_id)s` raises on a record that
skipped it. The ID is now in the text format as well as JSON.

**One hazard, pinned by a test:** `logger.info(msg, extra={"correlation_id":
x})` now raises `KeyError` from `Logger.makeRecord`, which refuses to let
`extra` shadow an attribute the record already has. Nothing in the repo does
that today. Bind with `set_correlation_id()` instead — it covers every line in
scope rather than one call.

**6.11 is done (2026-08-25)** — `GuideModal` sanitises, and a source scan now
fails on any unsanitised `dangerouslySetInnerHTML`. The report's "better still,
use a real markdown renderer" is deliberately **not** done: `simpleMarkdownToHtml`
is a hand-rolled regex converter and replacing it with `react-markdown` is a
behaviour change to every guide page, which wants its own task.

**Found doing it: 4.9 cannot be done at all yet.** It is listed L0 "cheap
insurance", but **this repository has no git remote** — branch protection is a
forge-side setting, so there is nothing to protect until the code is pushed
somewhere. It rides on the same decision as the VPS, and the tracker row is now
⏸️ rather than ⬜.

**Then 4.1 — remove every `|| true`.** 3.4 is done (see below), and 4.1 is the task it
set up: ruff `S110`/`S112` are now enabled and clean, but the whole `ruff check`
step is still `|| true`, so nothing enforces them yet. 4.1 also brings the
baseline ratchet that lets `BLE001` finally be turned on — 493 handlers catch
broadly and *do* log, which is a different problem from the 187 that said
nothing, and only a ratchet can hold that line without a 493-item cleanup.

After that, the highest-value remaining Phase 3 work is **3.9** (correlation ID
into logs). 3.4 added a great many log lines describing exactly which record was
dropped and what is now wrong; without a correlation ID none of them can be tied
back to the request that produced them.


**🚀 Launch target: 2026-11-24, ceiling 2027-01-24** (set 2026-08-24). The tracker's
**Launch readiness** section classifies all 65 remaining tasks as L0 (25, blocking),
L1 (18) or L2 (22), and carries the ordering that actually fits the date —
sequential phase order does not. Two long-lead items decide it and neither is
code: the **mobile client audit (8.0)** and the **PII legal answers (2.14)**.

**Next action, in order:**
1. ~~Apply `051` to `cf_db`.~~ **Done 2026-08-24** — see live-database state above. This
   step used to warn that the sandbox blocks an AI session from migrating the live
   database. It does not: `../venv/Scripts/alembic.exe upgrade head`, run from `backend`,
   applied it with no permission prompt and no extra allow rule.
2. **User-test 2.8 / 2.18, 1.18 and 2.15**, then flip those rows to ✅. For 2.15 the
   thing to exercise is ordinary map work — draw and save a boundary, edit block
   vertices, import a shapefile, import a tree inventory — and confirm nothing that
   used to save now refuses. The guard is a global request-body middleware, so a
   false positive would show up as a `413` or an `IMPORT_MAX_VERTICES_EXCEEDED` on a
   perfectly normal save.
3. **Then 2.12** (recommended next build): `pip-audit`, `npm audit`, `gitleaks`, Trivy
   in CI — the only Phase 2 task left that does not need a legal owner (2.13/2.14) or
   the mobile client (2.16/2.17).

**Standing environment caveats — revised 2026-08-24, and this changes how to read a
red run.** There are two interpreters on this machine and they are not equivalent:

- `D:\forest_management\venv` — Python 3.14 / **FastAPI 0.104.1**. It also has no
  `pytest-timeout`, so `pyproject.toml`'s `--timeout=300` makes pytest refuse to start
  at all. This is the interpreter the "expect 5 red" note was written against.
- `C:\Python314\python.exe` (plain `python` on PATH) — Python 3.14 / **FastAPI
  0.139.2**, the locked version. **A full run here is 1,514 passed, exit 0** — including
  the three `test_route_authentication.py` tests previously believed unrunnable, which
  were failing on the FastAPI version, not on anything real.

So: **run the suite with `python -m pytest`, not the venv**, and treat any red as a
genuine failure rather than the expected five. Python is still 3.14 against a locked
3.11, so nothing genuinely version-sensitive is proven locally — the H1.3 devcontainer
would still end this class of doubt.

## ✅ FIXED — the 14 endpoints that returned 404 [found + fixed 2026-08-25]

**All 14 are served.** They were defined in modules `main.py` never mounted, so
they simply did not exist while the UI called them — the whole AI report
feature, DFO approve and reject, submit-for-calculation, super-admin-unlock,
unified-shell-status and progress.

### What was done

| Module | Action |
|---|---|
| `reports.py` | **Mounted.** It imported cleanly; it was only missing from `SUB_ROUTERS`. All 8 routes now served. |
| `calculations.py` | **Not revived.** Its six unique routes were lifted into a new `app/api/calculation_lifecycle.py`, which is mounted. |

**Why lift rather than mount `calculations.py`.** It is 1,501 lines, it cannot
be imported (it wants `i18n_error` from a module that does not define it and
`app.api.forests_helpers`, which does not exist anywhere), and **ten of its
twenty routes duplicate routes `forests.py` already serves**. Mounting it whole
would have shadowed them — the product decision this file previously flagged as
yours, taken by accident. Lifting the six is purely additive: no route that
works today changed.

### Three defects fixed in the lift, not carried across

1. **DFO approve and reject denied every real DFO.** They gated on
   `role not in ("dfo", "super_admin")`, and there is no `"dfo"` role —
   `UserRole` is guest/user/org_admin/super_admin, and **DFO is `ORG_ADMIN`**.
   Only super admins could ever have approved. They now use
   `require_dfo_or_above` from `deps.py`, which exists for exactly this.
2. **Ownership checks were open-coded**, bypassing H2.7's `is_owner_or_admin`.
3. **The frontend sent no `Authorization` header** on any of these calls, so
   mounting alone would have turned every 404 into a 401. Six bare `fetch()`
   call sites now use `authHeaders()`. The 8 report calls go through the axios
   instance, which already attaches the token.

### Deliberately NOT done

- **`progress/stream`** (SSE) is not mounted. It does `async with SessionLocal()`
  on a *synchronous* sessionmaker, so it raises `AttributeError` on first use —
  it has never worked. Its only caller, `CalculationProgress.tsx`, is rendered
  by nothing, and `EventSource` cannot send an `Authorization` header, so it
  could not have authenticated either. Reviving SSE is its own task.
- ~~**Deleting `calculations.py`.**~~ **Done 2026-08-25**, after running the
  check that entry called for. Evidence, in the order it was gathered: nothing
  imports it (one stale docstring in `schemas/map_creation.py`, now corrected
  to point at `forests.py`); it could not be imported anyway, so none of its
  code has ever run; of its 20 routes, 16 are served elsewhere (10 by
  `forests.py`, 6 by `calculation_lifecycle.py`); and the remaining four —
  `status`, `start-calculation`, `queue-status`, `progress/stream` — have
  **zero live callers**, verified by full-URL search, not by matching the last
  path segment. **Route/method pairs stayed at 374 across the deletion**, which
  is the proof that nothing reachable was removed. `calculation_queue_service`
  survives: `calculation_runner.py` and `saga_compensation_service.py` use it.
  Ruff 317 → 315. The four route implementations live on in git at `8e9f3bd`.

### Still unmounted, and harmless — three left

`geometry.py` (9 routes, all duplicated by mounted routers — the frontend calls
the working `/api/forests/...` equivalents), `new_map_endpoints.py` (5 routes,
`NameError: router is not defined`, so it has **never** worked, 0 call sites)
and `audits.py` (1 route, 0 call sites). All three are recorded in the gate.
`geometry.py` is the next deletion candidate on the same evidence, but it has
**not** been checked to that standard yet — do the full-URL caller search
before touching it, exactly as `calculations.py` got.

### Verification

`scripts/check_unmounted_routers.py --gate` is in CI and `reports` is cleared
from its allowlist, so losing that mount fails the build. 20 new tests in
`tests/test_calculation_lifecycle_routes.py` drive the endpoints over HTTP —
`test_map_lifecycle.py` tested the state machine underneath and stayed green
throughout, which is precisely how the endpoints could vanish unnoticed. They
pass under random ordering.

---

## ⚠️ FOUND — 17 documentation files exist only on this machine [2026-08-24]

`.gitignore:152` ignores `docs/` wholesale. That directory holds **17 files, none
of them tracked**: the ADRs, `GLOSSARY.md`, `API_VERSIONING.md`,
`DB_MIGRATIONS.md`, `SECRETS.md`, `DEPLOYMENT_CHECKLIST.md`,
`comment-conventions.md`, `docstring-templates.md` and a `guides/` directory.

**A `git clone` of this repository gets none of them.** They survive only as long
as this machine does. The audit report cites `docs/` paths eleven times, and
task 6.7 plans to "consolidate `docs/`; ADRs from 001" — work that assumes files
the repository does not contain.

This is the third instance of one trap today. `*.json` nearly swallowed the H2.12
supply-chain baselines; an unanchored `check_*.py` did swallow
`scripts/check_slo.py` in H5.7; and the comment beside that rule records the same
thing happening to `scripts/check_schema_drift.py` back in H1.11. Unanchored
ignore rules written for throwaway files keep catching maintained ones.

**Not fixed here, because it is a decision rather than an oversight.** Some may
be deliberately local — `SECRETS.md` wants reading before it is published, even
though its name suggests documentation *about* secret handling rather than
secrets themselves. Which of the 17 belong in the repository is the question;
once answered it is one negation line, the same shape as the two already added.

**Do it before 6.7**, which otherwise plans work on documentation that is not
under version control.

---


## ✅ FIXED — the translation admin page could only see 11% of the strings [found + fixed 2026-08-24]

**T-1 done.** `seed_translations` is a reconciliation now, not a one-shot.

**What is wrong.** The super-admin translation page edits a `translations` table
that overlays the shipped bundle at runtime — a sound design: `PUT
/translations/{key}` creates the row if absent, keeps prior values as history,
and records who changed it. A wrong word is a one-field fix with an audit trail,
no deploy.

But the page can only list what is in the table, and the table is a fraction of
the bundle:

| | |
|---|---|
| Keys in the shipped bundle | **4,777** |
| Rows in `translations` (verified in `cf_db`, 2026-08-24) | **536** |

`seed_translations()` backfills the table from the bundle **only when the table
is empty** (`if db.query(Translation).count() > 0: return 0`). It ran once, when
the bundle held ~535 keys, and the table has not been empty since — so every
string added in the months after is invisible to the editor. Verified absent
from the table: `layerPanel.importInto`, `layerPanel.newFeatureIn`,
`layerPanel.autoCreateBlocksExist`, `layerPanel.menuGroupView`, and also
`layerPanel.addSubArea` and `layerPanel.newBlock`, which have existed for months.

The endpoints call `seed_translations(db)` on every request, so they *believe*
they are reconciling. They are not; it returns 0 immediately.

**T-1 — as fixed.** `seed_translations` reconciles on every call: one query for
existing keys, then only the differences are written. Two rules make it safe to
run repeatedly — **an override is never touched** (`is_override` marks human
work), and **a non-override row IS refreshed** (it is only a mirror of the
bundle, and a stale mirror would show the editor a string the application no
longer uses). The CSV import stays first-run-only: re-running it would push
legacy CSV values back over anything edited since, which is the one way this
function could destroy human work.

Measured against `cf_db` read-only before shipping: **4,242 keys would be
inserted**, 0 defaults are stale, the 1 existing override is untouched, and the
1 orphan row (in the table, not in the bundle) is left in place — reconciliation
never deletes. **It applies itself the next time a super admin opens the
translation page**; no migration, no manual step.

**Why it matters beyond wording.** This is a Nepali-first system for Nepali
forest officials. A runtime translation editor that reaches 11% of the interface
is, in practice, not a translation editor.

---

## 🟨 DEFERRED BUG — the boundary reaches the block-edit path as a feature id [found 2026-08-24]

**Deferred by the user on 2026-08-24: record it, do not fix it now.**

**Symptom.** Editing in MapWorkspace produced a 500 whose body was a raw
`psycopg2` error — the full `SELECT` over `forest_blocks`, its column list and
its bound parameters — because `feature_id` arrived as the literal string
`"boundary"` and `forest_blocks.id` is a UUID column.

**Both halves of what the user saw are already fixed** (see the H2.15 session,
uncommitted at time of writing): `editing._structural_uuid` now refuses a
non-UUID feature id before it reaches the database, answering
`editing.boundary_is_not_a_division` — *"The forest boundary can't be edited
from the block layer. Switch the active layer to Forest Boundary and try
again."* — and no handler anywhere can put SQL in a response any more.

**What is NOT fixed, and is the actual defect.** A client should never send
that pairing. The server now names the mismatch instead of crashing on it, but
something in the frontend still pairs `layerType` = a structural layer with
`featureId` = `'boundary'`. Traced and *ruled out*: `useContextMenuUndoRedo`,
`featureRowOps`, and the move-gesture commit in `MapWorkspace.tsx:2236` all
pair `layerType:'boundary'` with `featureId:'boundary'` correctly. The
remaining suspect is the V-3.1 change that arms the **whole active layer** for
vertex editing — the active layer supplies `layerType` while the selection
supplies `featureId`, so a boundary vertex grabbed while a block layer is
active would produce exactly this. Not confirmed.

**To pick this up you need one thing first:** a repro — which layer was active
in the panel, and what was clicked. The user reported on 2026-08-24 that vertex
editing otherwise **works fine**, so this is an edge, not the main path.

**Deliberately not done:** making the server treat `"boundary"` as the boundary
whatever `layerType` says. It would make the click succeed and then hand
boundary geometry to code that goes on to save it as a block — a worse bug than
the one reported.

---

## ⚠️ CORRECTION — the audit report calls `cf_db` "production"; it is not [2026-08-24]

The system owner confirmed on 2026-08-24 that **the application has never been
deployed, is not reachable from the internet, and every record in `cf_db` is
synthetic test data that will be wiped before go-live** — the 298 households, the
113,451 trees, the 18 users, all of it.

`industry_grade_report.md` says of the household data *"This is not a design risk.
It is live data."* and refers to `cf_db` as "the production database" in several
places. Both are wrong. S1-53 is annotated in place, and `PII_DECISION_BRIEF.md`
carries the correction in §0 and §7.

**What this changes:** urgency, not validity. Every finding still describes a real
defect that must be fixed before launch. What it removes is the incident framing —
nothing here is currently exposing anyone, and no finding needs fixing *today*
because of live risk.

**What it does NOT change, and is easy to miss:** the two PII questions that
*reduce* what is collected — is caste required by the regulations, and is
metre-precision location needed — get **cheaper and more valuable** in this
window, not less. Today they cost a schema edit. After the first real survey they
cost a migration, a disclosure question, and possibly re-consenting households.
**The planned pre-launch data wipe is the free moment to apply them.** That window
closes at go-live.

---

**Outstanding and explicitly the user's:** rotate the database password (28 untracked
files hold the literal, including both `.env` files) — the git-history purge was
deliberately declined, since the repo has no remote.

---

## 🟠 SUPERSEDED (was present until 2026-08-20) — VERTEX EDIT: SHARED/UNSHARED VERTEX EDITING RULES [2026-08-18]

**Plan file:** `map_design_ui_impl/vertex_edit_plan.md`
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — VERTEX EDIT" section

**Goal:** make vertex editing topology-safe. **Shared** vertices (on the common boundary of two same-level units, incl. mid-edge) move on BOTH units in one gesture (no gap / no overlap); **unshared (outer-shell)** vertices are locked. Rule A: forest boundary freely editable ONLY when no block/compartment/sub-compartment layer exists. Rule B: blocks/compartments/sub-compartments editable ONLY on shared vertices. **Only editable vertices are rendered** — the user cannot grab a locked vertex. **Boundary-shape edits re-clip existing sub-areas** (D6).

**Status:** design DONE + present-behavior verified + final review fixes applied 2026-08-18 (R1 clip + R6 validate-and-reject exist; `enforce_block_coverage` runs only on cut/merge, NOT vertex edits → silent block↔boundary gap hole; sub-area re-clip exists only in dead code → D6 added; boundary excluded from `edit-geometry`; Geoman renders every vertex; single-feature commit rejects most shared drags; local pre-check must be made propagation-aware). **V-1 (vertex classification engine) IMPLEMENTED — IN REVIEW 2026-08-18** (backend `vertex_classification_service.py` + frontend `vertexClassifier.ts` mirror; pytest 20/20 incl. new 17, vitest 15/15, tsc 0 new). **V-2 (atomic shared-vertex move, D2) IMPLEMENTED — IN REVIEW 2026-08-18** (backend commits `4d2c51f`: `_persist_geometry_batch` + `_features_with_propagated` + `shared_moves` payload, 8 new integration tests; frontend: `vertexSharedMove.ts` propagation + propagation-aware pre-check + multi-feature undo via `sharedMovePartners`; vitest 620/620, tsc 0 new). **V-3 (render-only-editable, D1) IMPLEMENTED — IN REVIEW 2026-08-19** (`vertexEditMask.ts` mask engine + `mask` option in `enableGeometryEdit` + per-layer mask wiring in MapWorkspace; vitest 637/637, tsc 0 new). **V-3.1 (selectionless rewrite + live-bug fixes) IMPLEMENTED — IN REVIEW 2026-08-19** — vertex_edit now arms the WHOLE active layer (no manual row/feature selection; toolbar button un-gated); `enableGeometryEdit` uses a layer-scoped registry view + per-entry closures that commit the DRAGGED layer's id/geometry (fixes "vertex moved but not saved" — the old commit sent no `Authorization` header → 401 → snapshot-restore; and boundary was POSTing to `edit-geometry` which `editing.py:653` rejects — now routed to `PUT /forests/calculations/{id}/boundary` with recomputed `area_hectares`, incl. undo/redo `applyVertexServer`); scoped arming also kills the Geoman marker leak (block edit no longer arms the global registry → no forest-boundary vertices visible during block edit). vitest 642/642 (80 files), tsc 7 errors (below the 8 baseline — the removed MapWorkspace:1696 `activeLayerId==='activity_features'` mask comparison was part of the baseline itself). **V-3.2 (tool separation + move-gesture parity) IMPLEMENTED — IN REVIEW 2026-08-19** — the vertex tool no longer body-drags the whole feature (Geoman's option is `draggable`, defaults true, and its `pm:dragend` was unheard by the vertex lifecycle → moved-but-never-committed); the move tool now uses the drag-only `enableLayerDrag()` API so it renders no vertex markers; the move commit gained `authHeaders()` + the boundary route, matching V-3.1. **V-4 (shared-edge add/delete, D4) IMPLEMENTED — IN REVIEW 2026-08-19** — `computeSharedVertexChange` inserts a vertex added on a shared edge into every same-level neighbour that owns the segment and deletes a shared vertex from all owners, shipped as the same V-2 `shared_moves` batch (no backend change); a delete that would drop a partner ring below a triangle is refused with `VERTEX_CHANGE_BLOCKED` + toast. Note this takes the plan's *alternative* for deletes (both-sides) rather than its stated default (block outright). Full gate: pytest 25/25, vitest 80 files / 653 tests, keySync 7/7, tsc 7 = baseline.

**Next action:** user retests on the running server — (1) drag a block vertex → saves (no revert); (2) forest-boundary vertex drag pre-structure → saves; (3) no forest-boundary markers during block vertex edit; (4) shared interior vertex moves BOTH units; (5) undo/redo replays whole shared batch; (6) move-mode drag saves and shows no vertex markers, and vertex-mode drag no longer moves the whole shape (V-3.2); (7) add a vertex on a shared edge → appears on both units and the next drag keeps them joined, delete a shared vertex → gone from both, delete that would collapse a neighbour → refused with a toast (V-4). Then V-5.

---

## 🟠 PREVIOUS PLAN (ON HOLD) — NEPALI-FIRST i18n [2026-08-16 → active until 2026-08-18]

**Plan file:** `map_design_ui_impl/IMPLEMENTATION_PLAN_NEPALI_FIRST_I18N.md`
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — NEPALI-FIRST i18n" section (top of file)

**Goal:** every UI string, error and suggestion available in Nepali **and** English, Nepali as the default for a fresh visitor, with a super-admin able to edit wording at runtime.

**Status:** Ph 0/1/2/3 ✅ COMPLETE (user green). Phase 4 batches **4a ✅, 4b ✅, 4c ✅, 4d ✅, 4e ✅, 4f ✅, 4g ✅, 4h ✅, 4i ✅** (all user green 2026-08-18). **D6 numeral policy revised + user green:** numerals follow the active language (Nepali Devanagari, English ASCII); output routed through `formatNumber`/`formatDecimal`, input through `parseLocaleNumber`. **Remaining (ON HOLD):** Ph 5 (persisted-status keys, DFO EN-message fix, generated outputs) → Ph 6 (governance & full verification). **Carried debt:** 45 of 48 numeric inputs still `type="number"` (ASCII-only); ~154 raw `toFixed`/`toLocaleString` outside migrated screens; `{treeMapping.status}` / `{inventory.status}` render raw backend status values (Ph 5).

---

## ✅ PREVIOUS PLAN (COMPLETE — USER GREEN 2026-08-18) — POINT-FILE IMPORT → FOREST BOUNDARY [2026-08-15]

**Plan file:** `map_design_ui_impl/IMPLEMENTATION_PLAN_POINT_IMPORT_BOUNDARY.md`
**Source report:** `map_design_ui_impl/REPORT_POINT_IMPORT_BOUNDARY.md` (rev.3 — deep research, user reviewed)
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — POINT IMPORT → BOUNDARY" section

**Goal:** let users import a CSV/XLSX/TXT of point coordinates (lat/lon in 4326/32644/32645, English or Nepali headers, DMS or decimal) and create the **forest boundary polygon** — ordered ring or concave hull — with Nepal-extent validation and a preview/confirm step.

**Status: ✅ COMPLETE — USER GREEN 2026-08-18.** Phases B-1…B-7 IMPLEMENTED + committed (`6e77c91`), plus follow-up fixes: preview-mapping 500→400 (DMS support), row-⋮-menu "Create Boundary from Point File" entry, **swapped-lat/lon ask→auto-fix** (`12e4dc3`): swap-detected CSV preview shows a confirm prompt instead of a 400 and `fix_swap=true` re-previews corrected points; import-time auto-swap on any point layer so "Skip / Assign Purpose Later" never stores points at the edge of the globe (`swapped_fixed` flag + UI toast); zero-area boundary CHECK 500 fixed via `feature_to_polygon(allow_point_hull=True)`; nullable unassigned-layer purpose (alembic `046`). Verification: `test_boundary_point_import.py` 22/22, `test_workspace_permissions.py` 20/20, vitest 71/71, keySync 6/6, tsc 0 new.

---

## 🟢 FOLLOW-ON — UNIFIED MAP DISPLAY REFRESH (P1 + P2) [IMPLEMENTED — awaiting user green]

**Plan file:** `map_design_ui_impl/IMPLEMENTATION_PLAN_MAP_DISPLAY_REFRESH.md`
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — MAP DISPLAY REFRESH" section

P1 (centralize `refreshAll()` + remove dead/redundant paths) and P2 (manual Refresh button in the Layer Panel) are **IMPLEMENTED + COMMITTED** (`8e1e56b`, `7411dfa` react-leaflet data-race fix, `302bc69` Add Sub-Area ⋮ menu) — superseded by the new present plan above before user testing. Awaiting user UI test/green signal; not the active initiative.

---

## ✅ COMPLETED — SAMPLING PAGE REWORK (A–H, user green 2026-08-15)

**Plan file:** `map_design_ui_impl/IMPLEMENTATION_PLAN_SAMPLING_PAGE_REWORK.md`
**Tracker:** `map_design_ui_impl/PROGRESS.md` → "PRESENT PLAN — SAMPLING PAGE REWORK" section (all rows ✅)

All phases A–H implemented + user green on 2026-08-15: A (scroll/layout), B (per-block design removed, DB-authoritative extract), C (mode-driven method: compartments → intensity 2% default, blocks → Guideline-2061 systematic first-priority / Random intensity fallback), D (Area Basis Tree Cover/Full), E (Type Systematic default/Random), F (pre-create sample-plot preview, deterministic replay), G (built-in read-only **Sample Plot** workspace layer + CSV/GeoJSON/GPX/KML export — edits explicitly declined by user), H (OP `map:sampling_plot*` + `sampling_*` variable integrity regression + full gates). Live data fixes along the way: NULL-area crash (`0e837af`), honest per-unit sampling method + true grid (`a4ba0cc`), full-area systematic under-sampling (`368dead`), tree-cover top-up not clustered (`eadae78`), accessible-area non-forest subtraction. Full `pytest` 977 passed (remaining errors are pre-existing env `arq` issues); `vitest` 531/531; e2e remnants pre-existing at `463b7e7`.

**Next action (completing-work policy):** plan is finished — no active tracked milestone here. Begin a NEW initiative only after the user states the next goal. **The new present plan is the Unified Map Display Refresh (see top).**

---

## 🟠 FOLLOW-ON (IN REVIEW — not the present plan)

| Plan | Status | Notes |
|------|--------|-------|
| Block Creation Paths + Boundary≡Blocks Area Invariant | 🔵 IN REVIEW | `IMPLEMENTATION_PLAN_BLOCK_BOUNDARY_INVARIANT.md`; E.1–E.8 implemented, awaiting user green; E.9 pending. |
| Unified Editing Toolset | 🔵/🟢 IN REVIEW | `unified_editing.md`; UE-0…UE-3 user-green; UE-4 (E2E) 🔵 IN REVIEW (layout fix + toolbar gating user-green 2026-08-11), remaining E2E scenarios pending. Auto-Blocks builds on this toolset. |

---

Historical note: the former present plan, **Unified Geometry Import → Polygons** (plan file `IMPLEMENTATION_PLAN_UNIFIED_GEOMETRY_IMPORT.md`), is ✅ **COMPLETE** (U-1→U-7 user green 2026-08-08) — kept for reference; not the active initiative.

---

---

Historical note: the former present plan, **Name-First CFOP Creation → Purpose-First Geometry** (plan file `NAME_FIRST_CREATION_PLAN.md`), is ✅ **COMPLETE** — its tracker rows in PROGRESS.md (phases 1–8 + post-GA fixes) are done and the name-goal is delivered. Kept for reference; no longer the active initiative.
The earlier **Tabbed Calculation Detail Page** (Phases 0–11) is also ✅ **COMPLETE**; its un-run external release gates (E2E live, Lighthouse, terraform, k8s, U-series) remain but are not the active initiative.

---

## ⛔ STALE / COMPLETE plans — DO NOT CONTINUE

| Plan | Status | Notes |
|------|--------|-------|
| Map Design UI Revamp (R1–R8, S11, S14) | ✅ COMPLETE | See `CLAUDE.md` historical section |
| Workspace Import + Layer UX + Map Lifecycle (P1–P3) | ✅ COMPLETE | `implementation_plan_consolidated.md` |
| Map & Workspace Unification (U01–U15) | ✅ CODE COMPLETE | Only release gates left: U03 go/no-go, U15 gate, flag flip (`unified_shell_default=true`) |
| Resizable Dock Panels | ✅ COMPLETE | 2026-08-01 |

---

## How to keep this file honest

After ANY session or completed phase:
1. Update the **Progress tracker** (`map_design_ui_impl/PROGRESS.md` → PRESENT PLAN section).
2. Update **`CLAUDE.md`** ("Current Work" section).
3. Update the **Current phase / Next action** lines above.

Never read the stale plans expecting them to be current. If a stale plan says something different from `CURRENT_PLAN.md`, **`CURRENT_PLAN.md` wins**.