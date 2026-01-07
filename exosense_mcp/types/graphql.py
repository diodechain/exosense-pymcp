"""TypeScript types for ExoSense GraphQL"""

from typing import Optional
from pydantic import BaseModel


class Pagination(BaseModel):
    """Pagination options"""

    limit: Optional[int] = None
    offset: Optional[int] = None


class BriefInfo(BaseModel):
    """Bare minimum structure to avoid fetching the full details"""

    id: str
    name: str


class BriefUserInfo(BriefInfo):
    """Brief user information"""

    email: Optional[str] = None


class MetricDatapoint(BaseModel):
    """Metric datapoint structure"""

    timestamp: str
    valueString: str
    value: float
    protocol: str
    receivedTime: str


class Tag(BaseModel):
    """Tag structure"""

    name: str
    value: str


OrderBy = str  # "asc" | "desc"
ISO8601 = str  # Date/time string in ISO 8601 format
JSON = dict  # Generic JSON object type
UUID = str  # UUID type for unique identifiers

