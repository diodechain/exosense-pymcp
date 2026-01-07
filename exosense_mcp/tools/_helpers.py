"""Helper functions for tools"""

from typing import Dict, Any, Type
from pydantic import BaseModel
import json


def pydantic_to_json_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model to JSON schema"""
    return model_class.model_json_schema()


def format_success_response(data: Any, message: str | None = None) -> Dict[str, Any]:
    """Format success response for MCP"""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "data": data,
                        "message": message,
                    },
                    indent=2,
                ),
            }
        ]
    }


def format_error_response(error: Exception | str) -> Dict[str, Any]:
    """Format error response for MCP"""
    message = str(error) if isinstance(error, Exception) else error
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": False,
                        "error": message,
                    },
                    indent=2,
                ),
            }
        ]
    }

