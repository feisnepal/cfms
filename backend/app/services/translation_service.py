from __future__ import annotations

import csv
import io
import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TRANSLATIONS_DIR = Path("uploads/translations")
CSV_PATH = TRANSLATIONS_DIR / "geometry_np.csv"

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024

ALLOWED_COLUMNS = {"key", "en", "np", "context"}
REQUIRED_COLUMNS = {"key"}

NEPALI_UNICODE_RANGE = re.compile(r"[\u0900-\u097F]")

# Phase 3: repository root (backend/app/services -> parents[3] is repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_LOCALES_DIR = _REPO_ROOT / "frontend" / "src" / "i18n" / "locales"


def parse_translation_csv(content: bytes) -> Dict:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("utf-8")
            logger.debug("CSV decoded as UTF-8 (no BOM)")
        except UnicodeDecodeError as e:
            raise ValueError(f"Cannot decode CSV: expected UTF-8 encoding, got {e}")

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    field_map: Dict[str, str] = {}
    for col in reader.fieldnames:
        normalized = col.strip().lower()
        field_map[normalized] = col

    missing_columns = ALLOWED_COLUMNS - set(field_map.keys())
    if "key" in missing_columns:
        raise ValueError(
            f"CSV must have 'key' column. Found columns: {list(field_map.keys())}"
        )

    unknown_cols = set(field_map.keys()) - ALLOWED_COLUMNS
    if unknown_cols:
        logger.warning("CSV contains unexpected columns: %s", unknown_cols)

    overlay: Dict[str, Dict] = {"ne": {}, "en": {}}
    errors: List[Dict[str, str]] = []
    key_count = 0
    seen_keys: set = set()

    for row_idx, row in enumerate(reader, start=2):
        key = row.get(field_map.get("key", "key"), "").strip()
        en_val = row.get(field_map.get("en", "en"), "").strip()
        np_val = row.get(field_map.get("np", "np"), "").strip()

        if not key:
            errors.append({"row": str(row_idx), "column": "key", "error": "Empty key"})
            continue

        if not re.match(r"^[a-zA-Z][\w.]*$", key):
            errors.append({
                "row": str(row_idx),
                "column": "key",
                "error": f"Invalid key format. Must start with a letter, contain only alphanumeric, dots, underscores",
            })
            continue

        if key in seen_keys:
            logger.warning("Duplicate key at row %d: '%s' -- using last occurrence", row_idx, key)
        seen_keys.add(key)

        parts = key.split(".")

        if np_val:
            _set_nested(overlay["ne"], parts, np_val)
        if en_val:
            _set_nested(overlay["en"], parts, en_val)

        key_count += 1

    result: Dict = {
        "ne": overlay["ne"],
        "en": overlay["en"],
        "key_count": key_count,
    }

    if errors:
        result["errors"] = errors

    return result


def _set_nested(d: Dict, parts: List[str], value: str) -> None:
    current = d
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def save_translation_csv(content: bytes) -> Optional[str]:
    # The directory is created here, on the one path that writes, rather than
    # at import. `TRANSLATIONS_DIR.mkdir(...)` used to run at module scope,
    # which made importing this module a filesystem mutation: `main.py` imports
    # `api.translations`, which imports this, so ANY process that touched the
    # app -- uvicorn, alembic, pytest collection, the router gates -- created
    # directories as a side effect of an import, and a directory it could not
    # create was not a failed upload but an unimportable application.
    #
    # That is exactly how it failed: under docker compose the container runs as
    # appuser (uid 10001, added in H5.1) while ./uploads is bind-mounted from
    # the host and owned by the host user, so this mkdir raised PermissionError
    # at import and uvicorn never started -- the backend "never became healthy"
    # in compose-smoke with no clue as to why. Every other reader here already
    # guards with .exists(), so this is the only site that needed it.
    try:
        TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise IOError(f"Failed to create translations directory: {e}")

    backup_name: Optional[str] = None
    if CSV_PATH.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"geometry_np_{timestamp}.csv"
        backup_path = TRANSLATIONS_DIR / backup_name

        try:
            CSV_PATH.rename(backup_path)
            logger.info("Archived previous translations -> %s", backup_name)
        except OSError as e:
            raise IOError(f"Failed to archive previous CSV: {e}")

    try:
        CSV_PATH.write_bytes(content)
        logger.info("Saved new translations CSV (%d bytes)", len(content))
    except OSError as e:
        if backup_name and (TRANSLATIONS_DIR / backup_name).exists():
            (TRANSLATIONS_DIR / backup_name).rename(CSV_PATH)
            logger.warning("Rolled back to previous version after write failure")
        raise IOError(f"Failed to write CSV: {e}")

    return backup_name


