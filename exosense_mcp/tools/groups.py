"""Get groups from ExoSense with optional filtering"""

import re
from typing import Optional, Dict, Any
from pydantic import Field, field_validator, ValidationError
from ..graphql.groups import get_all_groups
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response, group_to_structured, group_children_to_structured, asset_to_structured

# UUID validation regex
UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class GroupsParams(McpToolParams):
    """Parameters for groups tool"""

    group_type_id: Optional[str] = Field(None, description="Filter by group type ID (UUID). Omit to get all group types.")
    group_id: Optional[str] = Field(None, description="Filter by a specific group ID (UUID). Use when the user asks about one group or 'groups under X'. Omit to list from root.")
    recurse: Optional[bool] = Field(None, description="When true, include child groups in the hierarchy. Use when the user asks for 'all groups', 'group tree', 'subgroups', or 'children'.")
    text: Optional[str] = Field(None, description="Search group names or descriptions by text. Use when the user searches by name (e.g. 'groups named West', 'find group containing Building').")
    include_children: Optional[bool] = Field(False, description="Include child groups in each group in the response. Set true when user asks for 'groups and their children', 'group structure', or 'hierarchy'.")
    include_assets: Optional[bool] = Field(False, description="Include assets belonging to each group. Set true when user asks for 'groups with their assets', 'what assets are in each group', or 'assets per group'.")
    include_devices: Optional[bool] = Field(False, description="Include IoT devices owned by each group. Set true when user asks for 'groups with devices', 'devices per group', or 'device ownership'.")
    include_users: Optional[bool] = Field(False, description="Include users assigned to each group. Set true when user asks for 'who has access', 'users in a group', or 'group membership'.")
    include_roles: Optional[bool] = Field(False, description="Include roles defined at each group. Set true when user asks for 'roles per group' or 'permissions by group'.")
    limit: int = Field(25, ge=1, le=100, description="Maximum number of groups to return (1-100, default 25). Increase for 'list all groups' or large orgs.")
    offset: int = Field(0, ge=0, description="Number of groups to skip for pagination (default 0). Use with limit for paging.")

    @field_validator("group_id")
    @classmethod
    def validate_group_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not UUID_REGEX.match(v):
            raise ValueError("Must be a valid UUID")
        return v


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get groups from ExoSense with optional filtering and include options"""
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
        # Validate arguments with Pydantic
        try:
            args = GroupsParams(**args_in)
            # Ensure boolean include flags fall back to defaults when None is passed
            if args.include_children is None:
                args.include_children = False
            if args.include_assets is None:
                args.include_assets = False
            if args.include_devices is None:
                args.include_devices = False
            if args.include_users is None:
                args.include_users = False
            if args.include_roles is None:
                args.include_roles = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Build filters object from parameters
        filters: dict = {}
        if args.group_type_id:
            filters["group_type_id"] = args.group_type_id
        if args.group_id:
            filters["group_id"] = args.group_id
        if args.recurse is not None:
            filters["recurse"] = args.recurse
        if args.text:
            filters["text"] = args.text

        # Build include options
        options: dict = {
            "includeChildren": args.include_children,
            "includeAssets": args.include_assets,
            "includeDevices": args.include_devices,
            "includeUsers": args.include_users,
            "includeRoles": args.include_roles,
        }

        # Build pagination
        pagination = Pagination(limit=args.limit, offset=args.offset)

        # Use the pre-built GraphQL query
        query = get_all_groups(filters, options, pagination)
        context.log.debug("Executing query to get groups", {"filters": filters, "options": options, "pagination": pagination.model_dump()})
        result = await client.query(query)
        raw_groups = result.get("groups", [])
        id_to_name = {g.get("id"): g.get("name") or "" for g in raw_groups if g.get("id")}
        for g in raw_groups:
            for c in (g.get("children") or []):
                if c.get("id"):
                    id_to_name[c["id"]] = c.get("name") or ""
        structured_groups = []
        for g in raw_groups:
            node = group_to_structured(g, id_to_name=id_to_name)
            if args.include_children and g.get("children"):
                node["children"] = group_children_to_structured(
                    g["children"],
                    parent_id=g.get("id"),
                    parent_name=g.get("name") or "",
                )
            if args.include_assets and g.get("assets"):
                node["assets"] = [
                    asset_to_structured(a, group_id=g.get("id"), group_name=g.get("name") or "")
                    for a in g["assets"]
                ]
            if args.include_devices and g.get("devices"):
                node["devices"] = g.get("devices", [])
            if args.include_users and g.get("users"):
                node["users"] = g.get("users", [])
            if args.include_roles and g.get("roles"):
                node["roles"] = g.get("roles", [])
            structured_groups.append(node)

        return format_success_response(
            {
                "count": len(structured_groups),
                "groups": structured_groups,
                "filters": filters,
                "options": options,
                "pagination": {
                    "limit": args.limit,
                    "offset": args.offset,
                    "hasMore": len(raw_groups) == args.limit,
                },
            }
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(GroupsParams)
TOOL_METADATA = {
    "name": "exosense-get-groups",
    "description": "Full groups query with all filter and include options. Prefer exosense-list-groups, exosense-get-group-tree (includes path_from_root), or exosense-get-group for common questions. For 'who is the top level?' or 'who owns this group?' use exosense-get-group-path with group_id.",
    "inputSchema": schema
}
