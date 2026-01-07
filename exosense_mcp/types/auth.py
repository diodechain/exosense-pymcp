"""Authentication types for ExoSense API"""

from typing import Literal, Optional
from pydantic import BaseModel


class TokenAuth(BaseModel):
    """Token-based authentication"""

    type: Literal["token"]
    token: str
    origin: str


class APIKeyAuth(BaseModel):
    """API key-based authentication"""

    type: Literal["apikey"]
    apiKey: str
    origin: str


class OAuthAuth(BaseModel):
    """OAuth-based authentication"""

    type: Literal["oauth"]
    accessToken: str
    refreshToken: Optional[str] = None
    origin: str


# Union type for all supported authentication methods
ExoSenseAuth = TokenAuth | APIKeyAuth | OAuthAuth


class ExoSenseConfig(BaseModel):
    """Configuration for ExoSense client"""

    graphql_endpoint: str
    auth: ExoSenseAuth
    timeout: int = 30000

