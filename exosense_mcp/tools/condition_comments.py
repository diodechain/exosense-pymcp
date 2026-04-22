"""Get condition comments"""

from typing import Optional, Dict, Any
from pydantic import Field, ValidationError
from ..graphql.condition_policies import get_condition_comments
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class ConditionCommentsParams(McpToolParams):
    """Parameters for condition comments tool"""

    condition_id: str = Field(..., description="The ID of the condition to get comments for")
    limit: Optional[int] = Field(None, ge=1, description="Maximum number of comments to return")
    offset: Optional[int] = Field(None, ge=0, description="Number of comments to skip for pagination")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get condition comments"""
    try:
        # Validate arguments with Pydantic
        try:
            args = ConditionCommentsParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        pagination = Pagination(limit=args.limit, offset=args.offset) if args.limit or args.offset else None
        query = get_condition_comments(condition_id=args.condition_id, pagination=pagination)
        context.log.debug("Executing query to get condition comments")
        result = await client.query(query)

        comments = result.get("conditionComments", [])
        return format_success_response(
            comments, f"Successfully retrieved {len(comments)} condition comments"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(ConditionCommentsParams)
TOOL_METADATA = {
    "name": "exosense-get-condition-comments",
    "description": "Get condition comments",
    "inputSchema": schema
}
