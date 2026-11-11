"""ND-0 harness: read-only nodata ("डाटा उपलब्ध छैन") report for an Operational Plan.

Two modes:

  python scripts/op_nodata_report.py docx <path-or-glob> [--max N] [out.txt]
      Count markers in an exported .docx.
      TOTAL = nodata paragraph-entries + nodata table-cells (baseline 41 = 33 + 8).

  python scripts/op_nodata_report.py plan <plan-id | forest-name> [--max N] [out.txt]
      Resolve the plan the way the DOCX export does (effective tree, content
      resolution, the export's user_inputs merge, the builder's cell path) and
      report per bucket:
        content-markers   inline nodata the builder will colour red
        cell-markers      static_table / inline_tables cells rendering nodata
        inline-table     {{inline_table:N}} tokens left for the builder (post-ND-1
                         these are legitimate; pre-ND-1 they show up as content
                         markers instead — watch content-markers, not this count)
        structural       map/chart/table/asset/:full tokens left for the builder
        empty-list        value tokens resolving to [] (builder prints parens)
        no-data-tokens    non-prefixed tokens with no data (root causes)
        title             tokens in title_ne/title_en (never substituted)
        readiness         plan_readiness total/resolved/missing/unmet/unverified

      --max applies to content-markers + cell-markers.

Exit code 1 when --max is given and the tracked total exceeds it (gate mode).
All reports are written UTF-8; the console only ever sees ASCII summary lines.
"""
from __future__ import annotations

import argparse
import glob
import inspect
import io
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARKER = "डाटा उपलब्ध छैन"
TOKEN_RE = re.compile(r"\{\{(\w+(?::\w+)*)\}\}")
STRUCTURAL_PREFIXES = ("chart:", "map:", "thememap:", "opsmap:", "table:", "asset:")


def _utf8_stdout() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- docx mode


