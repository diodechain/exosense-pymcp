"""Get groups from ExoSense with optional filtering"""

import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ValidationError
from ..graphql.groups import get_all_groups
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

# UUID validation regex
UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class GroupsParams(BaseModel):
    """Parameters for groups tool"""

    group_type_id: Optional[str] = Field(None, description="Filter by group type ID")
    group_id: Optional[str] = Field(None, description="Filter by specific group ID")
    recurse: Optional[bool] = Field(None, description="Whether to recurse through child groups")
    text: Optional[str] = Field(None, description="Text search filter for group names or descriptions")
    # Booleans with defaults: allow None and fall back to defaults
    include_children: Optional[bool] = Field(False, description="Include child groups in the response")
    include_assets: Optional[bool] = Field(False, description="Include assets in the response")
    include_devices: Optional[bool] = Field(False, description="Include devices in the response")
    include_users: Optional[bool] = Field(False, description="Include users in the response")
    include_roles: Optional[bool] = Field(False, description="Include roles in the response")
    limit: int = Field(25, ge=1, le=100, description="Maximum number of groups to return (1-100, default 25)")
    offset: int = Field(0, ge=0, description="Number of groups to skip for pagination (default 0)")

    @field_validator("group_id")
    @classmethod
    def validate_group_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not UUID_REGEX.match(v):
            raise ValueError("Must be a valid UUID")
        return v


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get groups from ExoSense with optional filtering and include options"""
    try:
        # Validate arguments with Pydantic
        try:
            args = GroupsParams(**arguments)
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

        return format_success_response(
            {
                "count": len(result.get("groups", [])),
                "groups": result.get("groups", []),
                "filters": filters,
                "options": options,
                "pagination": {
                    "limit": args.limit,
                    "offset": args.offset,
                    "hasMore": len(result.get("groups", [])) == args.limit,
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
    "description": "Get groups from ExoSense with optional filtering and include options. Includes pagination support for large datasets.",
    "inputSchema": schema
}