def get_overlay_json() -> Dict:
    if not CSV_PATH.exists():
        logger.debug("No translations CSV found at %s -- returning empty overlay", CSV_PATH)
        return {"ne": {}, "en": {}}

    try:
        content = CSV_PATH.read_bytes()
        result = parse_translation_csv(content)
        return {
            "ne": result.get("ne", {}),
            "en": result.get("en", {}),
        }
    except (ValueError, IOError) as e:
        logger.error("Failed to read translations CSV: %s", e)
        return {"ne": {}, "en": {}}


def list_archived_versions() -> List[Path]:
    if not TRANSLATIONS_DIR.exists():
        return []

    pattern = "geometry_np_*.csv"
    archives = sorted(
        TRANSLATIONS_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )

    archives = [p for p in archives if p.name != CSV_PATH.name]

    return archives


def get_translation_stats() -> Dict:
    stats: Dict = {
        "total_keys": 0,
        "ne_keys": 0,
        "en_keys": 0,
        "file_size_bytes": 0,
        "last_modified": None,
        "archive_count": 0,
    }

    if CSV_PATH.exists():
        stats["file_size_bytes"] = CSV_PATH.stat().st_size
        stats["last_modified"] = datetime.fromtimestamp(
            CSV_PATH.stat().st_mtime
        ).isoformat()

        try:
            result = parse_translation_csv(CSV_PATH.read_bytes())
            ne_keys = _count_leaf_keys(result.get("ne", {}))
            en_keys = _count_leaf_keys(result.get("en", {}))
            stats["total_keys"] = max(ne_keys, en_keys)
            stats["ne_keys"] = ne_keys
            stats["en_keys"] = en_keys
        except ValueError:
            pass

    stats["archive_count"] = len(list_archived_versions())

    return stats


def _count_leaf_keys(d: Dict, prefix: str = "") -> int:
    count = 0
    for key, value in d.items():
        if isinstance(value, dict):
            count += _count_leaf_keys(value, f"{prefix}{key}.")
        elif isinstance(value, str):
            count += 1
    return count


# ---------------------------------------------------------------- Phase 3 DB ----

def _flatten_nested_json(data: Dict, prefix: str = "") -> Dict[str, str]:
    """Flatten a nested bundle dict into ``dotted.key`` -> leaf string."""
    out: Dict[str, str] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten_nested_json(value, f"{dotted}."))
        elif isinstance(value, str) and value.strip():
            out[dotted] = value
    return out


