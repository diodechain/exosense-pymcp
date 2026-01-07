"""Common tool context interface and tool definition types"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from ..types.auth import ExoSenseAuth


class Logger(Protocol):
    """Logger interface for tools"""

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        ...

    def info(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        ...

    def warn(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        ...

    def error(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        ...


@dataclass
class ToolContext:
    """Common tool context interface matching MCP's Context"""

    log: Logger
    report_progress: Callable[[Dict[str, Any]], Any]
    session: Optional[Dict[str, ExoSenseAuth]] = None


@dataclass
class ToolDefinition:
    """Tool definition interface for consistent tool structure"""

    name: str
    description: str
    parameters: type  # Pydantic model class
    execute: Callable[[Any, ToolContext], Any]
    annotations: Optional[Dict[str, Any]] = None

