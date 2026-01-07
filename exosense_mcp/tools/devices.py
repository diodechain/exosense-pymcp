"""Get devices from ExoSense with optional filtering"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.devices_products import get_devices
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class DevicesParams(BaseModel):
    """Parameters for devices tool"""

    product: str = Field(..., description="Product ID (pid) to filter devices by")
    text: Optional[str] = Field(None, description="Text search filter for device names or identities")
    status: Optional[str] = Field(None, description="Filter by device provision status")
    health_status: Optional[str] = Field(None, description="Filter by device health status")
    group_id: Optional[str] = Field(None, description="Filter devices by group ID")
    sort: Optional[str] = Field(None, description="Sort order for results")
    single: Optional[bool] = Field(None, description="Return only a single device")
    only_unused: Optional[bool] = Field(None, description="Filter to only unused devices")
    device_identities: Optional[List[str]] = Field(None, description="Optional list of specific device IDs to fetch")
    # Booleans with defaults: allow None and fall back to defaults
    include_tags: Optional[bool] = Field(False, description="Include device tags in the response")
    include_resources: Optional[bool] = Field(False, description="Include device resources in the response")
    include_state: Optional[bool] = Field(False, description="Include the state of the resources in the response")
    limit: int = Field(25, ge=1, le=100, description="Maximum number of devices to return (1-100, default 25)")
    offset: int = Field(0, ge=0, description="Number of devices to skip for pagination (default 0)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get devices from ExoSense with optional filtering and include options"""
    try:
        # Validate arguments with Pydantic
        try:
            args = DevicesParams(**arguments)
            # Ensure boolean include flags fall back to defaults when None is passed
            if args.include_tags is None:
                args.include_tags = False
            if args.include_resources is None:
                args.include_resources = False
            if args.include_state is None:
                args.include_state = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Build filters object from parameters
        filters: dict = {}
        if args.text:
            filters["text"] = args.text
        if args.status:
            filters["status"] = args.status
        if args.health_status:
            filters["health_status"] = args.health_status
        if args.group_id:
            filters["group_id"] = args.group_id
        if args.sort:
            filters["sort"] = args.sort
        if args.single is not None:
            filters["single"] = args.single
        if args.only_unused is not None:
            filters["only_unused"] = args.only_unused

        # Build include options
        options: dict = {
            "includeTags": args.include_tags,
            "includeRes": args.include_resources,
            "includeState": args.include_state,
        }
        if args.device_identities:
            options["ids"] = args.device_identities

        # Build pagination
        pagination = Pagination(limit=args.limit, offset=args.offset)

        query = get_devices(args.product, filters, options, pagination)
        context.log.debug("Executing query to get devices", {"filters": filters, "options": options, "pagination": pagination.model_dump()})
        result = await client.query(query)

        devices = result.get("devices", [])
        return format_success_response(
            {
                "count": len(devices),
                "devices": devices,
                "filters": filters,
                "options": options,
                "pagination": {
                    "limit": args.limit,
                    "offset": args.offset,
                    "hasMore": len(devices) == args.limit,
                },
            }
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(DevicesParams)
TOOL_METADATA = {
    "name": "exosense-get-devices",
    "description": "Get devices from ExoSense with optional filtering and include options. Supports pagination for large device datasets. Requires a product ID to filter devices by IoT Connector/Product.",
    "inputSchema": schema
}
