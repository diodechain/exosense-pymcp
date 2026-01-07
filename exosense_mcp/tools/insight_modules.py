"""Get all available internal insight modules"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from ..graphql.insight_modules import get_internal_insight_modules
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class InsightModulesParams(BaseModel):
    """Parameters for insight modules tool"""

    limit: Optional[int] = Field(None, ge=1, description="Maximum number of modules to return")
    offset: Optional[int] = Field(None, ge=0, description="Number of modules to skip for pagination")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get all available internal insight modules"""
    try:
        # Validate arguments with Pydantic
        try:
            args = InsightModulesParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        pagination = Pagination(limit=args.limit, offset=args.offset) if args.limit or args.offset else None
        query = get_internal_insight_modules(pagination)
        context.log.debug("Executing query to get insight modules")
        result = await client.query(query)

        modules = result.get("internalInsightModules", [])
        return format_success_response(
            modules, f"Successfully retrieved {len(modules)} insight modules"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(InsightModulesParams)
TOOL_METADATA = {
    "name": "exosense-get-insight-modules",
    "description": "Get all available internal insight modules",
    "inputSchema": schema
}
