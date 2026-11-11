"""A template saved through the API must keep every field the document builder reads.

TreeNodeSchema (the request model) once lacked map_type / inline_tables / page_break_before, so editing a template in
the designer silently dropped them; the layout fields of the Rambhadevi-style plan would have gone the same way."""
from app.schemas.operational_plan import TreeNodeSchema
from app.services.operational_plan.tree_models import TreeNode


def test_every_tree_node_field_survives_the_request_schema():
    node = TreeNode(id="n1", title_ne="x", map_type="boundary", inline_tables=[{"columns": ["a"], "rows": [["1"]]}],
                    page_break_before=True, page_format="upperRoman", restart_pages=True, landscape=True,
                    number_prefix="परिच्छेद ", number_sep=" ").model_dump()
    back = TreeNodeSchema.model_validate(node).model_dump()
    lost = {k: v for k, v in node.items() if k in TreeNode.model_fields and k not in back}
    assert not lost, f"fields dropped by TreeNodeSchema: {sorted(lost)}"
    for key in ("map_type", "inline_tables", "page_break_before", "page_format", "restart_pages", "landscape",
                "number_prefix", "number_sep"):
        assert back[key] == node[key], key
