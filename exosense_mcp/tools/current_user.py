"""Get the current user information from ExoSense"""

import json
from typing import Dict, Any
from ..exosense_client import GraphQLQuery
from .types import ToolContext


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get the current user information from ExoSense"""
    import exosense_mcp.server as server_module
    auth = context.session.get("authorization") if context.session else None
    client = server_module.get_exosense_client(auth)

    user = await client.query(
        GraphQLQuery(
            query="""
            query GetCurrentUser {
              currentUser {
                id
                email
              }
            }
            """,
            operation_name="GetCurrentUser",
        )
    )

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "data": user,
                        "message": "Successfully retrieved current user information",
                    },
                    indent=2,
                ),
            }
        ]
    }


# Tool metadata for MCP protocol
TOOL_METADATA = {
    "name": "exosense-current-user",
    "description": "Get the current user information from ExoSense",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
