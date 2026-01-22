# ExoSense MCP Server (Python)

A Model Context Protocol (MCP) server for interacting with the ExoSense platform using GraphQL, implemented in Python.

## Overview

This MCP server provides tools to interact with ExoSense devices, sensors, groups, assets, and data through a standardized GraphQL interface. It features a modular architecture with session-based authentication and supports comprehensive IoT device management operations.

The server is implemented using `aiohttp` and follows the JSON-RPC 2.0 protocol for MCP communication. Tools are loaded dynamically from a configuration file, making it easy to add or modify tools without changing the core server code.

## Features

- **GraphQL API**: All interactions with ExoSense use GraphQL for efficient data fetching
- **Session-based Authentication**: Token/OAuth authentication managed at the session level
- **Modular Tool Architecture**: 18 specialized tools for different ExoSense operations
- **Dynamic Tool Loading**: Tools are loaded from `config.yml` at startup
- **Type-Safe**: Full Python type hints with Pydantic validation
- **Pre-built Queries**: Common GraphQL queries and mutations included
- **Error Handling**: Comprehensive error handling and validation
- **HTTP Streaming**: Built on aiohttp with HTTP streaming support

## Installation

```bash
cd python
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install -e .
```

## Configuration

The server can be configured using environment variables. You can set them in one of two ways:

1. **Using a `.env` file** (recommended for local development):
   - Create a `.env` file in the `python/` directory
   - Add the following variables:
     ```
     EXOSENSE_API_URL=https://api.exosense.com
     EXOSENSE_ORIGIN=https://exosense.com
     EXOSENSE_AUTH_TOKEN=your-token-here
     PORT=8080
     HTTP_STREAMING=Private
     ```
   - The `.env` file is automatically loaded when the server starts

2. **Using system environment variables**:
   - Set environment variables directly in your shell or system configuration

### Environment Variables

- `EXOSENSE_API_URL`: GraphQL endpoint for ExoSense (default: `https://api.exosense.com`)
- `EXOSENSE_ORIGIN`: Host name of the solution being referenced (default: `https://exosense.com`)
- `EXOSENSE_AUTH_TOKEN`: Default authentication token (optional, required for private mode)
- `PORT`: Server port (default: `8080`)
- `HTTP_STREAMING`: Set to `"Private"` for backward compatibility (optional, no longer required for auth mode)

### Hybrid Authentication Mode

The server uses a **hybrid authentication approach** that supports both single-tenant and multi-tenant scenarios:

1. **Client-Provided Auth (Multi-Tenant)**: If a client provides authentication headers:
   - The server will use the client's credentials from headers
   - Supports `x-automation-token` + `x-origin` OR `Authorization: Automation <token>` + `origin`
   - Each client session can have different credentials
   - Perfect for SaaS platforms or multi-organization deployments

2. **Environment Fallback (Single-Tenant Default)**: If no auth headers are provided:
   - The server falls back to `EXOSENSE_ORIGIN` and `EXOSENSE_AUTH_TOKEN` from `.env`
   - IT can set a default API key without exposing it to clients
   - Clients can still override by providing their own headers
   - Perfect for internal tools or when you want a default tenant

**Priority**: Headers (client-provided) → `.env` variables (IT-provided default)

This allows IT to configure a default API key in `.env` for convenience, while still allowing pipelines and clients to use their own credentials when needed.

## Usage

### Starting the Server

```bash
python3 -m exosense_mcp.server
```

Or using the installed script:

```bash
exosense-mcp-server
```

The server will:
1. Test the connection to ExoSense (if credentials are provided)
2. Load all tools from `config.yml`
3. Start the HTTP server on the configured port (default: 8080)
4. Listen for MCP requests at `http://localhost:8080/mcp`

### Pipeline Authentication

