"""Get work instructions"""

from typing import Optional, Dict, Any
from pydantic import Field, ValidationError
from ..graphql.work_instructions import get_work_instructions
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class WorkInstructionsParams(McpToolParams):
    """Parameters for work instructions tool"""

    filters: Optional[Dict] = Field(None, description="Filters to apply to the query")
    limit: Optional[int] = Field(None, ge=1, description="Maximum number of work instructions to return")
    offset: Optional[int] = Field(None, ge=0, description="Number of work instructions to skip for pagination")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get work instructions"""
    try:
        # Validate arguments with Pydantic
        try:
            args = WorkInstructionsParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        pagination = Pagination(limit=args.limit, offset=args.offset) if args.limit or args.offset else None
        query = get_work_instructions(filters=args.filters, pagination=pagination)
        context.log.debug("Executing query to get work instructions")
        result = await client.query(query)

        instructions = result.get("workInstructions", [])
        return format_success_response(
            instructions, f"Successfully retrieved {len(instructions)} work instructions"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(WorkInstructionsParams)
TOOL_METADATA = {
    "name": "exosense-get-work-instructions",
    "description": "Get work instructions",
    "inputSchema": schema
}
