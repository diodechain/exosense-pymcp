# Pipeline Authentication Guide

This guide explains how to configure authentication for pipelines that want to use their own ExoSense credentials instead of the server's default `.env` credentials.

## Auto-Discovery

The MCP server supports **authentication discovery** using industry-standard patterns, allowing pipelines to automatically detect what authentication is required.

### 1. MCP Initialize Response (Recommended)

The `initialize` method response includes authentication capabilities in the `capabilities.authentication` field:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {},
      "authentication": {
        "required": false,
        "methods": [
          {
            "type": "automation_token",
            "header": "x-automation-token",
            "description": "ExoSense automation token",
            "required_headers": ["x-automation-token", "x-origin"]
          }
        ],
        "fallback_available": true,
        "fallback_description": "Server has default credentials configured in .env (optional)"
      }
    },
    "serverInfo": {...}
  }
}
```

**Pipeline Discovery Flow:**
```python
# 1. Call initialize (without auth headers to check capabilities)
response = requests.post(
    "http://mcp-server:64010/mcp",
    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pipeline", "version": "1.0.0"}
    }}
)

# 2. Check authentication capabilities
capabilities = response.json()["result"]["capabilities"]
auth_info = capabilities.get("authentication", {})

# 3. Determine if auth is needed
if auth_info.get("required", False) or not auth_info.get("fallback_available", False):
    # Auth is required - use pipeline credentials
    # Use auth_info["methods"] to see supported methods
    headers = {
        "x-automation-token": os.getenv("EXOSENSE_AUTOMATION_TOKEN"),
        "x-origin": os.getenv("EXOSENSE_ORIGIN")
    }
else:
    # Auth is optional - can use server default or provide own
    headers = {}  # Or provide your own credentials to override
```

### 2. Well-Known Endpoint (Industry Standard)

The server also exposes authentication metadata at a standard `.well-known` endpoint:

```bash
GET /.well-known/mcp-authentication
```

**Response:**
```json
{
  "authentication": {
    "required": false,
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
      }
    ],
    "fallback_available": true,
    "fallback_description": "..."
  },
  "server": {
    "name": "exosense-mcp-server",
    "version": "1.0.0",
    "protocol": "MCP",
    "protocolVersion": "2024-11-05"
  }
}
```

**Pipeline Discovery Flow:**
```python
# Query discovery endpoint before connecting
discovery_response = requests.get("http://mcp-server:64010/.well-known/mcp-authentication")
auth_info = discovery_response.json()["authentication"]

# Check if auth is required
if auth_info["required"] or not auth_info["fallback_available"]:
    # Must provide credentials
    headers = {
        "x-automation-token": os.getenv("EXOSENSE_AUTOMATION_TOKEN"),
        "x-origin": os.getenv("EXOSENSE_ORIGIN")
    }
else:
    # Optional - can use server default
    headers = {}  # Or provide your own to override
```

## Overview

The ExoSense MCP server supports **hybrid authentication**:
- **Priority 1**: Client-provided headers (pipeline credentials)
- **Priority 2**: Server `.env` fallback (IT-managed default)

If your pipeline provides authentication headers, the server will use those credentials. If not, it falls back to the server's `.env` configuration.

## Authentication Methods

The server supports three authentication methods via HTTP headers:

### 1. Automation Token (Recommended for Pipelines)

**Headers:**
```
x-automation-token: <your-automation-token>
x-origin: <your-exosense-origin>
```

**Example:**
```
x-automation-token: abc123xyz789
x-origin: https://your-instance.exosense.com
```

### 2. Authorization Header (Automation Token)

**Headers:**
```
Authorization: Automation <your-automation-token>
origin: <your-exosense-origin>
```

**Example:**
```
Authorization: Automation abc123xyz789
origin: https://your-instance.exosense.com
```

### 3. OAuth Bearer Token

**Headers:**
```
Authorization: Bearer <your-oauth-access-token>
origin: <your-exosense-origin>
```

**Example:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
origin: https://your-instance.exosense.com
```

## Integration Examples

### cURL Example

```bash
# Initialize session with authentication
curl -X POST http://localhost:64010/mcp \
  -H "Content-Type: application/json" \
  -H "x-automation-token: YOUR_AUTOMATION_TOKEN" \
  -H "x-origin: https://your-instance.exosense.com" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "my-pipeline",
        "version": "1.0.0"
      }
    }
  }'

# Use the session ID from the response for subsequent calls
SESSION_ID="<session-id-from-initialize-response>"

# Call a tool
curl -X POST http://localhost:64010/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "exosense-get-asset-statuses",
      "arguments": {}
    }
  }'
```

