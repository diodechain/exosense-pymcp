"""List groups (minimal: id, name, parent_id). Use for count, list, or search by name."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.groups import get_groups_list
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class ListGroupsParams(BaseModel):
    limit: int = Field(25, ge=1, le=100, description="Max groups to return (default 25)")
    offset: int = Field(0, ge=0, description="Skip N groups for pagination")
    text: Optional[str] = Field(None, description="Search by group name or description (omit for no search)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    # Tolerate omitted, null, or string limit/offset (LLM often sends only text or wrong types)
    args_in = dict(arguments)
    if args_in.get("limit") is None:
        args_in["limit"] = 25
    else:
        try:
            args_in["limit"] = int(args_in["limit"])
        except (TypeError, ValueError):
            args_in["limit"] = 25
    if args_in.get("offset") is None:
        args_in["offset"] = 0
    else:
        try:
            args_in["offset"] = int(args_in["offset"])
        except (TypeError, ValueError):
            args_in["offset"] = 0
    try:
        args = ListGroupsParams(**args_in)
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    filters: dict = {}
    if args.text:
        filters["text"] = args.text.strip()
    pagination = Pagination(limit=args.limit, offset=args.offset)
    query = get_groups_list(filters, pagination)
    result = await client.query(query)
    groups = result.get("groups", [])

    return format_success_response(
        {
            "count": len(groups),
            "groups": [{"id": g.get("id"), "name": g.get("name"), "parent_id": g.get("parent_id")} for g in groups],
            "has_more": len(groups) == args.limit,
        },
        f"Found {len(groups)} group(s).",
    )


schema = pydantic_to_json_schema(ListGroupsParams)
TOOL_METADATA = {
    "name": "exosense-list-groups",
    "description": "Use for: 'How many groups?', 'List groups', 'What groups exist?', 'Search groups by name'. Returns a light list (id, name, parent_id) only. For hierarchy use exosense-get-group-tree; for one group's details use exosense-get-group.",
    "inputSchema": schema,
}
