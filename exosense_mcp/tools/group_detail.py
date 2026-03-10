"""Get one group by ID with optional assets, devices, users. Use for 'what is in this group', 'who has access'."""

import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.groups import get_all_groups
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class GroupDetailParams(BaseModel):
    group_id: str = Field(..., description="Group UUID")
    include_assets: bool = Field(False, description="Include assets in this group")
    include_devices: bool = Field(False, description="Include devices in this group")
    include_users: bool = Field(False, description="Include users in this group")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    # Tolerate omitted or null booleans (LLM often sends only group_id + include_assets)
    args_in = dict(arguments)
    for key in ("include_assets", "include_devices", "include_users"):
        if args_in.get(key) is None:
            args_in[key] = False
        elif isinstance(args_in[key], str):
            args_in[key] = args_in[key].lower() in ("true", "1", "yes", "on")
    try:
        args = GroupDetailParams(**args_in)
        if not UUID_REGEX.match(args.group_id):
            return format_error_response(Exception("group_id must be a valid UUID"))
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    filters = {"group_id": args.group_id}
    options = {
        "includeChildren": False,
        "includeAssets": args.include_assets,
        "includeDevices": args.include_devices,
        "includeUsers": args.include_users,
        "includeRoles": False,
    }
    pagination = Pagination(limit=1, offset=0)
    query = get_all_groups(filters, options, pagination)
    result = await client.query(query)
    groups = result.get("groups", [])
    if not groups:
        return format_success_response({"group": None, "message": "Group not found."}, "Group not found.")
    group = groups[0]
    # Keep response small: only include requested nested data
    out = {
        "id": group.get("id"),
        "name": group.get("name"),
        "parent_id": group.get("parent_id"),
        "description": group.get("description"),
        "custom_id": group.get("custom_id"),
    }
    if args.include_assets and group.get("assets"):
        out["assets"] = [{"id": a.get("id"), "name": a.get("name")} for a in group["assets"]]
    if args.include_devices and group.get("devices"):
        out["devices"] = [{"id": d.get("id"), "identity": d.get("identity")} for d in group["devices"]]
    if args.include_users and group.get("users"):
        out["users"] = [{"id": u.get("id"), "email": u.get("email"), "name": u.get("name")} for u in group["users"]]

    return format_success_response({"group": out}, f"Group: {group.get('name', '')}.")

schema = pydantic_to_json_schema(GroupDetailParams)
TOOL_METADATA = {
    "name": "exosense-get-group",
    "description": "Use for: 'Details of group X', 'What is in this group?', 'Who has access?', 'What assets in group X?'. Pass group_id and set include_assets/include_devices/include_users when needed. For 'how many assets does [group] have?' use exosense-group-asset-count instead (one call, small response). For listing groups use exosense-list-groups.",
    "inputSchema": schema,
}
