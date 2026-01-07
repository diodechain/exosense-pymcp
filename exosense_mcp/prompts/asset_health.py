"""Asset health prompt"""


async def load_asset_health(args: dict) -> dict:
    """Load asset health prompt"""
    asset = args.get("asset", "")
    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"I need to check the health of asset {asset}. Please gather the latest status, data, and event logs for this asset. When fetching the logs only get 10 at a time.",
                },
            },
            {
                "role": "assistant",
                "content": {
                    "type": "text",
                    "text": f'I'll help you check the health of asset "{asset}". Let me start by locating the asset and then gather its health information.\n\nFirst, I need to determine if "{asset}" is a UUID or an asset name:\n- If it's a UUID (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx), I can directly query the asset\n- If it's an asset name, I'll need to search for it first\n\nLet me begin by searching for the asset to get its details and UUID.',
                },
            },
        ],
    }


asset_health = {
    "name": "asset-health",
    "description": "Get asset health information by reviewing the asset status, latest data, and event logs.",
    "arguments": [
        {
            "name": "asset",
            "description": "The UUID or name of the asset to retrieve health information for.",
            "required": True,
        }
    ],
    "load": load_asset_health,
}

