"""Asset health summary only (counts). Use for 'How many assets?', 'Overview', 'Health summary'."""

from typing import Dict, Any
from pydantic import BaseModel, Field, ValidationError
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response
from . import asset_statuses


class AssetHealthSummaryParams(BaseModel):
    max_assets: int = Field(100, ge=1, le=500, description="Max assets to check (default 100)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Return only summary counts; no asset lists or details."""
    try:
        args = AssetHealthSummaryParams(**arguments)
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    minimal_args = {
        "include_details": False,
        "max_assets": args.max_assets,
        "extra_status_data": False,
        "filter_category": None,
        "filter_level": None,
    }
    result = await asset_statuses.execute(minimal_args, context)
    # result is MCP format with content[0].text = JSON string
    content = result.get("content", [])
    if not content or content[0].get("type") != "text":
        return result
    import json
    try:
        data = json.loads(content[0]["text"])
        if not data.get("success"):
            return result
        payload = data.get("data", {})
        summary = {
            "total_assets_checked": payload.get("total_assets_checked", 0),
            "assets_healthy": payload.get("assets_healthy", 0),
            "assets_with_issues": payload.get("assets_with_issues", 0),
            "assets_offline": payload.get("assets_offline", 0),
            "problem_categories": payload.get("problem_categories"),
        }
        return format_success_response(summary, data.get("message", "Summary."))
    except (json.JSONDecodeError, KeyError, TypeError):
        return result


schema = pydantic_to_json_schema(AssetHealthSummaryParams)
TOOL_METADATA = {
    "name": "exosense-asset-health-summary",
    "description": "Call this for asset counts and overview. Use when the user asks: 'How many assets do I have?', 'How many assets?', 'Asset count', 'Overview', 'Health summary', 'How many are healthy/offline?'. Returns total_assets_checked, assets_healthy, assets_with_issues, assets_offline, problem_categories. Do NOT use exosense-get-asset-details for counts or overview—get-asset-details is only for one specific asset the user named. For listing which assets have issues use exosense-asset-issues-list.",
    "inputSchema": schema,
}
