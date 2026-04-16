"""ExoSense API client with GraphQL support"""

from typing import Any, Dict, Optional, Union
import httpx
from pydantic import BaseModel

from .types.auth import ExoSenseAuth, ExoSenseConfig, TokenAuth, APIKeyAuth, OAuthAuth


class GraphQLQuery(BaseModel):
    """GraphQL query structure"""

    query: str
    variables: Optional[Dict[str, Any]] = None
    operation_name: Optional[str] = None


class GraphQLError(BaseModel):
    """GraphQL error structure"""

    message: str
    locations: Optional[list[Dict[str, int]]] = None
    path: Optional[list[Union[str, int]]] = None
    extensions: Optional[Dict[str, Any]] = None


class GraphQLResponse(BaseModel):
    """GraphQL response structure"""

    data: Optional[Dict[str, Any]] = None
    errors: Optional[list[GraphQLError]] = None
    extensions: Optional[Dict[str, Any]] = None


class ExoSenseClient:
    """ExoSense API client with GraphQL support"""

    def __init__(self, config: ExoSenseConfig):
        self.auth = config.auth
        self.graphql_endpoint = config.graphql_endpoint
        self.timeout = config.timeout or 30000
        timeout_sec = self.timeout / 1000.0
        # Reuse one client for connection pooling (avoid new TCP/TLS per GraphQL call).
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_sec),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )

    async def aclose(self) -> None:
        """Close the HTTP client (call on shutdown or before replacing the client)."""
        await self._http.aclose()

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers based on auth type"""
        headers: Dict[str, str] = {}
        
        if isinstance(self.auth, TokenAuth):
            headers["Authorization"] = f"Automation {self.auth.token}"
            headers["Origin"] = self.auth.origin
        elif isinstance(self.auth, APIKeyAuth):
            headers["X-API-Key"] = self.auth.apiKey
            headers["Origin"] = self.auth.origin
        elif isinstance(self.auth, OAuthAuth):
            headers["Authorization"] = f"Bearer {self.auth.accessToken}"
            headers["Origin"] = self.auth.origin
            
        return headers

    async def graphql(self, query: GraphQLQuery) -> GraphQLResponse:
        """Execute a GraphQL query"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ExoSense-MCP-Server/1.0.0",
            **self._get_auth_headers(),
        }

        payload = {
            "query": query.query,
            "variables": query.variables or {},
        }
        if query.operation_name:
            payload["operationName"] = query.operation_name

        try:
            response = await self._http.post(
                self.graphql_endpoint,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            result_data = response.json()
            result = GraphQLResponse(**result_data)

            # Handle GraphQL errors
            if result.errors:
                error_messages = ", ".join(err.message for err in result.errors)
                raise ValueError(f"GraphQL Error: {error_messages}")

            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Authentication failed - check your credentials") from e
            if e.response.status_code == 403:
                raise ValueError("Access forbidden - insufficient permissions") from e
            if e.response.status_code >= 500:
                raise ValueError(f"ExoSense server error: {e.response.status_code}") from e
            raise ValueError(
                f"GraphQL request failed: {e.response.text or str(e)}"
            ) from e
        except Exception as e:
            raise ValueError(f"GraphQL request failed: {str(e)}") from e

    async def query(self, query: GraphQLQuery) -> Dict[str, Any]:
        """Execute a GraphQL query and return only the data"""
        response = await self.graphql(query)
        if not response.data:
            raise ValueError("GraphQL query returned no data")
        return response.data

    async def mutate(self, mutation: GraphQLQuery) -> Dict[str, Any]:
        """Execute a GraphQL mutation"""
        response = await self.graphql(mutation)
        if not response.data:
            raise ValueError("GraphQL mutation returned no data")
        return response.data

