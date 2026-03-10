"""Get group hierarchy (tree). Use for structure, tree, or 'groups and their children'."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
import re
from ..graphql.groups import get_groups_tree
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

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

    return format_success_response(
        {"count": len(groups), "groups": groups, "has_more": len(groups) == args.limit},
        f"Group tree: {len(groups)} group(s).",
    )


schema = pydantic_to_json_schema(GroupTreeParams)
TOOL_METADATA = {
    "name": "exosense-get-group-tree",
    "description": "Use for: 'Group structure', 'Hierarchy', 'Tree', 'Groups and their children'. Returns id, name, parent_id, and one level of children. For a flat list use exosense-list-groups; for one group's assets/users/devices use exosense-get-group.",
    "inputSchema": schema,
}
