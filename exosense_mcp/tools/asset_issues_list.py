"""List assets with issues (and optional filters). Use for 'What are the specific issues?', 'Which assets have problems?'."""

from typing import Any, Dict, Optional
from pydantic import Field, ValidationError
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response
from . import asset_statuses


class AssetIssuesListParams(McpToolParams):
    filter_category: Optional[str] = Field(
        None,
        description="Only issues in this category (e.g. 'timeout', 'default'). Omit for all.",
    )
    filter_level: Optional[str] = Field(
        None,
        description="Only issues at this level (e.g. 'critical', 'warning'). Use with filter_category.",
    )
    max_assets: int = Field(100, ge=1, le=500, description="Max assets to check (default 100)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Return only assets-with-issues list and counts; no healthy/offline lists."""
    try:
        args = AssetIssuesListParams(**arguments)
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    minimal_args = {
        "include_details": True,
        "max_assets": args.max_assets,
        "extra_status_data": False,
        "filter_category": args.filter_category,
        "filter_level": args.filter_level,
    }
    result = await asset_statuses.execute(minimal_args, context)
    content = result.get("content", [])
    if not content or content[0].get("type") != "text":
        return result
    import json
    try:
        data = json.loads(content[0]["text"])
        if not data.get("success"):
            return result
        payload = data.get("data", {})
        out = {
            "total_assets_checked": payload.get("total_assets_checked", 0),
            "assets_with_issues": payload.get("assets_with_issues", 0),
            "assets_with_issues_details": payload.get("assets_with_issues_details", []),
            "problem_categories": payload.get("problem_categories"),
        }
        if args.filter_category or args.filter_level:
            out["filter_applied"] = {"category": args.filter_category, "level": args.filter_level}
        return format_success_response(out, data.get("message", "Issues list."))
    except (json.JSONDecodeError, KeyError, TypeError):
        return result


schema = pydantic_to_json_schema(AssetIssuesListParams)
TOOL_METADATA = {
    "name": "exosense-asset-issues-list",
    "description": "Use for: 'What are the specific issues?', 'Which assets have problems?', 'How long has [asset/group] had issues?' - returns assets_with_issues_details including last_heard (ISO timestamp) per asset so you can compute or describe duration. List assets with issues, names of assets with critical timeouts. Optionally set filter_category and filter_level. For overview counts use exosense-asset-health-summary; for full status use exosense-get-asset-statuses.",
    "inputSchema": schema,
}
