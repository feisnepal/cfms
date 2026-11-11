"""One-shot helper for task H1.16 — declare DB-only indexes in the models.

84 indexes exist in the database and in production but are declared by no model,
so `alembic revision --autogenerate` proposes DROPping every one of them. This
reads each index's real definition from ``pg_indexes`` and writes a matching
``Index(...)`` into the owning model's ``__table_args__``.

Definitions come from the database rather than from guesswork, and the index
NAME is preserved exactly: a differently-named equivalent reads as one dropped
and one added, which makes the drift worse rather than better.

Not every index can be expressed this way. Expression indexes (``to_tsvector``,
``st_transform``) and some partial indexes cannot be reliably round-tripped by
Alembic's comparison, so they are reported and skipped rather than declared
wrongly — see the task notes.

    python scripts/declare_missing_indexes.py --dry-run
    python scripts/declare_missing_indexes.py --apply
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

import sqlalchemy as sa

BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
BASELINE = BACKEND / "alembic_drift_baseline.txt"
MODELS = BACKEND / "app" / "models"

# CREATE [UNIQUE] INDEX name ON public.table USING method (cols) [WHERE pred]
DDL = re.compile(
    r"CREATE\s+(?P<uniq>UNIQUE\s+)?INDEX\s+(?P<name>\S+)\s+ON\s+\S+\s+"
    r"USING\s+(?P<method>\w+)\s+\((?P<cols>.*?)\)(?:\s+WHERE\s+(?P<where>.*))?$",
    re.S,
)


def wanted() -> dict[str, str]:
    """index name -> table, from the drift baseline."""
    out = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"Detected removed index '([^']+)' on '([^']+)'", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def render(name: str, ddl: str) -> tuple[str, list[str]] | None:
    """Render (Index(...) call, column names), or None if not faithfully expressible."""
    m = DDL.match(ddl.strip())
    if not m:
        return None
    cols = m.group("cols").strip()
    # Expression indexes carry function calls or casts; SQLAlchemy needs text()
    # and Alembic cannot match them back reliably. Skip rather than mis-declare.
    if "(" in cols or "::" in cols:
        return None

    parts = [f"'{name}'"] + [f"'{c.strip()}'" for c in cols.split(",")]
    if m.group("uniq"):
        parts.append("unique=True")
    if m.group("method").lower() != "btree":
        parts.append(f"postgresql_using='{m.group('method').lower()}'")
    if m.group("where"):
        pred = m.group("where").strip().rstrip(";")
        parts.append(f"postgresql_where=text({pred!r})")
    return f"Index({', '.join(parts)})", [c.strip() for c in cols.split(",")]


def model_for(table: str) -> tuple[pathlib.Path, str] | None:
    for p in sorted(MODELS.glob("*.py")):
        src = p.read_text(encoding="utf-8")
        for cm in re.finditer(r"class (\w+)\(Base\):(.*?)(?=\nclass |\Z)", src, re.S):
            tn = re.search(r"__tablename__\s*=\s*[\"'](\w+)[\"']", cm.group(2))
            if tn and tn.group(1) == table:
                return p, cm.group(1)
    return None


def inject(path: pathlib.Path, cls: str, decls: list[str]) -> bool:
    """Add Index(...) entries to a class's __table_args__, creating it if absent."""
    src = path.read_text(encoding="utf-8")
    cm = re.search(rf"class {cls}\(Base\):(.*?)(?=\nclass |\Z)", src, re.S)
    if not cm:
        return False
    body, start, end = cm.group(1), cm.start(1), cm.end(1)
    added = ",\n        ".join(decls)

    ta = re.search(r"\n    __table_args__\s*=\s*\(", body)
    if ta:
        # Insert just after the opening paren of the existing tuple.
        pos = start + ta.end()
        new = src[:pos] + f"\n        {added}," + src[pos:]
    else:
        tn = re.search(r"\n    __tablename__\s*=\s*[\"']\w+[\"']\n", body)
        if not tn:
            return False
        pos = start + tn.end()
        new = src[:pos] + f"    __table_args__ = (\n        {added},\n    )\n" + src[pos:]

    # Ensure the names we emit are imported.
    need = ["Index"] + (["text"] if any("text(" in d for d in decls) else [])
    for sym in need:
        if not re.search(rf"\b{sym}\b", new.split("class ")[0]):
            new = re.sub(r"(from sqlalchemy import )([^\n]+)", rf"\1{sym}, \2", new, count=1)
    path.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    # H1.13 follow-up: no credential default. A password baked in as a default
    # is a password in the repo, and this script's default target (`cf_chk`)
    # made it look harmless enough to survive the first sweep.
    ap.add_argument(
        "--url",
        default=os.environ.get("CHECK_DATABASE_URL", ""),
        help="SQLAlchemy URL of the schema-check database. Defaults to "
             "$CHECK_DATABASE_URL; there is deliberately no built-in fallback.",
    )
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("pass --dry-run or --apply")
    if not args.url:
        ap.error("pass --url or set CHECK_DATABASE_URL")

    conn = sa.create_engine(args.url).connect()
    ddls = {
        r[0]: r[1]
        for r in conn.execute(sa.text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'"
        ))
    }

    # An Index can only reference columns the model declares. 24 columns exist
    # in the database and in production but no model declares them, so indexes
    # over those cannot be added until the columns are — the two drift
    # categories are entangled. Detect that here rather than discovering it as
    # a ConstraintColumnNotFoundError at import.
    import warnings
    warnings.filterwarnings("ignore")
    from app.core.database import Base
    import app.models  # noqa: F401  (registers mappers)
    model_cols = {
        t.name: {c.name for c in t.columns} for t in Base.metadata.tables.values()
    }

    by_table: dict[str, list[str]] = {}
    skipped: list[tuple[str, str]] = []
    for name, table in sorted(wanted().items()):
        ddl = ddls.get(name)
        if not ddl:
            skipped.append((name, "not present in the database"))
            continue
        rendered = render(name, ddl)
        if rendered is None:
            skipped.append((name, "expression index — cannot be matched by autogenerate"))
            continue
        decl, cols = rendered
        absent = [c for c in cols if c not in model_cols.get(table, set())]
        if absent:
            skipped.append((name, f"model lacks column(s) {absent} — blocked on declaring them"))
            continue
        by_table.setdefault(table, []).append(decl)

    total = sum(len(v) for v in by_table.values())
    print(f"declarable: {total} across {len(by_table)} tables")
    print(f"skipped:    {len(skipped)}")
    for n, why in skipped:
        print(f"    {n}: {why}")

    if args.dry_run:
        for t, d in sorted(by_table.items()):
            print(f"\n  {t}:")
            for x in d:
                print(f"    {x}")
        return 0

    done = 0
    for table, decls in sorted(by_table.items()):
        hit = model_for(table)
        if not hit:
            print(f"  !! no model for {table}")
            continue
        path, cls = hit
        if inject(path, cls, decls):
            done += len(decls)
            print(f"  {path.name}::{cls} += {len(decls)}")
    print(f"\ndeclared {done} indexes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