### Python Example

```python
import requests
import os

# Configuration
MCP_SERVER_URL = "http://localhost:64010/mcp"
AUTOMATION_TOKEN = os.getenv("EXOSENSE_AUTOMATION_TOKEN")
EXOSENSE_ORIGIN = os.getenv("EXOSENSE_ORIGIN")

# Headers for authentication
headers = {
    "Content-Type": "application/json",
    "x-automation-token": AUTOMATION_TOKEN,
    "x-origin": EXOSENSE_ORIGIN,
}

# Initialize session
init_response = requests.post(
    f"{MCP_SERVER_URL}",
    headers=headers,
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "my-pipeline",
                "version": "1.0.0"
            }
        }
    }
)

# Extract session ID from response
session_id = init_response.headers.get("Mcp-Session-Id")
if not session_id:
    # Try to get from response body
    result = init_response.json()
    # Session ID is typically in the response headers

# Use session ID for tool calls
tool_headers = {
    "Content-Type": "application/json",
    "Mcp-Session-Id": session_id,
}

# Call a tool
tool_response = requests.post(
    f"{MCP_SERVER_URL}",
    headers=tool_headers,
    json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "exosense-get-asset-statuses",
            "arguments": {}
        }
    }
)

print(tool_response.json())
```

### GitHub Actions Example

```yaml
name: ExoSense Asset Health Check

on:
  schedule:
    - cron: '0 * * * *'  # Every hour
  workflow_dispatch:

jobs:
  check-assets:
    runs-on: ubuntu-latest
    steps:
      - name: Check Asset Health
        env:
          EXOSENSE_AUTOMATION_TOKEN: ${{ secrets.EXOSENSE_AUTOMATION_TOKEN }}
          EXOSENSE_ORIGIN: ${{ secrets.EXOSENSE_ORIGIN }}
          MCP_SERVER_URL: http://your-mcp-server:64010/mcp
        run: |
          # Initialize session
          INIT_RESPONSE=$(curl -s -X POST "$MCP_SERVER_URL" \
            -H "Content-Type: application/json" \
            -H "x-automation-token: $EXOSENSE_AUTOMATION_TOKEN" \
            -H "x-origin: $EXOSENSE_ORIGIN" \
            -d '{
              "jsonrpc": "2.0",
              "id": 1,
              "method": "initialize",
              "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "github-actions", "version": "1.0.0"}
              }
            }')
          
          # Extract session ID (you may need to parse the response)
          SESSION_ID=$(echo "$INIT_RESPONSE" | jq -r '.result.sessionId // empty')
          
          # Call tool
          curl -X POST "$MCP_SERVER_URL" \
            -H "Content-Type: application/json" \
            -H "Mcp-Session-Id: $SESSION_ID" \
            -d '{
              "jsonrpc": "2.0",
              "id": 2,
              "method": "tools/call",
              "params": {
                "name": "exosense-get-asset-statuses",
                "arguments": {}
              }
            }'
```

### GitLab CI Example

```yaml
check-assets:
  script:
    - |
      # Initialize session with pipeline credentials
      INIT_RESPONSE=$(curl -s -X POST "$MCP_SERVER_URL" \
        -H "Content-Type: application/json" \
        -H "x-automation-token: $EXOSENSE_AUTOMATION_TOKEN" \
        -H "x-origin: $EXOSENSE_ORIGIN" \
        -d '{
          "jsonrpc": "2.0",
          "id": 1,
          "method": "initialize",
          "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "gitlab-ci", "version": "1.0.0"}
          }
        }')
      
      # Extract session ID
      SESSION_ID=$(echo "$INIT_RESPONSE" | jq -r '.result.sessionId // empty')
      
      # Call tool
      curl -X POST "$MCP_SERVER_URL" \
        -H "Content-Type: application/json" \
        -H "Mcp-Session-Id: $SESSION_ID" \
        -d '{
          "jsonrpc": "2.0",
          "id": 2,
          "method": "tools/call",
          "params": {
            "name": "exosense-get-asset-statuses",
            "arguments": {}
          }
        }'
  variables:
    MCP_SERVER_URL: "http://your-mcp-server:64010/mcp"
  secrets:
    EXOSENSE_AUTOMATION_TOKEN:
      vault: exosense/automation-token
    EXOSENSE_ORIGIN:
      vault: exosense/origin
```

