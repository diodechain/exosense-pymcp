"""Authentication handler for MCP server"""

from typing import Dict, Any
from .types.auth import ExoSenseAuth, TokenAuth, OAuthAuth


async def authenticate(request_headers: Dict[str, Any]) -> Dict[str, ExoSenseAuth]:
    """
    Authentication handler for MCP server
    
    Currently the work of the auth is passed over to GraphQL.
    """
    # Extract origin from headers - prefer x-origin, then origin header
    # If neither is provided, we'll leave it empty and let the caller decide
    # (server may have .env fallback, but we shouldn't mix here)
    origin = request_headers.get("x-origin") or request_headers.get("origin") or ""

    # Many of the MCP Clients don't let me change the type of the auth token.
    # But they allow using a different header name.
    # So we'll check an alt header for an automation token
    if "x-automation-token" in request_headers:
        token = request_headers["x-automation-token"]
        # If origin is missing, raise an error - don't silently use .env fallback
        # This ensures pipeline credentials are complete and not mixed with .env
        if not origin:
            raise ValueError("x-automation-token provided but x-origin or origin header is required")
        return {
            "authorization": TokenAuth(
                type="token",
                token=token,
                origin=origin,
            )
        }

    auth_header = request_headers.get("authorization")
    if not auth_header:
        raise ValueError("Missing or invalid authorization header")

    # Split auth into type and token
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        raise ValueError("Missing or invalid authorization header")

    auth_type, token = parts

    if auth_type == "Bearer":
        # Make an OAuthAuth object
        # If origin is missing, raise an error - don't silently use .env fallback
        if not origin:
            raise ValueError("Authorization: Bearer token provided but x-origin or origin header is required")
        return {
            "authorization": OAuthAuth(
                type="oauth",
                accessToken=token,
                origin=origin,
            )
        }

    if auth_type == "Automation":
        # Make a TokenAuth object
        # If origin is missing, raise an error - don't silently use .env fallback
        if not origin:
            raise ValueError("Authorization: Automation token provided but x-origin or origin header is required")
        return {
            "authorization": TokenAuth(
                type="token",
                token=token,
                origin=origin,
            )
        }

    raise ValueError("Unsupported authorization type")

