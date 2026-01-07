#!/bin/bash
# Test script to verify MCP server is running and tools are loaded

echo "1. Testing initialize..."
INIT_RESPONSE=$(curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -i \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    }
  }')

# Extract session ID from headers
SESSION_ID=$(echo "$INIT_RESPONSE" | grep -i "mcp-session-id" | cut -d' ' -f2 | tr -d '\r\n')

if [ -z "$SESSION_ID" ]; then
  echo "❌ Failed to get session ID from initialize response"
  echo "Response:"
  echo "$INIT_RESPONSE"
  exit 1
fi

echo "✅ Initialize successful"
echo "   Session ID: $SESSION_ID"
echo ""

echo "2. Testing tools/list..."
TOOLS_RESPONSE=$(curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }')

echo "$TOOLS_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$TOOLS_RESPONSE"

# Count tools in response
TOOL_COUNT=$(echo "$TOOLS_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('result', {}).get('tools', [])))" 2>/dev/null || echo "0")

echo ""
if [ "$TOOL_COUNT" -gt "0" ]; then
  echo "✅ Found $TOOL_COUNT tools loaded"
else
  echo "⚠️  No tools found - check server logs for loading errors"
fi

