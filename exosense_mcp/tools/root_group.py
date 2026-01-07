"""Get root group information from ExoSense"""

import json
from typing import Dict, Any
from pydantic import BaseModel, ValidationError
from ..graphql.groups import get_root_group_id
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class RootGroupParams(BaseModel):
    """Parameters for root group tool"""
    pass


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get the root group information from ExoSense"""
    try:
        # Validate arguments with Pydantic
        try:
            args = RootGroupParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        query = get_root_group_id()
        context.log.debug("Executing query to get root group")
        result = await client.query(query)

        return format_success_response(
            result, "Successfully retrieved root group information"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(RootGroupParams)
TOOL_METADATA = {
    "name": "exosense-get-root-group",
    "description": "Get the root group information from ExoSense",
    "inputSchema": schema
}
