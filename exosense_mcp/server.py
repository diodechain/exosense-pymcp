"""
MCP Server implementation for ExoSense using aiohttp.
Compatible with Python 3.9+.
"""
import atexit
import inspect
import json
import uuid
import importlib.util
import sys
import logging
import os
import asyncio
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response
import yaml
from dotenv import load_dotenv

# Optional hot-reload support
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None

# Load environment variables
load_dotenv()

from .exosense_client import ExoSenseClient, GraphQLQuery
from .types.auth import ExoSenseAuth, TokenAuth, ExoSenseConfig
from .auth import authenticate

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def _dumps(obj: Any) -> str:
    """Compact JSON for MCP/JSON-RPC responses (faster, smaller than default spacing)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _mcp_session_id(request: Request) -> Optional[str]:
    """Session header (aiohttp headers are case-insensitive; one lookup per variant for odd clients)."""
    h = request.headers
    return h.get("Mcp-Session-Id") or h.get("mcp-session-id") or h.get("MCP-Session-Id")


class ToolContext:
    """Passed to tool execute functions; module-level to avoid per-request class creation."""

    __slots__ = ("session", "log", "report_progress")

    def __init__(self, session_auth: Optional[Any]) -> None:
        self.session = {"authorization": session_auth} if session_auth else None
        self.log = logger
        self.report_progress = lambda _p: None  # placeholder for MCP progress


# Environment variable configuration
EXOSENSE_API_URL = os.getenv("EXOSENSE_API_URL", "https://api.exosense.com")
EXOSENSE_AUTH_TOKEN = os.getenv("EXOSENSE_AUTH_TOKEN")
EXOSENSE_ORIGIN = os.getenv("EXOSENSE_ORIGIN", "https://exosense.com")
PORT = int(os.getenv("PORT", "9000"))
LISTEN_HOST = os.getenv("LISTEN_HOST", "127.0.0.1")
HTTP_STREAMING = os.getenv("HTTP_STREAMING")

# Session storage (in production, use a proper session store)
sessions: Dict[str, Dict[str, Any]] = {}

# Dynamically loaded tools: {tool_name: {"metadata": {...}, "execute": callable}}
TOOLS: Dict[str, Dict[str, Any]] = {}
TOOL_FUNCTIONS: Dict[str, Callable] = {}

# Global ExoSense client instance
_exosense_client: Optional[ExoSenseClient] = None


def _dispose_exosense_client(prev: Optional[ExoSenseClient]) -> None:
    """Schedule async close of replaced client (connection pool cleanup)."""
    if prev is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(prev.aclose())
    except RuntimeError:
        pass


def get_exosense_client(auth: Optional[ExoSenseAuth] = None) -> ExoSenseClient:
    """Initialize ExoSense client with authentication"""
    global _exosense_client

    if not _exosense_client or auth:
        # If auth is provided (from headers), use it as-is - don't mix with .env
        # The authenticate() function now requires origin header when credentials are provided
        # So we should never have auth without origin here, but keep the check for safety
        if auth:
            auth_to_use = auth
            # This should never happen now (authenticate() requires origin), but keep as safety check
            if not auth_to_use.origin:
                raise ValueError("Authentication provided but origin is missing. Please include x-origin or origin header.")
            # Derive API URL from the origin provided in headers
            # API URL is origin + "/api/graphql"
            graphql_endpoint = f"{auth_to_use.origin.rstrip('/')}/api/graphql"
            logger.debug(f"   Using API endpoint from origin: {graphql_endpoint}")
        else:
            # No auth provided, use .env defaults
            auth_to_use = TokenAuth(
                type="token",
                token=EXOSENSE_AUTH_TOKEN or "",
                origin=EXOSENSE_ORIGIN,
            )
            # Use .env API URL
            graphql_endpoint = EXOSENSE_API_URL

        if _exosense_client is not None:
            _dispose_exosense_client(_exosense_client)
        _exosense_client = ExoSenseClient(
            ExoSenseConfig(
                graphql_endpoint=graphql_endpoint,
                auth=auth_to_use,
            )
        )

    return _exosense_client


def load_config(config_path: str = "config.yml") -> Dict[str, Any]:
    """Load configuration from YAML file."""
    # Resolve config path relative to project root (where config.yml should be)
    # __file__ is exosense_mcp/server.py, so parent.parent is project root
    project_root = Path(__file__).parent.parent
    config_file = project_root / config_path
    
    if not config_file.exists():
        # Try current working directory as fallback
        config_file = Path(config_path)
        if not config_file.exists():
            # Create default config if it doesn't exist
            logger.warning(f"Config file not found: {config_path}")
            return {"tools": []}
    
    logger.debug(f"Loading config from: {config_file}")
    try:
        with open(config_file, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    except OSError as e:
        raise OSError(f"Cannot read config: {config_file}: {e}") from e
    try:
        config = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1} column {mark.column + 1})" if mark is not None else ""
        msg = f"Invalid YAML in {config_file}{where}: {e!s}. Re-copy from the repo or fix the file (tabs, merge conflicts, or text without a leading # on a comment line)."
        raise ValueError(msg) from e
    if config is None:
        return {"tools": []}
    return config


def resolve_diode_client_mode() -> str:
    """
    Defaults to embedded Diode (this process manages diode_client/). Only when
    DIODE_CLIENT=container do we skip starting Diode and rely on a sidecar/image.
    Unset, empty, or embedded → embedded; unknown values log a warning and use embedded.
    """
    raw = (os.getenv("DIODE_CLIENT") or "").strip().lower()
    if raw == "container":
        return "container"
    if raw and raw != "embedded":
        logger.warning("Unknown DIODE_CLIENT %r; using embedded", os.getenv("DIODE_CLIENT"))
    return "embedded"


def load_tool_module(tool_file: str) -> tuple:
    """
    Dynamically load a tool module from a file path.
    Returns (tool_metadata, execute_function)
    
    All paths are resolved relative to the project root (exosense-pymcp directory).
    tool_file should be like "exosense_mcp/tools/current_user.py"
    """
    # Resolve paths relative to project root
    # __file__ is exosense_mcp/server.py, so parent is exosense_mcp/, parent.parent is project root
    project_root = Path(__file__).parent.parent
    exosense_mcp_dir = Path(__file__).parent
    
    # Determine the full module path for proper package structure
    # tool_file is like "exosense_mcp/tools/current_user.py"
    # We need to convert it to "exosense_mcp.tools.current_user"
    if tool_file.startswith("exosense_mcp/"):
        # Remove .py extension and convert / to .
        module_path = tool_file.replace("/", ".").replace(".py", "")
        # Resolve file path relative to project root
        tool_path = project_root / tool_file
    else:
        # Try relative to exosense_mcp directory
        tool_path = exosense_mcp_dir / tool_file
        if not tool_path.exists():
            # Try as absolute path
            tool_path = Path(tool_file)
            if not tool_path.exists():
                raise FileNotFoundError(f"Tool file not found: {tool_file}")
        
        # Extract module name from path relative to project root
        try:
            tool_path = tool_path.resolve()
            project_root = project_root.resolve()
            relative_path = tool_path.relative_to(project_root)
            module_path = str(relative_path).replace("/", ".").replace(".py", "")
        except ValueError:
            # If path is not relative to project root, infer module name
            if "exosense_mcp" in str(tool_path):
                parts = tool_path.parts
                idx = parts.index("exosense_mcp") if "exosense_mcp" in parts else -1
                if idx >= 0:
                    module_path = ".".join(parts[idx:]).replace(".py", "")
                else:
                    module_path = f"exosense_mcp.tools.{tool_path.stem}"
            else:
                module_path = f"exosense_mcp.tools.{tool_path.stem}"
    
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool file not found: {tool_path}")
    
    logger.debug(f"Loading tool module: {module_path} from {tool_path}")
    
    # Try to import the module normally first (this preserves package structure)
    # This works because exosense_mcp is a proper Python package
    try:
        module = importlib.import_module(module_path)
        logger.debug(f"Successfully imported {module_path} via normal import")
    except ImportError as e:
        # If normal import fails, try loading from file location
        logger.debug(f"Normal import failed for {module_path}, trying file-based load: {e}")
        
        # Ensure parent packages exist in sys.modules
        parts = module_path.split(".")
        for i in range(1, len(parts)):
            parent_module = ".".join(parts[:i])
            if parent_module not in sys.modules:
                try:
                    importlib.import_module(parent_module)
                except ImportError:
                    # Create a minimal package module
                    parent_mod = type(sys)(parent_module)
                    parent_mod.__name__ = parent_module
                    parent_mod.__package__ = ".".join(parts[:i-1]) if i > 1 else parts[0]
                    if i == 1:  # exosense_mcp
                        parent_mod.__path__ = [str(exosense_mcp_dir)]
                    elif i == 2:  # exosense_mcp.tools
                        parent_mod.__path__ = [str(exosense_mcp_dir / "tools")]
                    sys.modules[parent_module] = parent_mod
        
        # Load from file location
        spec = importlib.util.spec_from_file_location(module_path, tool_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from {tool_file}")
        
        module = importlib.util.module_from_spec(spec)
        if "." in module_path:
            module.__package__ = ".".join(module_path.split(".")[:-1])
        module.__name__ = module_path
        sys.modules[module_path] = module
        spec.loader.exec_module(module)
        logger.debug(f"Successfully loaded {module_path} from file")
    
    # Get metadata and execute function
    if not hasattr(module, 'TOOL_METADATA'):
        raise AttributeError(f"Tool module {tool_file} must define TOOL_METADATA")
    if not hasattr(module, 'execute'):
        raise AttributeError(f"Tool module {tool_file} must define execute() function")
    
    return module.TOOL_METADATA, module.execute


def reload_tool_module(module_path: str):
    """Reload a tool module by removing it from sys.modules and reimporting"""
    # Remove from sys.modules to force reload
    if module_path in sys.modules:
        del sys.modules[module_path]
    # Also remove parent packages if they're tool modules
    parts = module_path.split(".")
    for i in range(len(parts), 0, -1):
        parent = ".".join(parts[:i])
        if parent.startswith("exosense_mcp.tools.") and parent in sys.modules:
            # Only remove tool modules, not the main package
            if parent != "exosense_mcp.tools":
                del sys.modules[parent]


def load_tools_from_config(config_path: str = "config.yml", reload: bool = False):
    """Load all tools from config.yml."""
    global TOOLS, TOOL_FUNCTIONS
    
    if reload:
        logger.info("🔄 Reloading tools from config...")
        # Clear existing tools
        TOOLS = {}
        TOOL_FUNCTIONS = {}
    
    config = load_config(config_path)
    tools_config = config.get("tools", [])
    
    if not reload:
        TOOLS = {}
        TOOL_FUNCTIONS = {}
    
    for tool_entry in tools_config:
        tool_file = tool_entry.get("file")
        tool_name = tool_entry.get("name")
        
        if not tool_file or not tool_name:
            logger.warning(f"Skipping invalid tool entry: {tool_entry}")
            continue
        
        try:
            # If reloading, clear the module from cache first
            if reload:
                # Determine module path
                project_root = Path(__file__).parent.parent
                tool_path = project_root / tool_file
                if tool_path.exists():
                    try:
                        relative_path = tool_path.relative_to(project_root)
                        module_path = str(relative_path).replace("/", ".").replace(".py", "")
                        reload_tool_module(module_path)
                    except Exception as e:
                        logger.debug(f"Could not reload module {tool_file}: {e}")
            
            metadata, execute_func = load_tool_module(tool_file)
            
            # Verify the tool name matches
            if metadata.get("name") != tool_name:
                logger.warning(f"Tool name mismatch in {tool_file}. Expected {tool_name}, got {metadata.get('name')}")
            
            TOOLS[tool_name] = metadata
            TOOL_FUNCTIONS[tool_name] = execute_func
            logger.info(f"{'🔄 Reloaded' if reload else 'Loaded'} tool: {tool_name} from {tool_file}")
            
        except Exception as e:
            logger.exception(f"Error loading tool {tool_name} from {tool_file}: {e}")
            continue
    
    if reload:
        logger.info(f"✅ Reload complete: {len(TOOLS)} tools loaded")


# Load tools on module import
load_tools_from_config()


# File watcher for hot-reloading (optional, requires watchdog)
if WATCHDOG_AVAILABLE:
    class ToolReloadHandler(FileSystemEventHandler):
        """Handler for file system events to reload tools"""
        
        def __init__(self, config_path: str, project_root: Path):
            self.config_path = config_path
            self.project_root = project_root
            self.last_reload = {}
            self.debounce_seconds = 1.0  # Debounce rapid file changes
            
        def on_modified(self, event):
            """Handle file modification events"""
            if event.is_directory:
                return
            
            file_path = Path(event.src_path)
            
            # Check if it's config.yml
            if file_path.name == "config.yml" or str(file_path) == str(self.project_root / self.config_path):
                self._reload_config()
                return
            
            # Check if it's a tool file
            if file_path.suffix == ".py" and "tools" in str(file_path):
                # Debounce: only reload if enough time has passed
                import time
                current_time = time.time()
                file_str = str(file_path)
                
                if file_str in self.last_reload:
                    if current_time - self.last_reload[file_str] < self.debounce_seconds:
                        return  # Too soon, skip
                
                self.last_reload[file_str] = current_time
                self._reload_tool(file_path)
        
        def _reload_config(self):
            """Reload all tools from config"""
            logger.info("📝 config.yml changed, reloading all tools...")
            try:
                load_tools_from_config(self.config_path, reload=True)
                logger.info(f"✅ Reloaded {len(TOOLS)} tools")
            except Exception as e:
                logger.error(f"❌ Error reloading tools: {e}", exc_info=True)
        
        def _reload_tool(self, tool_path: Path):
            """Reload a specific tool file"""
            # Find which tool this file corresponds to
            try:
                relative_path = tool_path.relative_to(self.project_root)
                tool_file = str(relative_path).replace("\\", "/")
                
                # Find in config
                config = load_config(self.config_path)
                tools_config = config.get("tools", [])
                
                for tool_entry in tools_config:
                    if tool_entry.get("file") == tool_file:
                        tool_name = tool_entry.get("name")
                        logger.info(f"📝 Tool file changed: {tool_file}, reloading tool: {tool_name}")
                        try:
                            load_tools_from_config(self.config_path, reload=True)
                            logger.info(f"✅ Reloaded tool: {tool_name}")
                        except Exception as e:
                            logger.error(f"❌ Error reloading tool {tool_name}: {e}", exc_info=True)
                        return
                
                logger.debug(f"File changed but not in config: {tool_file}")
            except Exception as e:
                logger.debug(f"Could not determine tool for file {tool_path}: {e}")
    
    def start_file_watcher(config_path: str = "config.yml"):
        """Start watching for file changes to enable hot-reloading"""
        if not WATCHDOG_AVAILABLE:
            logger.warning("⚠️  Hot-reload disabled: watchdog not installed. Install with: pip install watchdog")
            return None
        
        project_root = Path(__file__).parent.parent
        config_file = project_root / config_path
        
        # Watch config file and tools directory
        event_handler = ToolReloadHandler(config_path, project_root)
        observer = Observer()
        
        # Watch config file
        if config_file.exists():
            observer.schedule(event_handler, config_file.parent, recursive=False)
            logger.info(f"👀 Watching config file: {config_file}")
        
        # Watch tools directory
        tools_dir = project_root / "exosense_mcp" / "tools"
        if tools_dir.exists():
            observer.schedule(event_handler, tools_dir, recursive=False)
            logger.info(f"👀 Watching tools directory: {tools_dir}")
        
        observer.start()
        logger.info("🔄 Hot-reload enabled: tools will reload automatically on file changes")
        return observer
    
    def stop_file_watcher(observer):
        """Stop the file watcher"""
        if observer:
            observer.stop()
            observer.join()
            logger.info("🛑 File watcher stopped")
else:
    def start_file_watcher(config_path: str = "config.yml"):
        """Placeholder when watchdog is not available"""
        logger.warning("⚠️  Hot-reload disabled: watchdog not installed. Install with: pip install watchdog")
        return None
    
    def stop_file_watcher(observer):
        """Placeholder when watchdog is not available"""
        pass


def create_jsonrpc_response(request_id: Any, result: Any = None, error: Optional[Dict] = None) -> Dict:
    """Create a JSON-RPC 2.0 response."""
    response = {
        "jsonrpc": "2.0",
        "id": request_id
    }
    if error:
        response["error"] = error
    else:
        response["result"] = result
    return response


def create_text_content(text: str) -> List[Dict[str, str]]:
    """Create MCP text content format."""
    return [{"type": "text", "text": text}]


async def handle_initialize(request: Request) -> Response:
    """Handle initialize method."""
    try:
        data = await request.json()
        request_id = data.get("id")
        params = data.get("params", {})
        
        logger.debug(f"🔧 Initialize request - ID: {request_id}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("   Params: %s", _dumps(params))
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Extract authentication: try headers first, fall back to .env
        # This supports hybrid single/multi-tenant: IT can set default in .env,
        # but clients can override with their own credentials
        auth = None
        
        # First, try to get auth from headers (client-provided, multi-tenant style)
        logger.debug("   Attempting to extract auth from headers")
        try:
            logger.debug("   Request header keys: %s", list(request.headers.keys()))
            auth_result = await authenticate(request.headers)
            if auth_result and "authorization" in auth_result:
                auth = auth_result["authorization"]
                # Log if origin is missing - will use .env fallback
                if hasattr(auth, 'token') and auth.token and not auth.origin:
                    logger.warning(f"   ⚠️  Token provided but origin missing - will use .env origin as fallback")
                elif hasattr(auth, 'accessToken') and auth.accessToken and not auth.origin:
                    logger.warning(f"   ⚠️  OAuth token provided but origin missing - will use .env origin as fallback")
                else:
                    logger.debug("   ✅ Auth extracted from headers (client-provided)")
            else:
                logger.debug("   No auth found in headers")
        except Exception as e:
            logger.debug(f"   Auth extraction from headers failed: {e}")
            # Continue to fallback
        
        # If no auth from headers, fall back to .env variables (IT-provided default)
        if not auth:
            if EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN:
                logger.debug("   Using .env authentication (fallback/default)")
                auth = TokenAuth(
                    type="token",
                    token=EXOSENSE_AUTH_TOKEN,
                    origin=EXOSENSE_ORIGIN,
                )
            else:
                logger.warning("   ⚠️  No authentication available (neither headers nor .env)")
        
        sessions[session_id] = {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "clientInfo": params.get("clientInfo", {}),
            "authorization": auth,
        }
        client_name = params.get('clientInfo', {}).get('name', 'unknown')
        logger.debug(f"✅ New session created: {session_id} (client: {client_name})")
        
        # Build authentication metadata for discovery
        auth_metadata = {
            "required": False,  # Auth is optional (has .env fallback)
            "methods": [
                {
                    "type": "automation_token",
                    "header": "x-automation-token",
                    "description": "ExoSense automation token",
                    "required_headers": ["x-automation-token", "x-origin"]
                },
                {
                    "type": "bearer_token",
                    "header": "Authorization",
                    "scheme": "Automation",
                    "description": "Automation token via Authorization header",
                    "required_headers": ["Authorization", "origin"]
                },
                {
                    "type": "oauth",
                    "header": "Authorization",
                    "scheme": "Bearer",
                    "description": "OAuth bearer token",
                    "required_headers": ["Authorization", "origin"]
                }
            ],
            "fallback_available": bool(EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN),
            "fallback_description": "Server has default credentials configured in .env (optional)"
        }
        
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "authentication": auth_metadata
            },
            "serverInfo": {
                "name": "exosense-mcp-server",
                "version": "1.0.0"
            }
        }
        
        response_data = create_jsonrpc_response(request_id, result)
        
        return web.Response(
            text=_dumps(response_data),
            content_type="application/json",
            headers={"Mcp-Session-Id": session_id}
        )
    except Exception as e:
        logger.error(f"Error in initialize: {e}", exc_info=True)
        return web.Response(
            text=_dumps(create_jsonrpc_response(
                data.get("id") if 'data' in locals() else None,
                error={"code": -32603, "message": f"Internal error: {str(e)}"}
            )),
            content_type="application/json",
            status=500
        )


async def handle_tools_list(request: Request) -> Response:
    """Handle tools/list method."""
    try:
        data = await request.json()
        request_id = data.get("id")
        session_id = _mcp_session_id(request)

        logger.debug(f"📋 Tools/list request - ID: {request_id}, Session: {session_id}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("   All headers: %s", dict(request.headers))
        logger.debug(f"   Tools available: {len(TOOLS)}")
        
        # Verify session
        if not session_id or session_id not in sessions:
            logger.warning(f"   ❌ Invalid or missing session: {session_id}")
            logger.debug(f"   Active sessions: {list(sessions.keys())}")
            return web.Response(
                text=_dumps(create_jsonrpc_response(
                    request_id,
                    error={
                        "code": -32000,
                        "message": "Invalid or missing session. Please call 'initialize' first."
                    }
                )),
                content_type="application/json",
                status=401
            )
        
        # Return list of tools
        tools_list = list(TOOLS.values())
        result = {"tools": tools_list}
        
        logger.debug(f"   ✅ Returning {len(tools_list)} tools")
        logger.debug(f"   Tool names: {[t.get('name') for t in tools_list]}")
        
        response_data = create_jsonrpc_response(request_id, result)
        
        return web.Response(
            text=_dumps(response_data),
            content_type="application/json",
            headers={"Mcp-Session-Id": session_id}
        )
    except Exception as e:
        logger.error(f"Error in tools/list: {e}", exc_info=True)
        return web.Response(
            text=_dumps(create_jsonrpc_response(
                data.get("id") if 'data' in locals() else None,
                error={"code": -32603, "message": f"Internal error: {str(e)}"}
            )),
            content_type="application/json",
            status=500
        )


async def handle_tools_call(request: Request) -> Response:
    """Handle tools/call method."""
    try:
        data = await request.json()
        request_id = data.get("id")
        params = data.get("params", {})
        
        session_id = _mcp_session_id(request)
        
        # Verify session
        if not session_id:
            return web.Response(
                text=_dumps(create_jsonrpc_response(
                    request_id,
                    error={
                        "code": -32000,
                        "message": "Missing session ID. Please call 'initialize' first to establish a session."
                    }
                )),
                content_type="application/json",
                status=401
            )
        
        if session_id not in sessions:
            return web.Response(
                text=_dumps(create_jsonrpc_response(
                    request_id,
                    error={
                        "code": -32000,
                        "message": f"Invalid or expired session. Please call 'initialize' to create a new session."
                    }
                )),
                content_type="application/json",
                status=401
            )
        
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        logger.info("Tool call: %s", tool_name)
        logger.debug("Tool args: %s", arguments)
        
        # Check if tool exists
        if tool_name not in TOOL_FUNCTIONS:
            return web.Response(
                text=_dumps(create_jsonrpc_response(
                    request_id,
                    error={"code": -32601, "message": f"Unknown tool: {tool_name}"}
                )),
                content_type="application/json",
                status=400
            )
        
        # Get the tool's execute function and metadata
        execute_func = TOOL_FUNCTIONS[tool_name]
        tool_metadata = TOOLS.get(tool_name, {})
        input_schema = tool_metadata.get("inputSchema", {})
        required_params = input_schema.get("required", [])
        
        # Validate required arguments
        if required_params:
            missing_params = [param for param in required_params if param not in arguments]
            if missing_params:
                return web.Response(
                    text=_dumps(create_jsonrpc_response(
                        request_id,
                        error={
                            "code": -32602,
                            "message": f"Missing required arguments: {', '.join(missing_params)}"
                        }
                    )),
                    content_type="application/json",
                    status=400
                )
        
        # Get session for authentication context
        session = sessions[session_id]
        auth = session.get("authorization")
        
        # If no auth in session, fall back to .env (hybrid mode support)
        # This allows tools to work even if client didn't provide headers
        if not auth and EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN:
            logger.debug(f"   No session auth, using .env fallback")
            auth = TokenAuth(
                type="token",
                token=EXOSENSE_AUTH_TOKEN,
                origin=EXOSENSE_ORIGIN,
            )
        
        context = ToolContext(auth)
        
        # Execute the tool
        try:
            if inspect.iscoroutinefunction(execute_func):
                result_data = await execute_func(arguments, context)
            else:
                result_data = execute_func(arguments, context)
            
            # Convert result to JSON string for text content
            if isinstance(result_data, dict) and "content" in result_data:
                # Already in MCP format
                content = result_data["content"]
            elif isinstance(result_data, (dict, list)):
                result_text = _dumps(result_data)
                content = create_text_content(result_text)
            else:
                result_text = str(result_data)
                content = create_text_content(result_text)
            
            result = {"content": content}
            
        except Exception as e:
            logger.error(f"Exception executing tool {tool_name}: {e}", exc_info=True)
            error_response = create_jsonrpc_response(
                request_id,
                error={"code": -32603, "message": f"Tool execution error: {str(e)}"}
            )
            return web.Response(
                text=_dumps(error_response),
                content_type="application/json",
                status=500
            )
        
        response_data = create_jsonrpc_response(request_id, result)
        
        return web.Response(
            text=_dumps(response_data),
            content_type="application/json",
            headers={"Mcp-Session-Id": session_id}
        )
    except Exception as e:
        logger.error(f"Error in tools/call: {e}", exc_info=True)
        return web.Response(
            text=_dumps(create_jsonrpc_response(
                data.get("id") if 'data' in locals() else None,
                error={"code": -32603, "message": f"Internal error: {str(e)}"}
            )),
            content_type="application/json",
            status=500
        )


@web.middleware
async def cors_middleware(request: Request, handler):
    """Middleware to add CORS headers to all responses."""
    # Handle OPTIONS preflight requests
    if request.method == "OPTIONS":
        logger.debug("OPTIONS request (CORS preflight)")
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, x-automation-token, origin",
                "Access-Control-Max-Age": "3600"
            }
        )
    
    # Process request and add CORS headers to response
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Mcp-Session-Id, x-automation-token, origin"
    return response


@web.middleware
async def logging_middleware(request: Request, handler):
    """Middleware to log incoming requests. Hot paths (MCP, health) stay at DEBUG to avoid I/O overhead."""
    path = request.path
    is_lightweight = (
        (request.method == "POST" and path == "/mcp")
        or (request.method == "GET" and path in ("/health", "/", "/.well-known/mcp-authentication"))
    )

    if is_lightweight:
        logger.debug(f"📥 {request.method} {path}")
    else:
        logger.info("=" * 80)
        logger.info(f"📥 INCOMING REQUEST: {request.method} {request.path_qs}")
        logger.info(f"   Remote: {request.remote}")
        logger.info(f"   URL: {request.url}")
        logger.debug(f"   Headers: {dict(request.headers)}")

    try:
        response = await handler(request)
        if is_lightweight:
            logger.debug(f"📤 {response.status} {path}")
        else:
            logger.info(f"📤 RESPONSE: Status {response.status}")
            if response.headers:
                logger.debug(f"   Response Headers: {dict(response.headers)}")
            logger.info("=" * 80)
        return response
    except Exception as e:
        logger.error(f"❌ ERROR in handler: {e}", exc_info=True)
        if not is_lightweight:
            logger.info("=" * 80)
        raise


async def handle_mcp_request(request: Request) -> Response:
    """Main MCP request handler - routes to appropriate method handler."""
    try:
        data = await request.json()
        method = data.get("method")
        request_id = data.get("id")
        
        # Only log routine operations at DEBUG level
        is_routine = method in ("initialize", "tools/list")
        if is_routine:
            logger.debug(f"🔍 Processing MCP request: method={method}, id={request_id}")
        else:
            logger.info(f"🔍 Processing MCP request: method={method}, id={request_id}")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("   Full request data: %s", _dumps(data))
        
        if method == "initialize":
            logger.debug("   → Routing to initialize handler")
            return await handle_initialize(request)
        elif method == "tools/list":
            logger.debug("   → Routing to tools/list handler")
            return await handle_tools_list(request)
        elif method == "tools/call":
            logger.debug("   → Routing to tools/call handler")
            return await handle_tools_call(request)
        else:
            logger.warning(f"   ⚠️  Unknown method: {method}")
            return web.Response(
                text=_dumps(create_jsonrpc_response(
                    request_id,
                    error={"code": -32601, "message": f"Method not found: {method}"}
                )),
                content_type="application/json",
                status=404
            )
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON decode error: {e}")
        return web.Response(
            text=_dumps(create_jsonrpc_response(
                None,
                error={"code": -32700, "message": "Parse error"}
            )),
            content_type="application/json",
            status=400
        )
    except Exception as e:
        logger.error(f"❌ Error in handle_mcp_request: {e}", exc_info=True)
        return web.Response(
            text=_dumps(create_jsonrpc_response(
                None,
                error={"code": -32603, "message": f"Internal error: {str(e)}"}
            )),
            content_type="application/json",
            status=500
        )


async def _cleanup_exosense_http(app: web.Application) -> None:
    global _exosense_client
    if _exosense_client is not None:
        await _exosense_client.aclose()
        _exosense_client = None


def create_app() -> web.Application:
    """Create the aiohttp application."""
    # Middlewares are applied in reverse order
    # Disable aiohttp's built-in access logger to reduce verbosity
    app = web.Application(middlewares=[logging_middleware, cors_middleware])
    app.on_cleanup.append(_cleanup_exosense_http)
    # Disable aiohttp access logger
    aiohttp_access_logger = logging.getLogger("aiohttp.access")
    aiohttp_access_logger.setLevel(logging.WARNING)  # Only show warnings/errors
    app.router.add_post("/mcp", handle_mcp_request)
    
    # Add a simple health check endpoint
    async def health_check(request: Request) -> Response:
        logger.debug("🏥 Health check")
        return web.Response(
            text=_dumps({
                "status": "ok",
                "tools_loaded": len(TOOLS),
                "sessions_active": len(sessions)
            }),
            content_type="application/json"
        )
    
    # Add authentication discovery endpoint (industry standard .well-known pattern)
    async def auth_discovery(request: Request) -> Response:
        """
        Authentication discovery endpoint (industry standard .well-known pattern).
        Allows clients to discover what authentication methods are supported.
        """
        auth_metadata = {
            "authentication": {
                "required": False,  # Auth is optional (has .env fallback)
                "methods": [
                    {
                        "type": "automation_token",
                        "header": "x-automation-token",
                        "description": "ExoSense automation token",
                        "required_headers": ["x-automation-token", "x-origin"],
                        "example": {
                            "x-automation-token": "your-automation-token",
                            "x-origin": "https://your-instance.exosense.com"
                        }
                    },
                    {
                        "type": "bearer_token",
                        "header": "Authorization",
                        "scheme": "Automation",
                        "description": "Automation token via Authorization header",
                        "required_headers": ["Authorization", "origin"],
                        "example": {
                            "Authorization": "Automation your-automation-token",
                            "origin": "https://your-instance.exosense.com"
                        }
                    },
                    {
                        "type": "oauth",
                        "header": "Authorization",
                        "scheme": "Bearer",
                        "description": "OAuth bearer token",
                        "required_headers": ["Authorization", "origin"],
                        "example": {
                            "Authorization": "Bearer your-oauth-token",
                            "origin": "https://your-instance.exosense.com"
                        }
                    }
                ],
                "fallback_available": bool(EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN),
                "fallback_description": "Server has default credentials configured in .env (optional - clients can still override with headers)"
            },
            "server": {
                "name": "exosense-mcp-server",
                "version": "1.0.0",
                "protocol": "MCP",
                "protocolVersion": "2024-11-05"
            }
        }
        
        return web.Response(
            text=_dumps(auth_metadata),
            content_type="application/json"
        )
    
    app.router.add_get("/health", health_check)
    app.router.add_get("/", health_check)  # Also respond to root
    app.router.add_get("/.well-known/mcp-authentication", auth_discovery)
    
    return app


async def test_connection() -> None:
    """Test connection to ExoSense before starting server"""
    if not EXOSENSE_API_URL:
        print("⚠️  EXOSENSE_API_URL not set - connection test skipped", file=sys.stderr)
        return

    try:
        print("🔌 Testing connection to ExoSense...", file=sys.stderr)
        print(f"   API URL: {EXOSENSE_API_URL}", file=sys.stderr)
        print(f"   Origin: {EXOSENSE_ORIGIN or 'not set'}", file=sys.stderr)
        print(
            f"   Auth Token: {'***' + EXOSENSE_AUTH_TOKEN[-4:] if EXOSENSE_AUTH_TOKEN else 'not set'}",
            file=sys.stderr,
        )

        # Display authentication mode
        if EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN:
            print("   Auth Mode: Hybrid (headers first, .env fallback)", file=sys.stderr)
            print("   Default credentials available from .env", file=sys.stderr)
        else:
            print("   Auth Mode: Client-provided only (no .env fallback)", file=sys.stderr)

        # Only test if we have auth credentials
        if EXOSENSE_AUTH_TOKEN:
            test_client = get_exosense_client()
            result = await test_client.query(
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

            if result.get("currentUser"):
                user = result["currentUser"]
                print(f"✅ Successfully connected to ExoSense", file=sys.stderr)
                print(f"   User: {user.get('email') or user.get('id')}", file=sys.stderr)
            else:
                print("⚠️  Connection test returned no user data", file=sys.stderr)
        else:
            print("ℹ️  No auth token provided - connection test skipped (HTTP mode)", file=sys.stderr)
    except Exception as error:
        print("❌ Failed to connect to ExoSense:", file=sys.stderr)
        print(f"   {str(error)}", file=sys.stderr)
        print("   Please check your configuration in .env file", file=sys.stderr)


def main():
    """Main entry point for the server"""
    # Test connection first
    asyncio.run(test_connection())

    # Start file watcher for hot-reloading (if available)
    observer = None
    if os.getenv("HOT_RELOAD", "true").lower() in ("true", "1", "yes"):
        observer = start_file_watcher()

    # Optional: auto-launch Diode CLI to publish MCP over Diode (embedded), or rely on container Diode
    diode_started = False
    config = load_config()
    auto_start_diode = config.get("auto-start-diode", False)
    diode_client_mode = resolve_diode_client_mode()
    if auto_start_diode and diode_client_mode == "container":
        logger.info(
            "Diode: DIODE_CLIENT=container — not starting embedded Diode CLI "
            "(publish via container/sidecar; set auto-start-diode false if unused)"
        )
        print(
            "   Diode: DIODE_CLIENT=container (embedded Diode not started)",
            file=sys.stderr,
        )
    elif auto_start_diode:
        try:
            from exosense_mcp.diode_manager import set_publish_port, start_diode_cli, cleanup_diode
            set_publish_port(PORT)
            if start_diode_cli():
                diode_started = True
                atexit.register(cleanup_diode)
            else:
                logger.warning("Diode auto-start failed; MCP server will run locally only.")
        except Exception as e:
            logger.warning("Could not start Diode client: %s. MCP server will run locally only.", e)

    app = create_app()
    logger.info("=" * 80)
    logger.info("🚀 STARTING EXOSENSE MCP SERVER")
    logger.info("=" * 80)
    logger.info(f"📍 Server URL: http://{LISTEN_HOST}:{PORT}/mcp")
    logger.info(f"📍 Health check: http://{LISTEN_HOST}:{PORT}/health")
    logger.info(f"📍 Auth discovery: http://{LISTEN_HOST}:{PORT}/.well-known/mcp-authentication")
    logger.info(f"📍 Auth discovery: http://{LISTEN_HOST}:{PORT}/.well-known/mcp-authentication")
    logger.info(f"🔧 Tools loaded: {len(TOOLS)}")
    if TOOLS:
        logger.info(f"   Tool names: {', '.join(TOOLS.keys())}")
    logger.info(f"📊 Log level: {LOG_LEVEL}")
    logger.info(f"🌐 HTTP_STREAMING mode: {HTTP_STREAMING or 'Client Auth'}")
    if EXOSENSE_AUTH_TOKEN and EXOSENSE_ORIGIN:
        logger.info("🔑 Hybrid auth mode: Headers first, .env fallback enabled")
    else:
        logger.info("🔑 Auth mode: Client-provided only (no .env fallback)")
    if observer:
        logger.info("🔄 Hot-reload: ENABLED (set HOT_RELOAD=false to disable)")
    logger.info("=" * 80)
    logger.info("👂 Listening for connections...")
    logger.info("=" * 80)
    print(f"\n🚀 Starting ExoSense MCP server in HTTP streaming mode on port {PORT}...", file=sys.stderr)
    print(f"✅ ExoSense MCP server started (HTTP mode on port {PORT})", file=sys.stderr)
    print(f"   Endpoint: http://localhost:{PORT}/mcp", file=sys.stderr)
    print(f"   Health: http://localhost:{PORT}/health", file=sys.stderr)
    print(f"   Tools loaded: {len(TOOLS)}", file=sys.stderr)
    if observer:
        print(f"   Hot-reload: ENABLED", file=sys.stderr)
    
    try:
        web.run_app(app, host=LISTEN_HOST, port=PORT)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down server...")
    finally:
        if diode_started:
            try:
                from exosense_mcp.diode_manager import cleanup_diode
                cleanup_diode()
            except Exception as e:
                logger.warning("Error shutting down Diode client: %s", e)
        stop_file_watcher(observer)


if __name__ == "__main__":
    main()