For pipelines that want to use their own ExoSense credentials (instead of the server's `.env` default), see **[PIPELINE_AUTHENTICATION.md](PIPELINE_AUTHENTICATION.md)** for detailed integration examples including:
- cURL examples
- Python/Node.js code samples
- GitHub Actions and GitLab CI configurations
- Security best practices

### MCP Client Configuration

To connect an MCP client to the ExoSense MCP server, configure your client with:

```json
{
  "mcpServers": {
    "exosense": {
      "type": "http",
      "url": "http://localhost:8080/mcp",
      "headers": {
        "x-automation-token": "<YOUR_EXOSENSE_API_TOKEN>",
        "origin": "https://your-exosense-instance.com"
      }
    }
  }
}
```

**Note**: If `HTTP_STREAMING=Private` is set in the server's `.env` file, headers are optional as the server will use `.env` authentication.

## Development

### Project Structure

```
python/
├── exosense_mcp/
│   ├── __init__.py
│   ├── server.py              # Main MCP server (aiohttp-based)
│   ├── auth.py                # Authentication handler
│   ├── exosense_client.py     # GraphQL client for ExoSense
│   ├── utils.py               # Utility functions
│   ├── tools/                 # Modular tool architecture
│   │   ├── __init__.py
│   │   ├── types.py           # Tool context and types
│   │   ├── _helpers.py        # Helper functions for tools
│   │   └── *.py               # Individual tool modules (18 tools)
│   ├── graphql/               # GraphQL query builders
│   │   ├── __init__.py
│   │   ├── assets.py
│   │   ├── groups.py
│   │   ├── devices_products.py
│   │   ├── insight_modules.py
│   │   ├── logs.py
│   │   ├── reports.py
│   │   ├── work_instructions.py
│   │   └── condition_policies.py
│   ├── types/                 # Type definitions
│   │   ├── __init__.py
│   │   ├── auth.py            # Authentication types
│   │   └── graphql.py          # GraphQL types
│   ├── resources/             # MCP resources (documentation links)
│   │   └── index.py
│   └── prompts/               # MCP prompts
│       └── *.py
├── config.yml                 # Tool configuration (lists all tools)
├── pyproject.toml
├── requirements.txt
└── README.md
```

### Tool Architecture

Each tool follows a consistent pattern:

1. **Pydantic Model**: Defines the tool's parameters with validation
2. **Execute Function**: `async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]`
3. **TOOL_METADATA**: Dictionary containing tool name, description, and JSON schema

Example tool structure:

```python
from typing import Dict, Any
from pydantic import BaseModel, Field, ValidationError
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

class MyToolParams(BaseModel):
    param1: str = Field(..., description="Description of param1")
    param2: int = Field(10, ge=1, description="Description of param2")

async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    try:
        # Validate arguments
        try:
            args = MyToolParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))
        
        # Get authenticated client
        auth = context.session.get("authorization") if context.session else None
        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)
        
        # Tool logic here
        result = await client.query(...)
        
        return format_success_response(result, "Success message")
    except Exception as error:
        return format_error_response(error)

# Tool metadata
schema = pydantic_to_json_schema(MyToolParams)
TOOL_METADATA = {
    "name": "exosense-my-tool",
    "description": "Description of what the tool does",
    "inputSchema": schema
}
```

### Adding New Tools

To add a new tool:

1. **Create a new tool file** in `exosense_mcp/tools/` (e.g., `my_new_tool.py`)
2. **Follow the tool architecture pattern** above
3. **Add the tool to `config.yml`**:
   ```yaml
   tools:
     - file: exosense_mcp/tools/my_new_tool.py
       name: exosense-my-new-tool
   ```
4. **Restart the server** - tools are loaded dynamically at startup

## Available Tools

The server provides 18 specialized MCP tools for ExoSense operations:

1. **`exosense-current-user`** - Get current user information
2. **`exosense-get-root-group`** - Get root group information
3. **`exosense-get-groups`** - Query groups with filtering and include options
4. **`exosense-get-products`** - Get all IoT Connectors (products)
5. **`exosense-get-devices`** - Query devices with filtering and include options
6. **`exosense-get-assets`** - Query assets with filtering and include options (returns summary only)
7. **`exosense-get-asset-details`** - Get high-level statistics for a specific asset by ID or name
8. **`exosense-find-asset`** - Find assets by fuzzy name matching (e.g., "my battery" → "Battery Bank")
9. **`exosense-get-asset-statuses`** - Get status information for specific assets
10. **`exosense-get-insight-modules`** - Get all available internal insight modules
11. **`exosense-get-insight-module`** - Get detailed information about a specific insight module
12. **`exosense-get-asset-historical-data`** - Generate and retrieve historical data reports
13. **`exosense-get-work-instructions`** - Get work instructions
14. **`exosense-get-conditions`** - Get conditions
15. **`exosense-get-condition-comments`** - Get condition comments
16. **`exosense-get-event-logs`** - Get event logs

All tools use session-based authentication and provide comprehensive error handling.

## Dependencies

- `pydantic>=2.0.0` - Data validation and settings management
- `httpx>=0.25.0` - Async HTTP client for GraphQL requests
- `python-dotenv>=1.0.0` - Environment variable management
- `aiohttp>=3.9.0` - Async HTTP server for MCP protocol
- `pyyaml>=6.0.0` - YAML configuration file parsing

## Testing

The server includes connection testing on startup. When you start the server, it will:

1. Test the connection to ExoSense (if credentials are provided)
2. Display connection status and configuration
3. Load and register all tools from `config.yml`
4. Start the HTTP server

## Contributing

1. Follow the existing modular tool architecture
2. Create new tools in separate files under `exosense_mcp/tools/`
3. Use Pydantic models for parameter validation
4. Add proper Python type hints for all new functionality
5. Include comprehensive error handling using `format_error_response`
6. Add tools to `config.yml` for dynamic loading
7. Follow the tool pattern: Pydantic model + `execute()` function + `TOOL_METADATA`

## License

MIT
