"""Get status information for specific assets"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from ..graphql.assets import get_asset_statuses
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class AssetStatusesParams(BaseModel):
    """Parameters for asset statuses tool"""

    asset_ids: List[str] = Field(..., description="List of asset IDs to get statuses for")
    extra_status_data: Optional[bool] = Field(False, description="Get additional status data (up to 5 entries instead of 1)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get status information for specific assets"""
    try:
        # Validate arguments with Pydantic
        try:
            args = AssetStatusesParams(**arguments)
            # Ensure extra_status_data has a value (use default if None)
            if args.extra_status_data is None:
                args.extra_status_data = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        options: dict = {"extraStatusData": args.extra_status_data}
        query = get_asset_statuses(args.asset_ids, options)
        context.log.debug("Executing query to get asset statuses")
        result = await client.query(query)

        # Format the response to be more useful
        asset_statuses = result.get("assetStatuses", [])
        formatted_statuses = []
        
        for status in asset_statuses:
            formatted_status = {
                "asset_id": status.get("id"),
                "last_heard": status.get("lastHeard"),
                "has_status_data": len(status.get("categories", [])) > 0,
                "category_count": len(status.get("categories", [])),
            }
            
            # Include category summaries if available
            categories = status.get("categories", [])
            if categories:
                formatted_status["categories"] = [
                    {
                        "category": cat.get("category"),
                        "value_count": len(cat.get("values", [])),
                        "latest_value": cat.get("values", [{}])[0] if cat.get("values") else None,
                    }
                    for cat in categories
                ]
            else:
                formatted_status["message"] = "No status categories available for this asset"
            
            formatted_statuses.append(formatted_status)
        
        return format_success_response(
            {
                "count": len(formatted_statuses),
                "statuses": formatted_statuses,
            },
            f"Retrieved status information for {len(formatted_statuses)} asset(s)"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(AssetStatusesParams)
TOOL_METADATA = {
    "name": "exosense-get-asset-statuses",
    "description": "Get status information for specific assets",
    "inputSchema": schema
}
