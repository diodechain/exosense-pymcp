"""Get hierarchy path for one group (root to group). Use for 'who is the top level?', 'who owns X?', 'customer'."""

import re
from typing import Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.groups import get_groups_list
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response, path_from_root_for_group

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

MAX_GROUPS_TO_FETCH = 1000
PAGE_SIZE = 200


class GroupPathParams(BaseModel):
    group_id: str = Field(..., description="Group UUID to get hierarchy path for (e.g. from list-groups or group-tree)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    args_in = dict(arguments)
    try:
        args = GroupPathParams(**args_in)
        if not UUID_REGEX.match(args.group_id):
            return format_error_response(Exception("group_id must be a valid UUID"))
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    id_to_info: Dict[str, Dict[str, Any]] = {}
    offset = 0
    found = False
    while offset < MAX_GROUPS_TO_FETCH:
        pagination = Pagination(limit=PAGE_SIZE, offset=offset)
        query = get_groups_list({}, pagination)
        result = await client.query(query)
        groups = result.get("groups", [])
        if not groups:
            break
        for g in groups:
            gid = g.get("id")
            if gid:
                id_to_info[gid] = {"name": g.get("name"), "parent_id": g.get("parent_id")}
                if gid == args.group_id:
                    found = True
        if found or len(groups) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if args.group_id not in id_to_info:
        return format_success_response(
            {"group_id": args.group_id, "group_name": None, "parent_group": None, "path_from_root": None, "message": "Group not found in first {} groups.".format(MAX_GROUPS_TO_FETCH)},
            "Group not found.",
        )

    info = id_to_info[args.group_id]
    group_name = (info.get("name") or "").strip() or None
    parent_id = info.get("parent_id")
    parent_group = None
    if parent_id:
        parent_info = id_to_info.get(parent_id, {})
        parent_group = {"group_id": parent_id, "group_name": parent_info.get("name")}

    path_from_root = path_from_root_for_group(args.group_id, id_to_info)
    top_level = path_from_root[0] if path_from_root else None

    out = {
        "group_id": args.group_id,
        "group_name": group_name,
        "parent_group": parent_group,
        "path_from_root": path_from_root,
        "top_level_group": top_level,
    }

    return format_success_response(
        out,
        "Top-level group: {}.".format(top_level.get("group_name") if top_level else "unknown") if top_level else "Group has no path.",
    )


schema = pydantic_to_json_schema(GroupPathParams)
TOOL_METADATA = {
    "name": "exosense-get-group-path",
    "description": "Use for: 'Who is the top level group for X?', 'Who owns [group]?', 'Who is the customer?', 'What is the hierarchy above this group?'. Pass group_id (UUID). Returns path_from_root (list of {group_id, group_name} from root to this group) and top_level_group (first element = the top-level/customer). Always use this structured data to answer hierarchy questions; do not infer from group names.",
    "inputSchema": schema,
}
