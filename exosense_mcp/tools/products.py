"""Get all IoT Connectors (products) from ExoSense"""

from typing import Dict, Any
from pydantic import BaseModel, ValidationError
from ..graphql.devices_products import get_all_products
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class ProductsParams(BaseModel):
    """Parameters for products tool"""
    pass


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get all IoT Connectors (products) from ExoSense"""
    try:
        # Validate arguments with Pydantic
        try:
            args = ProductsParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        query = get_all_products()
        context.log.debug("Executing query to get all products")
        result = await client.query(query)

        products = result.get("products", [])
        return format_success_response(
            products, f"Successfully retrieved {len(products)} products"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(ProductsParams)
TOOL_METADATA = {
    "name": "exosense-get-products",
    "description": "Get all IoT Connectors (products) from ExoSense",
    "inputSchema": schema
}
