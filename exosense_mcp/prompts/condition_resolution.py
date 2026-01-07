"""Condition resolution prompt"""


async def load_condition_resolution(args: dict) -> dict:
    """Load condition resolution prompt"""
    asset_uuid = args.get("asset_uuid", "")
    condition_key = args.get("condition_key", "")
    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"I need help resolving a condition on asset {asset_uuid} with condition key {condition_key}. Please help me gather all relevant information and provide resolution guidance.",
                },
            },
            {
                "role": "assistant",
                "content": {
                    "type": "text",
                    "text": "I'll help you resolve this condition systematically. Let me start by gathering the current condition information and then build a comprehensive resolution strategy.",
                },
            },
        ],
    }


condition_resolution = {
    "name": "condition-resolution",
    "description": "Resolve (or close) conditions based on input",
    "arguments": [
        {
            "name": "asset_uuid",
            "description": "The UUID of the asset that has a condition that we will try to resolve (close)",
            "required": True,
        },
        {
            "name": "condition_key",
            "description": "The key of the condition on the asset to resolve (close)",
            "required": True,
        },
    ],
    "load": load_condition_resolution,
}