### Node.js/TypeScript Example

```typescript
import axios from 'axios';

const MCP_SERVER_URL = process.env.MCP_SERVER_URL || 'http://localhost:64010/mcp';
const AUTOMATION_TOKEN = process.env.EXOSENSE_AUTOMATION_TOKEN!;
const EXOSENSE_ORIGIN = process.env.EXOSENSE_ORIGIN!;

async function initializeSession(): Promise<string> {
  const response = await axios.post(
    MCP_SERVER_URL,
    {
      jsonrpc: '2.0',
      id: 1,
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: {
          name: 'my-pipeline',
          version: '1.0.0',
        },
      },
    },
    {
      headers: {
        'Content-Type': 'application/json',
        'x-automation-token': AUTOMATION_TOKEN,
        'x-origin': EXOSENSE_ORIGIN,
      },
    }
  );

  // Session ID is in the response header
  const sessionId = response.headers['mcp-session-id'] || response.headers['Mcp-Session-Id'];
  if (!sessionId) {
    throw new Error('No session ID received');
  }

  return sessionId;
}

async function callTool(sessionId: string, toolName: string, arguments: any) {
  const response = await axios.post(
    MCP_SERVER_URL,
    {
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: arguments,
      },
    },
    {
      headers: {
        'Content-Type': 'application/json',
        'Mcp-Session-Id': sessionId,
      },
    }
  );

  return response.data;
}

// Usage
async function main() {
  try {
    const sessionId = await initializeSession();
    const result = await callTool(sessionId, 'exosense-get-asset-statuses', {});
    console.log('Asset health:', result);
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  }
}

main();
```

## Environment Variables

Store your credentials securely as environment variables or secrets:

**Required:**
- `EXOSENSE_AUTOMATION_TOKEN`: Your ExoSense automation token
- `EXOSENSE_ORIGIN`: Your ExoSense instance origin (e.g., `https://your-instance.exosense.com`)

**Optional:**
- `MCP_SERVER_URL`: MCP server endpoint (default: `http://localhost:64010/mcp`)

## Security Best Practices

1. **Never commit credentials to version control**
   - Use secrets management (GitHub Secrets, GitLab CI/CD Variables, etc.)
   - Use environment variables in your pipeline configuration

2. **Use HTTPS for MCP server communication**
   - If the MCP server is exposed over the internet, use HTTPS
   - Credentials are sent in headers, so HTTPS is essential

3. **Rotate credentials regularly**
   - Set up token rotation policies
   - Monitor for unauthorized access

4. **Use least-privilege tokens**
   - Create automation tokens with only the permissions needed
   - Don't use admin tokens for pipeline automation

## Session Management

1. **Initialize once per pipeline run**
   - Call `initialize` at the start of your pipeline
   - Store the session ID for subsequent tool calls

2. **Session ID is in response headers**
   - Look for `Mcp-Session-Id` or `mcp-session-id` header
   - Include it in all subsequent requests

3. **Sessions are per-connection**
   - Each pipeline run gets a new session
   - Sessions are not shared between pipeline runs

## Troubleshooting

### "No authentication available"
- **Cause**: Neither headers nor `.env` credentials are available
- **Solution**: Ensure you're sending authentication headers with the `initialize` request

### "Authentication failed"
- **Cause**: Invalid token or origin
- **Solution**: Verify your `EXOSENSE_AUTOMATION_TOKEN` and `EXOSENSE_ORIGIN` are correct

### "Invalid or missing session"
- **Cause**: Session ID not provided or expired
- **Solution**: Ensure you're including the `Mcp-Session-Id` header from the `initialize` response

### "Unknown tool"
- **Cause**: Tool name mismatch or tool not loaded
- **Solution**: Verify the tool name matches exactly (e.g., `exosense-get-asset-statuses`)

## Quick Reference

**Authentication Headers (choose one method):**
```bash
# Method 1: x-automation-token (recommended)
x-automation-token: <token>
x-origin: <origin>

# Method 2: Authorization header
Authorization: Automation <token>
origin: <origin>

# Method 3: OAuth
Authorization: Bearer <oauth-token>
origin: <origin>
```

**Session Header (for all tool calls):**
```bash
Mcp-Session-Id: <session-id-from-initialize>
```

**MCP Endpoints:**
- Initialize: `POST /mcp` (method: `initialize`)
- List Tools: `POST /mcp` (method: `tools/list`)
- Call Tool: `POST /mcp` (method: `tools/call`)
- Health Check: `GET /health`
