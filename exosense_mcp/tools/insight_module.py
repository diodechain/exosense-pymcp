"""Get detailed information about a specific insight module"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from ..graphql.insight_modules import get_insight_module
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class InsightModuleParams(BaseModel):
    """Parameters for insight module tool"""

    module_id: str = Field(..., description="The ID of the insight module to retrieve")
    # Boolean with default: allow None and fall back to default
    include_translations: Optional[bool] = Field(False, description="Include translations in the response")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get detailed information about a specific insight module"""
    try:
        # Validate arguments with Pydantic
        try:
            args = InsightModuleParams(**arguments)
            if args.include_translations is None:
                args.include_translations = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        options: dict = {"includeTranslations": args.include_translations}
        query = get_insight_module(args.module_id, options)
        context.log.debug("Executing query to get insight module")
        result = await client.query(query)

        module = result.get("internalInsightModule")
        if not module:
            return format_error_response(Exception("Insight module not found"))

        return format_success_response(module, "Successfully retrieved insight module")
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(InsightModuleParams)
TOOL_METADATA = {
    "name": "exosense-get-insight-module",
    "description": "Get detailed information about a specific insight module",
    "inputSchema": schema
}
