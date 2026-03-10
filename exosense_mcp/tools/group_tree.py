"""Get group hierarchy (tree). Use for structure, tree, or 'groups and their children'."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
import re
from ..graphql.groups import get_groups_tree
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response, group_to_structured, group_children_to_structured, path_from_root_for_group

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class GroupTreeParams(BaseModel):
    group_id: Optional[str] = Field(None, description="Root of tree (UUID). Omit for full tree from root.")
    limit: int = Field(100, ge=1, le=200, description="Max groups to return (default 100)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    args_in = dict(arguments)
    if args_in.get("limit") is None:
        args_in["limit"] = 100
    else:
        try:
            args_in["limit"] = int(args_in["limit"])
        except (TypeError, ValueError):
            args_in["limit"] = 100
    try:
        args = GroupTreeParams(**args_in)
        if args.group_id is not None and not UUID_REGEX.match(args.group_id):
            return format_error_response(Exception("group_id must be a valid UUID"))
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    filters: dict = {}
    if args.group_id:
        filters["group_id"] = args.group_id
    pagination = Pagination(limit=args.limit, offset=0)
    query = get_groups_tree(filters, pagination)
    result = await client.query(query)
    groups = result.get("groups", [])
    id_to_name = {g.get("id"): g.get("name") or "" for g in groups if g.get("id")}
    id_to_info = {g.get("id"): {"name": g.get("name"), "parent_id": g.get("parent_id")} for g in groups if g.get("id")}
    for g in groups:
        for c in g.get("children") or []:
            if c.get("id"):
                id_to_name[c["id"]] = c.get("name") or ""
                id_to_info[c["id"]] = {"name": c.get("name"), "parent_id": g.get("id")}
    structured = []
    for g in groups:
        node = group_to_structured(g, id_to_name=id_to_name)
        gid = g.get("id")
        if gid:
            node["path_from_root"] = path_from_root_for_group(gid, id_to_info)
        children = g.get("children") or []
        node["children"] = group_children_to_structured(
            children,
            parent_id=g.get("id"),
            parent_name=g.get("name") or "",
        )
        for ch in node["children"]:
            cid = ch.get("group_id")
            if cid:
                ch["path_from_root"] = path_from_root_for_group(cid, id_to_info)
        structured.append(node)

    return format_success_response(
        {"count": len(structured), "groups": structured, "has_more": len(groups) == args.limit},
        f"Group tree: {len(groups)} group(s).",
    )


schema = pydantic_to_json_schema(GroupTreeParams)
TOOL_METADATA = {
    "name": "exosense-get-group-tree",
    "description": "Use for: 'Group structure', 'Hierarchy', 'Tree', 'Groups and their children'. Returns group_id, group_name, parent_group (group_id, group_name), path_from_root (list of {group_id, group_name} from root to this group; first element = top-level/customer), and children. For 'who is the top level?' or 'who owns this group?' use path_from_root[0] or exosense-get-group-path. For a flat list use exosense-list-groups; for one group's details use exosense-get-group.",
    "inputSchema": schema,
}