def cmd_docx(pattern: str, out_path: str | None, max_nodata: int | None) -> int:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    paths = glob.glob(pattern) if any(ch in pattern for ch in "*?[") else [pattern]
    if not paths:
        print(f"ERROR: no docx matches {pattern!r}")
        return 2
    doc = Document(paths[0])

    def iter_blocks(parent):
        for child in parent.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    lines: list[str] = []
    heading = ""
    last_para = ""
    para_entries = 0
    cell_hits = 0
    tables_with_hits = 0
    block_no = 0

    for block in iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text or ""
            style = (block.style.name if block.style is not None else "") or ""
            if "Heading" in style or "Title" in style:
                heading = text.strip()[:120]
            if MARKER in text:
                block_no += 1
                para_entries += 1
                lines.append(
                    f"[{block_no}] para | heading={heading!r} | style={style!r} | "
                    f"text={text.strip()[:300]!r}"
                )
            last_para = text.strip()[:120]
        else:
            th = 0
            example = ""
            for row in block.rows:
                for cell in row.cells:
                    if MARKER in (cell.text or ""):
                        th += 1
                        if not example:
                            example = (cell.text or "").strip()[:200]
            if th:
                block_no += 1
                cell_hits += th
                tables_with_hits += 1
                try:
                    header = " | ".join(
                        (c.text or "").strip()[:40] for c in block.rows[0].cells[:8]
                    )
                except Exception:
                    header = ""
                lines.append(
                    f"[{block_no}] table ({len(block.rows)}r x {len(block.columns)}c) | "
                    f"heading={heading!r} | above={last_para!r} | header={header!r} | "
                    f"no_data_cells={th} | e.g.={example!r}"
                )

    total = para_entries + cell_hits
    summary = (
        f"file: {paths[0]}\n"
        f"TOTAL no-data markers: {total} | in paragraphs: {para_entries} | "
        f"in tables: {tables_with_hits} tables ({cell_hits} cells)\n\n"
    )
    out = out_path or str(Path(__file__).with_name("op_nodata_report.txt"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(summary)
        f.write("\n".join(lines))
    print(f"docx markers: total={total} paragraphs={para_entries} cells={cell_hits} "
          f"blocks={len(lines)} -> {out}")
    if max_nodata is not None and total > max_nodata:
        print(f"GATE FAIL: total {total} > max {max_nodata}")
        return 1
    return 0


# --------------------------------------------------------------------------- plan mode


def _load_plan(db, ref: str):
    from sqlalchemy import select

    from app.models.operational_plan import OperationalPlan

    try:
        import uuid

        pid = uuid.UUID(ref)
        plan = db.execute(
            select(OperationalPlan).where(OperationalPlan.id == pid)
        ).scalar_one_or_none()
        if plan is not None:
            return plan
    except ValueError:
        pass
    plans = (
        db.execute(
            select(OperationalPlan)
            .where(OperationalPlan.forest_name.ilike(f"%{ref}%"))
            .order_by(OperationalPlan.updated_at.desc_nullslast())
            .limit(5)
        )
        .scalars()
        .all()
    )
    if not plans:
        raise SystemExit(f"ERROR: no operational plan matches {ref!r}")
    if len(plans) > 1:
        print(f"note: {len(plans)} plans match {ref!r}; using the most recently updated")
    return plans[0]


def _all_cell_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_cell_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_cell_strings(v)


def cmd_plan(ref: str, out_path: str | None, max_nodata: int | None) -> int:
    # the app's engine echo floods stdout; this script only prints its own summary
    logging.disable(logging.INFO)
    from app.core.database import SessionLocal
    from app.models.operational_plan import OperationalPlan  # noqa: F401
    from app.services.operational_plan import no_data
    from app.services.operational_plan.forest_shared_fields import shared_values
    from app.services.operational_plan.op_docx_builder import _resolve_var_text
    from app.services.operational_plan.plan_live import effective_tree
    from app.services.operational_plan.variable_resolver import (
        VARIABLE_REGISTRY,
        VariableResolver,
    )

    db = SessionLocal()
    try:
        plan = _load_plan(db, ref)
        calc_id = plan.calculation_id
        tree = effective_tree((plan.sections or {}).get("tree") or [])
        resolver = VariableResolver(db, calc_id, plan)

        # exactly what the export does before the builder runs (operational_plans.py)
        raw = resolver.get_raw_data()
        metadata = plan.plan_metadata or {}
        raw["user_inputs"] = {
            **(metadata.get("user_inputs") or {}),
            **shared_values(db, calc_id),
        }

        def call_cell(text: str) -> str:
            """The builder's cell rendering, passing the resolver when the
            signature supports it (ND-2 adds it)."""
            kwargs = {}
            if "resolver" in inspect.signature(_resolve_var_text).parameters:
                kwargs["resolver"] = resolver
            try:
                return _resolve_var_text(text, raw, **kwargs)
            except Exception as e:
                return f"<CELL ERROR {e!r}>"

        value_cache: dict[str, object] = {}

        def reg_value(key: str):
            if key not in value_cache:
                if VARIABLE_REGISTRY.get(key) is None:
                    value_cache[key] = "<NOT IN REGISTRY>"
                else:
                    try:
                        value_cache[key] = resolver.resolve_keys([key]).get(
                            key, "<ABSENT>"
                        )
                    except Exception as e:
                        value_cache[key] = f"<ERROR {e!r}>"
            return value_cache[key]

        def brief(v) -> str:
            if isinstance(v, str) and len(v) > 90:
                return v[:87] + "..."
            if isinstance(v, (list, dict)):
                return f"<{type(v).__name__} len={len(v)}>"
            return repr(v)

        lines: list[str] = [
            f"plan={plan.id} calc={calc_id} forest={plan.forest_name!r} "
            f"status={plan.status}"
        ]
        content_markers = 0
        cell_markers = 0
        rc1_inline = 0
        structural: list[str] = []
        empty_lists: list[str] = []
        no_data_tokens: list[str] = []
        title_tokens: list[str] = []
        nodes_with_issues = 0

        def walk(nodes, path):
            nonlocal content_markers, cell_markers, rc1_inline, nodes_with_issues
            for n in nodes:
                if not isinstance(n, dict):
                    n = n.model_dump() if hasattr(n, "model_dump") else dict(n)
                if n.get("deleted"):
                    continue
                title = (n.get("title_ne") or n.get("title_en") or "").strip()
                here = path + [title]
                content = n.get("content") or ""
                node_issues: list[str] = []

                # --- content: what the export's resolve_for_output produces
                try:
                    resolved = resolver.resolve_node_content(content)
                except Exception as e:
                    resolved = f"<CONTENT RESOLVE ERROR {e}>"
                n_marks = resolved.count(no_data.OPEN)
                if n_marks:
                    content_markers += n_marks
                    node_issues.append(f"content markers: {n_marks}")
                for tok in TOKEN_RE.findall(resolved):
                    if "{{" + tok + "}}" not in resolved:
                        continue  # token was substituted or marked already
                    if tok.startswith("inline_table"):
                        rc1_inline += 1
                        node_issues.append(f"inline_table token (builder handles): {tok}")
                    elif tok.startswith(STRUCTURAL_PREFIXES) or tok.endswith(":full"):
                        structural.append(f"{' > '.join(here)} :: {tok}")
                    else:
                        rv = reg_value(tok)
                        if rv == []:
                            empty_lists.append(f"{' > '.join(here)} :: {tok}")
                            node_issues.append(f"empty-list token: {tok}")
                        else:
                            no_data_tokens.append(
                                f"{' > '.join(here)} :: {tok} -> {brief(rv)}"
                            )
                            node_issues.append(f"no-data token: {tok} -> {brief(rv)}")

                # --- cells: the builder's own cell path (post-merge raw)
                for surface, cells in (
                    ("ST", n.get("static_table")),
                    ("INLINE", n.get("inline_tables") or []),
                ):
                    for cell in _all_cell_strings(cells) if cells else []:
                        if not TOKEN_RE.search(cell):
                            continue
                        rendered = call_cell(cell)
                        if no_data.OPEN in rendered:
                            cell_markers += rendered.count(no_data.OPEN)
                            toks = TOKEN_RE.findall(cell)
                            node_issues.append(
                                f"{surface} cell markers: {rendered.count(no_data.OPEN)} "
                                f"tokens={toks}"
                            )

                # --- title tokens (never substituted)
                for tok in TOKEN_RE.findall(title):
                    title_tokens.append(f"{' > '.join(here)} :: {tok}")
                    node_issues.append(f"title token: {tok}")

                if node_issues:
                    nodes_with_issues += 1
                    lines.append(f"\n  [{' > '.join(here)}]")
                    for issue in node_issues:
                        lines.append(f"    {issue}")
                walk(n.get("children") or [], here)

        walk(tree, [])

        total = content_markers + cell_markers
        lines.insert(
            1,
            f"\nSUMMARY content_markers={content_markers} cell_markers={cell_markers} "
            f"total={total} inline_table_tokens={rc1_inline} structural={len(structural)} "
            f"empty_lists={len(empty_lists)} no_data_tokens={len(no_data_tokens)} "
            f"title_tokens={len(title_tokens)} nodes_with_issues={nodes_with_issues}",
        )

        # --- readiness (what the export warning counts)
        try:
            from app.services.operational_plan.plan_readiness import plan_readiness

            rep = plan_readiness(db, calc_id, plan)
            lines.append(
                f"\nREADINESS total={rep['total']} resolved={rep['resolved']} "
                f"missing={len(rep['missing'])} unmet_maps={len(rep['unmet_maps'])} "
                f"unverified={rep.get('unverified', 0)} ready={rep['ready']}"
            )
            for m in rep["missing"]:
                lines.append(
                    f"  missing key={m['key']} known={m['known']} "
                    f"label_ne={m['label_ne']!r}"
                )
            for m in rep["unmet_maps"]:
                lines.append(
                    f"  unmet map={m['token']} status={m['status']} "
                    f"reason_ne={m['reason_ne']!r}"
                )
            for tok in rep.get("unverified_tokens") or []:
                lines.append(f"  unverified token={tok}")
        except Exception:
            import traceback

            lines.append("\nREADINESS FAILED:\n" + traceback.format_exc())

        out = out_path or str(Path(__file__).with_name("op_nodata_report.txt"))
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(
            f"plan markers: content={content_markers} cells={cell_markers} "
            f"total={total} inline_table_tokens={rc1_inline} empty_lists={len(empty_lists)} "
            f"no_data_tokens={len(no_data_tokens)} -> {out}"
        )
        if max_nodata is not None and total > max_nodata:
            print(f"GATE FAIL: total {total} > max {max_nodata}")
            return 1
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)

    pd = sub.add_parser("docx", help="count markers in an exported docx")
    pd.add_argument("path", help="docx path or glob")
    pd.add_argument("--max", type=int, dest="max_nodata", default=None)
    pd.add_argument("out", nargs="?", default=None)

    pp = sub.add_parser("plan", help="resolve a plan and report nodata buckets")
    pp.add_argument("ref", help="plan id or forest name")
    pp.add_argument("--max", type=int, dest="max_nodata", default=None)
    pp.add_argument("out", nargs="?", default=None)

    args = p.parse_args(argv)
    if args.mode == "docx":
        return cmd_docx(args.path, args.out, args.max_nodata)
    return cmd_plan(args.ref, args.out, args.max_nodata)


if __name__ == "__main__":
    raise SystemExit(main())
