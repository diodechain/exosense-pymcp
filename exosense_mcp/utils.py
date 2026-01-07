"""Utility functions for ExoSense MCP server"""

from typing import Any, Dict, Union, Optional
from datetime import datetime

from .types.auth import ExoSenseAuth, TokenAuth


def validate_auth_token(token: str) -> bool:
    """Validate authentication token format"""
    if not token or not isinstance(token, str):
        return False

    # Basic validation - adjust based on ExoSense token format
    return 32 <= len(token) <= 256


def create_token_auth(token: str, origin: str = "https://exosense.com") -> TokenAuth:
    """Create authentication object from token"""
    if not validate_auth_token(token):
        raise ValueError("Invalid authentication token format")

    return TokenAuth(type="token", token=token, origin=origin)


def format_error_response(
    error: Union[Exception, str], context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Format error response for MCP"""
    import json
    message = str(error) if isinstance(error, Exception) else error
    error_code = getattr(error, "code", None) if isinstance(error, Exception) else None

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": False,
                        "error": message,
                        "code": error_code,
                        "context": context,
                        "timestamp": datetime.now().isoformat(),
                    },
                    indent=2,
                ),
            }
        ]
    }


def format_success_response(data: Any, message: Optional[str] = None) -> Dict[str, Any]:
    """Format success response for MCP"""
    import json
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "data": data,
                        "message": message,
                        "timestamp": datetime.now().isoformat(),
                    },
                    indent=2,
                ),
            }
        ]
    }


def parse_iso_date(date_string: str) -> datetime:
    """Parse ISO date string to datetime object with validation"""
    try:
        return datetime.fromisoformat(date_string.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Invalid date format: {date_string}") from e


def validate_required_params(params: Dict[str, Any], required: list[str]) -> None:
    """Validate required parameters"""
    missing = [
        param
        for param in required
        if params.get(param) is None or params.get(param) == ""
    ]

    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(missing)}")

