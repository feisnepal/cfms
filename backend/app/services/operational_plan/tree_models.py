"""Pydantic models for the OP document tree.

Defines the document tree structure used to represent an Operational Plan
as a hierarchical list of sections, subsections, and appendixes. The
TreeNode model supports rich text, charts, tables, maps, and static table
content types.

See also:
    .seed_data.get_default_seed_tree — creates the initial tree
    .op_docx_builder.walk_tree — renders the tree to DOCX
"""

from __future__ import annotations
from typing import Optional, List, Literal, Any
from uuid import uuid4
from pydantic import BaseModel, Field
from datetime import datetime, timezone


NodeType = Literal["preamble", "toc", "section", "subsection", "appendix"]


class TreeNode(BaseModel):
    """Node in the operational plan document tree hierarchy."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: NodeType = "section"
    title_ne: str = ""
    title_en: str = ""
    number: Optional[str] = None
    level: int = 0
    content_type: Literal["richtext", "chart", "table", "map", "static_table"] = "richtext"
    content: str = ""
    chart_type: Optional[str] = None
    table_id: Optional[str] = None
    map_type: Optional[str] = None
    static_table: Optional[dict] = None
    inline_tables: Optional[list] = None
    children: List[TreeNode] = []
    is_locked: bool = False
    hidden_in_export: bool = False
    deleted: bool = False
    page_break_before: bool = False
    # Page layout (Rambhadevi-style plans): a node with page_format starts a NEW section whose page numbers use
    # that format (restart_pages: from 1 again) - e.g. upperRoman for the front matter, decimal for the chapters.
    # landscape: the node (and its children) is rendered on landscape pages, then portrait resumes.
    page_format: Optional[Literal["decimal", "upperRoman", "lowerRoman", "upperLetter", "lowerLetter"]] = None
    restart_pages: bool = False
    landscape: bool = False
    # heading text = number_prefix + number + number_sep + title (default: no prefix, '. '); e.g. 'परिच्छेद ' + '१' + ' ' + title
    number_prefix: Optional[str] = None
    number_sep: Optional[str] = None
    last_modified: Optional[str] = None
    # OP multi-template §3.9 — the template's own cover page. Exactly one node
    # per tree may set is_cover=True. Phase 0 only introduces the fields; cover
    # rendering + the one-time backfill land in Phase 3.
    is_cover: bool = False
    cover_meta: Optional[dict] = None
    # OP multi-template §3.4 — stable key matched by a plan-kind's
    # required_section_keys (title match is the fallback).
    section_key: Optional[str] = None
    # THEMATIC_MAP_VARIABLES_PLAN P6 — per-node map tuning for a content_type
    # == "map" node. `thememap_spec` is a partial override dict (only
    # OVERRIDABLE_FIELDS honoured); `opsmap_key` / `year` let a node pin an
    # opsmap variable + its plan year without editing `map_type`.
    thememap_spec: Optional[dict] = None
    opsmap_key: Optional[str] = None
    year: Optional[int] = None
    # plan_live.py: the template's own text (variables unresolved) this section was filled from, and a fingerprint of what it
    # printed. While the fingerprint still matches the text, the section follows the forest's data; once the user edits it, it is theirs.
    source_content: Optional[str] = None
    populated_hash: Optional[str] = None

    def touch(self):
        self.last_modified = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> TreeNode:
        if "children" in data:
            data["children"] = [cls.from_dict(c) if isinstance(c, dict) else c for c in data["children"]]
        return cls(**data)


class DocumentTree(BaseModel):
    """Complete document tree with metadata for an operational plan."""
    tree: List[TreeNode] = []
    metadata: dict = Field(default_factory=lambda: {
        "auto_numbering": True,
        "language": "NP",
        "version": "2.0"
    })


class TreeOperations:
    """Static utility methods for manipulating the document tree."""

    @staticmethod
    def find_node(tree: List[TreeNode], node_id: str) -> Optional[TreeNode]:
        for node in tree:
            if node.id == node_id:
                return node
            found = TreeOperations.find_node(node.children, node_id)
            if found:
                return found
        return None

    @staticmethod
    def find_parent(tree: List[TreeNode], node_id: str) -> Optional[TreeNode]:
        for node in tree:
            if any(c.id == node_id for c in node.children):
                return node
            found = TreeOperations.find_parent(node.children, node_id)
            if found:
                return found
        return None

    @staticmethod
    def add_node(tree: List[TreeNode], parent_id: Optional[str], new_node: TreeNode, position: int = -1) -> List[TreeNode]:
        if parent_id is None:
            if position < 0 or position >= len(tree):
                tree.append(new_node)
            else:
                tree.insert(position, new_node)
            return tree
        parent = TreeOperations.find_node(tree, parent_id)
        if parent is None:
            raise ValueError(f"Parent node {parent_id} not found")
        if position < 0 or position >= len(parent.children):
            parent.children.append(new_node)
        else:
            parent.children.insert(position, new_node)
        return tree

    @staticmethod
    def update_node(tree: List[TreeNode], node_id: str, updates: dict) -> List[TreeNode]:
        node = TreeOperations.find_node(tree, node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found")
        for key, value in updates.items():
            if key in ("id", "children"):
                continue
            setattr(node, key, value)
        node.touch()
        return tree

    @staticmethod
    def delete_node(tree: List[TreeNode], node_id: str) -> List[TreeNode]:
        for i, node in enumerate(tree):
            if node.id == node_id:
                if node.is_locked:
                    raise ValueError(f"Cannot delete locked node {node_id}")
                tree.pop(i)
                return tree
            try:
                TreeOperations.delete_node(node.children, node_id)
                return tree
            except ValueError:
                continue
        raise ValueError(f"Node {node_id} not found")

    @staticmethod
    def move_node(tree: List[TreeNode], node_id: str, new_parent_id: Optional[str], new_position: int = -1) -> List[TreeNode]:
        node_data = TreeOperations.find_node(tree, node_id)
        if node_data is None:
            raise ValueError(f"Node {node_id} not found")
        if node_data.is_locked:
            raise ValueError(f"Cannot move locked node {node_id}")

        tree = TreeOperations.delete_node(tree, node_id)
        tree = TreeOperations.add_node(tree, new_parent_id, node_data, new_position)
        return tree

    @staticmethod
    def flatten(tree: List[TreeNode]) -> List[TreeNode]:
        result = []
        for node in tree:
            result.append(node)
            result.extend(TreeOperations.flatten(node.children))
        return result