def load_bundle_pairs() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load en/ne bundle leaves as ``dotted.key`` -> string.

    Returns ``(en_leaves, ne_leaves)``; empty dicts when the frontend
    locale bundles are not present (e.g. bare backend checkout).
    """
    en_leaves: Dict[str, str] = {}
    ne_leaves: Dict[str, str] = {}
    try:
        en_path = FRONTEND_LOCALES_DIR / "en.json"
        ne_path = FRONTEND_LOCALES_DIR / "ne.json"
        if en_path.exists():
            with open(en_path, encoding="utf-8") as fh:
                en_leaves = _flatten_nested_json(json.load(fh))
        if ne_path.exists():
            with open(ne_path, encoding="utf-8") as fh:
                ne_leaves = _flatten_nested_json(json.load(fh))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read frontend locale bundles: %s", exc)
    return en_leaves, ne_leaves


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
CONTEXT_NOTES_DIR = _REPO_ROOT / "translations"


def placeholders_of(text: Optional[str]) -> List[str]:
    """The ``{{name}}`` placeholders in a message, in order, without repeats."""
    seen: List[str] = []
    for name in _PLACEHOLDER.findall(text or ""):
        if name not in seen:
            seen.append(name)
    return seen


def missing_placeholders(
    db: Session, key: str, en: Optional[str], ne: Optional[str]
) -> List[str]:
    """Placeholders the shipped English text has that an edit drops.

    A reviewer changing the wording must not be able to break a message: ``{{activity}}`` missing from
    a sentence would print a hole (or the raw braces) in front of a user. The English *bundle* text is the
    source of truth for which placeholders a key needs; each supplied language is checked against it.
    """
    from app.models.translation import Translation

    en_leaves, _ne = load_bundle_pairs()
    source = en_leaves.get(key)
    if source is None:
        row = db.query(Translation).filter(Translation.key == key).first()
        source = row.en if row else None
    needed = placeholders_of(source)
    if not needed:
        return []
    missing: List[str] = []
    for value in (en, ne):
        if value is None or not str(value).strip():
            continue
        have = set(placeholders_of(value))
        for name in needed:
            if name not in have and "{{" + name + "}}" not in missing:
                missing.append("{{" + name + "}}")
    return missing


def load_context_notes() -> Dict[str, str]:
    """``key -> "where this appears / what the placeholders mean"`` from ``translations/*_context.json``.

    The ``context`` column exists on the table but nothing filled it, so a reviewer saw the words and
    not *when* the sentence appears. Each file is a flat ``{"dotted.key": "note"}`` object.
    """
    notes: Dict[str, str] = {}
    try:
        for path in sorted(CONTEXT_NOTES_DIR.glob("*_context.json")):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                notes.update({str(k): str(v) for k, v in data.items() if v})
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read translation context notes: %s", exc)
    return notes


def seed_translations(db: Session) -> int:
    """Reconcile the ``translations`` table with the shipped bundle.

    **This used to be a one-shot and that was the bug.** The guard was
    ``if db.query(Translation).count() > 0: return 0`` — so it ran once, when
    the bundle held about 535 keys, and never again. By 2026-08-24 the bundle
    held 4,777 and the table still held 536: every string added in between was
    invisible to the super-admin translation editor, including ones months old
    (``layerPanel.addSubArea``, ``layerPanel.newBlock``). Worse, the endpoints
    call this on every request, so the code *looked* like it reconciled while
    returning 0 immediately.

    It now reconciles on every call, and is cheap enough to: one query for the
    existing keys, then only the differences are written.

    Two rules make this safe to run repeatedly:

    - **An override is never touched.** ``is_override`` is set by
      ``upsert_translation`` on any explicit edit, so it marks human work. Rows
      carrying it are left exactly as they are.
    - **A non-override row is a default, so it is refreshed.** ``is_override``
      false means nobody has ever edited that row, so its value is only a mirror
      of the bundle. Leaving a stale mirror would show the editor a string the
      application no longer uses.

    Only ``is_override`` rows reach the frontend (see ``get_overlay_rows``), so
    none of this changes what a user sees — it changes what the editor can
    *reach*, which was the whole defect.

    Returns the number of rows inserted or refreshed.
    """
    from app.models.translation import Translation

    en_leaves, ne_leaves = load_bundle_pairs()
    bundle_keys = set(en_leaves) | set(ne_leaves)
    if not bundle_keys:
        # A missing or unreadable bundle must not be read as "delete everything".
        logger.warning("Translation bundle produced no keys; skipping reconciliation")
        return 0

    table_was_empty = db.query(Translation).first() is None

    existing = {
        row.key: row
        for row in db.query(Translation).filter(Translation.key.in_(bundle_keys)).all()
    } if not table_was_empty else {}

    touched = 0
    for key in sorted(bundle_keys):
        row = existing.get(key)
        en_val, ne_val = en_leaves.get(key), ne_leaves.get(key)
        if row is None:
            db.add(Translation(
                key=key,
                en=en_val,
                ne=ne_val,
                source_file="bundle",
                is_override=False,
                reviewed=False,
            ))
            touched += 1
        elif not row.is_override and (row.en != en_val or row.ne != ne_val):
            # A default that has drifted from the bundle it mirrors.
            row.en, row.ne = en_val, ne_val
            touched += 1

    db.flush()

    # The CSV import stays first-run-only. Re-running it would push legacy CSV
    # values back over anything edited in the admin page since — the one way
    # this function could destroy human work.
    if table_was_empty and CSV_PATH.exists():
        try:
            result = parse_translation_csv(CSV_PATH.read_bytes())
        except (ValueError, IOError) as exc:
            logger.warning("Skipping CSV backfill (parse failed): %s", exc)
            result = {}
        for key, value in result.get("ne", {}).items():
            for leaf, ne_val in _flatten_nested_json(value if isinstance(value, str) else {key: value}, key).items():
                row = db.query(Translation).filter(Translation.key == leaf).first()
                if row is None:
                    db.add(Translation(
                        key=leaf,
                        ne=ne_val,
                        source_file="csv",
                        is_override=True,
                        reviewed=False,
                    ))
                    touched += 1
                elif ne_val:
                    row.ne = ne_val
                    row.source_file = "csv"
                    row.is_override = True
        for key, value in result.get("en", {}).items():
            for leaf, en_val in _flatten_nested_json(value if isinstance(value, str) else {key: value}, key).items():
                row = db.query(Translation).filter(Translation.key == leaf).first()
                if row is not None and en_val:
                    row.en = en_val

    # A note is metadata, not wording: fill an EMPTY context for any row (override or not); never
    # overwrite one somebody has written.
    notes = load_context_notes()
    if notes:
        for row in db.query(Translation).filter(Translation.key.in_(list(notes))).all():
            if not row.context:
                row.context = notes[row.key]
                touched += 1

    if touched:
        db.commit()
        logger.info("Reconciled translations table: %d row(s) inserted or refreshed", touched)
    return touched


def get_overlay_rows(db: Session) -> Dict[str, Dict[str, object]]:
    """Return ``{ne: {nested overlay}, en: {nested overlay}}`` for overrides.

    Mirrors the legacy CSV overlay shape (nested dicts by dotted key) so the
    frontend merge path is unchanged: only ``is_override`` rows are returned.
    """
    from app.models.translation import Translation

    rows = db.query(Translation).filter(Translation.is_override.is_(True)).all()
    ne: Dict[str, object] = {}
    en: Dict[str, object] = {}
    for row in rows:
        if row.ne:
            _set_nested(ne, row.key.split("."), row.ne)
        if row.en:
            _set_nested(en, row.key.split("."), row.en)
    return {"ne": ne, "en": en}


def upsert_translation(
    db: Session,
    key: str,
    en: Optional[str],
    ne: Optional[str],
    user_id=None,
    note: Optional[str] = None,
) -> dict:
    """Create or update a translations row; append prior values to history.

    Setting ``is_override=True`` (any explicit edit makes the row an override).
    Returns a plain dict for the API response.
    """
    from app.models.translation import Translation

    import uuid as _uuid

    row = db.query(Translation).filter(Translation.key == key).first()
    now = datetime.now(timezone.utc).isoformat()
    changed, from_en, from_ne = False, row.en if row else None, row.ne if row else None

    if row is None:
        row = Translation(
            key=key,
            en=en,
            ne=ne,
            source_file="editor",
            is_override=True,
            reviewed=False,
            updated_by=_uuid.UUID(str(user_id)) if user_id else None,
            history=[],
        )
        db.add(row)
        changed = bool(en or ne)
    else:
        row.en = en if en is not None else row.en
        row.ne = ne if ne is not None else row.ne
        row.source_file = "editor"
        row.is_override = True
        row.updated_by = _uuid.UUID(str(user_id)) if user_id else None
        changed = (row.en != from_en) or (row.ne != from_ne)

    if changed:
        history = list(row.history or [])
        history.append({
            "ts": now,
            "user": str(user_id) if user_id else None,
            "from_en": from_en,
            "from_ne": from_ne,
            "to_en": row.en,
            "to_ne": row.ne,
            "note": note,
        })
        row.history = history

    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "key": row.key,
        "en": row.en,
        "ne": row.ne,
        "context": row.context,
        "source_file": row.source_file,
        "is_override": row.is_override,
        "reviewed": row.reviewed,
        "updated_by": str(row.updated_by) if row.updated_by else None,
        "history": row.history or [],
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_translations(
    db: Session,
    search: Optional[str] = None,
    lang_is_empty: Optional[str] = None,
    override_only: bool = False,
    category: Optional[str] = None,
    reviewed: Optional[bool] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict:
    """Paginated admin listing with search + filter support."""
    from app.models.translation import Translation

    query = db.query(Translation)
    if search:
        query = query.filter(
            (Translation.key.ilike(f"%{search}%"))
            | (Translation.en.ilike(f"%{search}%"))
            | (Translation.ne.ilike(f"%{search}%"))
        )
    if override_only:
        query = query.filter(Translation.is_override.is_(True))
    if reviewed is not None:
        query = query.filter(Translation.reviewed.is_(reviewed))
    if lang_is_empty in ("ne", "en"):
        col = Translation.ne if lang_is_empty == "ne" else Translation.en
        query = query.filter((col.is_(None)) | (col == ""))
    if category:
        cat_prefix = f"{category}."
        query = query.filter(Translation.key.like(f"{cat_prefix}%"))

    total = query.count()
    rows = (
        query.order_by(Translation.key.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    items = [
        {
            "id": row.id,
            "key": row.key,
            "en": row.en,
            "ne": row.ne,
            "context": row.context,
            "source_file": row.source_file,
            "is_override": row.is_override,
            "reviewed": row.reviewed,
            "updated_by": str(row.updated_by) if row.updated_by else None,
            "history_count": len(row.history or []),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def get_translation_stats(db: Session) -> Dict:
    """Extended stats: DB counts + legacy CSV archive counts."""
    from app.models.translation import Translation

    total = db.query(Translation).count()
    untranslated_ne = (
        db.query(Translation)
        .filter((Translation.ne.is_(None)) | (Translation.ne == ""))
        .count()
    )
    overrides = db.query(Translation).filter(Translation.is_override.is_(True)).count()
    reviewed = db.query(Translation).filter(Translation.reviewed.is_(True)).count()

    stats = {
        "total_keys": total,
        "ne_keys": total - untranslated_ne,
        "en_keys": (
            db.query(Translation)
            .filter((Translation.en.is_(None)) | (Translation.en == ""))
            .count()
        ),
        "untranslated_ne": untranslated_ne,
        "overrides": overrides,
        "reviewed": reviewed,
        "archive_count": len(list_archived_versions()),
    }
    return stats


def make_translator(db: Session, lang: str):
    """A ``translate(key, **params)`` for server-built text (e.g. the forest summary verdict).

    Wording comes from the ``translations`` table when an admin has set it (the row's text for ``lang``), else from the shipped
    frontend bundle, else the English of either; ``{{name}}`` placeholders are filled from ``params``. Returns ``None`` for a key
    nobody knows, so the caller can leave that clause out instead of printing a raw key.
    """
    from app.models.translation import Translation

    lang = "ne" if str(lang).lower().startswith("ne") else "en"
    en_leaves, ne_leaves = load_bundle_pairs()
    bundle = {"en": en_leaves, "ne": ne_leaves}
    rows = {r.key: r for r in db.query(Translation).filter(Translation.key.like("forestSummary.%")).all()}

    def translate(key: str, **params):
        row = rows.get(key)
        text = None
        for code in (lang, "en"):
            value = getattr(row, code, None) if row is not None else None
            text = (value or "").strip() or bundle[code].get(key)
            if text:
                break
        if not text:
            return None
        return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)

    return translate
