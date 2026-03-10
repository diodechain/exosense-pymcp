"""Get high-level statistics about a specific asset"""

import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator, ValidationError
from ..graphql.assets import get_asset_details
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response

UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class AssetDetailsParams(BaseModel):
    """Parameters for asset details tool"""

    asset_id: Optional[str] = Field(
        None, description="UUID of the one specific asset the user asked about (do not use for counts or discovery)"
    )
    asset_name: Optional[str] = Field(
        None, description="Exact name of the one specific asset the user asked about (do not use for counts or discovery)"
    )
    # Booleans with defaults: allow None and fall back to defaults.
    # NOTE: include_data defaults to False to keep responses compact unless
    # the client explicitly asks for full signal data.
    include_data: Optional[bool] = Field(
        False,
        description="Include latest signal data and full configuration (default: false for compact responses)",
    )
    extra_rule_data: Optional[bool] = Field(
        False,
        description="Get additional rule data (up to 5 rule entries instead of 1 per rule)",
    )

    @model_validator(mode="after")
    def validate_at_least_one(self):
        if not self.asset_id and not self.asset_name:
            raise ValueError("Either asset_id or asset_name must be provided")
        if self.asset_id and not UUID_REGEX.match(self.asset_id):
            raise ValueError("asset_id must be a valid UUID")
        return self


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get high-level statistics about a specific asset"""
    try:
        # Validate arguments with Pydantic
        try:
            args = AssetDetailsParams(**arguments)
            # Ensure boolean flags fall back to defaults when None is passed
            if args.include_data is None:
                args.include_data = False
            if args.extra_rule_data is None:
                args.extra_rule_data = False
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Always fetch latest data point for signals, even if include_data is False
        # This gives us the latest value/timestamp without the full configuration
        options: dict = {
            "includeData": True,  # Always get latest data point
            "extraRuleData": args.extra_rule_data,
        }

        query = get_asset_details(
            asset_id=args.asset_id,
            asset_name=args.asset_name,
            options=options,
        )
        context.log.debug("Executing query to get asset details")
        result = await client.query(query)

        assets = result.get("assets", [])
        if not assets:
            return format_error_response(Exception("Asset not found"))

        asset = assets[0]

        # Extract latest data points from signals
        signals = asset.get("signals", []) or []
        latest_data_points = []
        
        for signal in signals:
            signal_name = signal.get("name") or signal.get("tag") or "Unknown"
            # Check both signal.data and signal.channel.data for latest value
            signal_data = signal.get("data", [])
            channel_data = signal.get("channel", {}).get("data", []) if signal.get("channel") else []
            
            # Prefer channel data if available, otherwise use signal data
            latest_data = channel_data[0] if channel_data else (signal_data[0] if signal_data else None)
            
            if latest_data:
                latest_data_points.append({
                    "signal_name": signal_name,
                    "signal_id": signal.get("id"),
                    "value": latest_data.get("value"),
                    "value_string": latest_data.get("valueString"),
                    "timestamp": latest_data.get("timestamp"),
                    "received_time": latest_data.get("receivedTime"),
                })
        
        # Sort by timestamp descending to get the most recent first
        latest_data_points.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        
        # Get the overall latest data point
        overall_latest = latest_data_points[0] if latest_data_points else None

        # Return a compact summary with structured ids for LLMs (asset_id, asset_name, parent_group).
        parent = asset.get("parent")
        parent_group = None
        if parent:
            parent_group = {"group_id": parent.get("id"), "group_name": parent.get("name")}
        summary = {
            "asset_id": asset.get("id"),
            "asset_name": asset.get("name") or "Unnamed Asset",
            "description": asset.get("description") or "",
            "locked": asset.get("locked"),
            "parent_group": parent_group,
            "template": asset.get("template")
            and {
                "id": asset["template"].get("id"),
                "name": asset["template"].get("name"),
            },
            # High-level counts instead of full arrays to avoid huge payloads
            "signal_count": len(signals),
            "rule_count": len(asset.get("rules", [])) if asset.get("rules") else 0,
            "action_count": len(asset.get("actions", []))
            if asset.get("actions")
            else 0,
            # Latest data point information
            "latest_data_point": overall_latest,
            "signals_with_data": len(latest_data_points),
        }

        return format_success_response(
            summary, "Successfully retrieved compact asset details summary"
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(AssetDetailsParams)
TOOL_METADATA = {
    "name": "exosense-get-asset-details",
    "description": "ONLY for detailed info on ONE specific asset that the user has already identified by name or ID. Use when the user asks about 'latest data for [asset name]', 'current readings for X', 'sensor values for asset Y', or 'details of this asset'. Requires asset_id (UUID) or asset_name (exact match). NEVER use for: asset counts, 'how many assets', 'how many assets do I have', overview, health summary, or listing assets. For counts/overview/health summary always use exosense-asset-health-summary instead. For status of many assets use exosense-get-asset-statuses.",
    "inputSchema": schema
}
