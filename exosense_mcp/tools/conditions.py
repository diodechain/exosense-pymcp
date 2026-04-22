"""Get conditions"""

from typing import Optional, List, Dict, Any
from pydantic import Field, ValidationError
from ..graphql.condition_policies import get_conditions
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class ConditionsParams(McpToolParams):
    """Parameters for conditions tool"""

    query: Optional[List[Dict]] = Field(None, description="Query filters for conditions")
    order: Optional[List[Dict]] = Field(None, description="Order by conditions")
    limit: Optional[int] = Field(None, ge=1, description="Maximum number of conditions to return")
    offset: Optional[int] = Field(None, ge=0, description="Number of conditions to skip for pagination")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get conditions"""
    try:
        # Validate arguments with Pydantic
        try:
            args = ConditionsParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        pagination = Pagination(limit=args.limit, offset=args.offset) if args.limit or args.offset else None
        query = get_conditions(query=args.query, order=args.order, pagination=pagination)
        context.log.debug("Executing query to get conditions")
        result = await client.query(query)

        return format_success_response(result, "Successfully retrieved conditions")
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(ConditionsParams)
TOOL_METADATA = {
    "name": "exosense-get-conditions",
    "description": "Get conditions",
    "inputSchema": schema
}
