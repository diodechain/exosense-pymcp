"""Get event logs"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.logs import get_event_logs
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class EventLogsParams(BaseModel):
    """Parameters for event logs tool"""

    filters: Optional[Dict] = Field(None, description="Filters to apply to the query")
    limit: Optional[int] = Field(None, ge=1, description="Maximum number of logs to return")
    offset: Optional[int] = Field(None, ge=0, description="Number of logs to skip for pagination")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get event logs"""
    try:
        # Validate arguments with Pydantic
        try:
            args = EventLogsParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        pagination = Pagination(limit=args.limit, offset=args.offset) if args.limit or args.offset else None
        query = get_event_logs(filters=args.filters, pagination=pagination)
        context.log.debug("Executing query to get event logs")
        result = await client.query(query)

        logs = result.get("logs", [])
        return format_success_response(
            logs, f"Successfully retrieved {len(logs)} event logs"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(EventLogsParams)
TOOL_METADATA = {
    "name": "exosense-get-event-logs",
    "description": "Get event logs",
    "inputSchema": schema
}
