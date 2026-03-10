"""Asset count for one group by name or ID. One call for 'how many assets does [group] have?'."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
import re
from ..graphql.groups import get_groups_list, get_group_totals_recursive
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class GroupAssetCountParams(BaseModel):
    group_name: Optional[str] = Field(None, description="Group name to search (e.g. 'Mahr Brothers'). Use for 'how many assets does X have?'.")
    group_id: Optional[str] = Field(None, description="Group UUID if already known. Omit if using group_name.")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    args_in = dict(arguments)
    if args_in.get("group_name") == "":
        args_in["group_name"] = None
    if args_in.get("group_id") == "":
        args_in["group_id"] = None
    try:
        args = GroupAssetCountParams(**args_in)
        if not args.group_name and not args.group_id:
            return format_error_response(Exception("Provide group_name or group_id"))
        if args.group_id and not UUID_REGEX.match(args.group_id):
            return format_error_response(Exception("group_id must be a valid UUID"))
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    group_id = args.group_id
    group_name = args.group_name or ""

    if not group_id and args.group_name:
        query = get_groups_list({"text": args.group_name.strip()}, Pagination(limit=1, offset=0))
        result = await client.query(query)
        groups = result.get("groups", [])
        if not groups:
            return format_success_response(
                {"group_name": args.group_name, "asset_count": 0, "message": "Group not found."},
                f"No group found matching '{args.group_name}'.",
            )
        group_id = groups[0].get("id")
        group_name = groups[0].get("name") or args.group_name

    # Use recursive totals so count includes assets in this group and all sub-groups
    query = get_group_totals_recursive(group_id)
    result = await client.query(query)
    groups = result.get("groups", [])
    if not groups:
        return format_success_response(
            {"group_id": group_id, "group_name": group_name, "asset_count": 0},
            "Group has 0 assets.",
        )
    group = groups[0]
    totals = group.get("totals") or {}
    count = totals.get("assets")
    if count is None:
        count = 0
    group_name = group_name or group.get("name") or group_id

    return format_success_response(
        {"group_id": group_id, "group_name": group_name, "asset_count": count},
        f"{group_name}: {count} asset(s).",
    )


schema = pydantic_to_json_schema(GroupAssetCountParams)
TOOL_METADATA = {
    "name": "exosense-group-asset-count",
    "description": "Use for: 'How many assets does [group/customer] have?', 'How many assets does Mahr Brothers have deployed?', 'Asset count for group X'. Single call: pass group_name or group_id. Returns group_id, group_name, asset_count. Count includes the group and all sub-groups (recursive). Do not use get-asset-details or list-groups + get-group for this.",
    "inputSchema": schema,
}
