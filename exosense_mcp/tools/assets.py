"""Get assets from ExoSense with optional filtering"""

import re
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator, ValidationError
from ..graphql.assets import get_assets
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

# UUID validation regex
UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class AssetsParams(McpToolParams):
    """Parameters for assets tool"""

    group_id: Optional[str] = Field(None, description="Find assets belonging to a specific group")
    text: Optional[str] = Field(None, description="Text search filter for asset names")
    level: Optional[List[str]] = Field(None, description="Filter assets by alarm level status")
    created_from: Optional[str] = Field(None, description="Find assets created from this date (ISO string)")
    created_to: Optional[str] = Field(None, description="Find assets created up to this date (ISO string)")
    order_by: Optional[str] = Field(None, description="Order results by field")
    sort: Optional[str] = Field(None, description="Sort order for results")
    signal_ids: Optional[List[str]] = Field(None, description="Filter by signal IDs")
    location: Optional[bool] = Field(None, description="Only return assets with location set")
    asset_ids: Optional[List[str]] = Field(None, description="Optional list of specific asset IDs to fetch")
    # Booleans with defaults: allow None from client and fall back to defaults
    include_templates: Optional[bool] = Field(False, description="Include asset templates in the response")
    include_parent: Optional[bool] = Field(False, description="Include parent group information in the response")
    include_meta: Optional[bool] = Field(False, description="Include asset metadata in the response")
    include_location: Optional[bool] = Field(False, description="Include asset location information in the response")
    include_data: Optional[bool] = Field(False, description="Include latest signal data in the response")
    extra_rule_data: Optional[bool] = Field(False, description="Get additional rule data (up to 5 rule entries instead of 1 per rule)")
    limit: int = Field(..., ge=1, le=100, description="Maximum number of assets to return (1-100, required)")
    offset: int = Field(..., ge=0, description="Number of assets to skip for pagination (required)")

    @field_validator("group_id", "signal_ids", "asset_ids", mode="before")
    @classmethod
    def validate_uuids(cls, v):
        if v is None:
            return v
        if isinstance(v, list):
            for item in v:
                if not UUID_REGEX.match(str(item)):
                    raise ValueError(f"Must be a valid UUID: {item}")
        elif isinstance(v, str):
            if not UUID_REGEX.match(v):
                raise ValueError(f"Must be a valid UUID: {v}")
        return v


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get assets from ExoSense with optional filtering and include options"""
    try:
        # Validate arguments with Pydantic
        try:
            args = AssetsParams(**arguments)
            # Ensure boolean include flags fall back to defaults when None is passed
            if args.include_templates is None:
                args.include_templates = False
            if args.include_parent is None:
                args.include_parent = False
            if args.include_meta is None:
                args.include_meta = False
            if args.include_location is None:
                args.include_location = False
            if args.include_data is None:
                args.include_data = False
            if args.extra_rule_data is None:
                args.extra_rule_data = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Build filters object from parameters
        filters: dict = {}
        if args.group_id:
            filters["group_id"] = args.group_id
        if args.text:
            filters["text"] = args.text
        if args.level:
            filters["level"] = args.level
        if args.created_from:
            filters["created_from"] = args.created_from
        if args.created_to:
            filters["created_to"] = args.created_to
        if args.order_by:
            filters["orderBy"] = args.order_by
        if args.sort:
            filters["sort"] = args.sort
        if args.signal_ids:
            filters["signalIds"] = args.signal_ids
        if args.location is not None:
            filters["location"] = args.location

        # Build include options
        options: dict = {
            "includeTemplates": args.include_templates,
            "includeParent": args.include_parent,
            "includeMeta": args.include_meta,
            "includeLocation": args.include_location,
            "includeData": args.include_data,
            "extraRuleData": args.extra_rule_data,
        }
        if args.asset_ids:
            options["ids"] = args.asset_ids

        # Build pagination
        pagination = Pagination(limit=args.limit, offset=args.offset)

        query = get_assets(filters, options, pagination)
        context.log.debug("Executing query to get assets", {"filters": filters, "options": options, "pagination": pagination.model_dump()})
        result = await client.query(query)

        assets = result.get("assets", [])
        # Return only a summary of asset names instead of full configuration
        asset_summary = [
            {
                "id": asset.get("id"),
                "name": asset.get("name") or "Unnamed Asset",
                "description": asset.get("description"),
                "locked": asset.get("locked"),
            }
            for asset in assets
        ]

        return format_success_response(
            {
                "count": len(assets),
                "assets": asset_summary,
                "pagination": {
                    "limit": args.limit,
                    "offset": args.offset,
                    "hasMore": len(assets) == args.limit,
                },
            }
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(AssetsParams)
TOOL_METADATA = {
    "name": "exosense-get-assets",
    "description": "Get a summary of assets from ExoSense (names and IDs only) with optional filtering. Returns only asset names, IDs, descriptions, and locked status - not the full configuration. Requires pagination parameters (limit and offset) for all requests. NOTE: For checking asset health, use 'exosense-get-asset-statuses' directly - it fetches assets internally and doesn't require calling this tool first.",
    "inputSchema": schema
}
