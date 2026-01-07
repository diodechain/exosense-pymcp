"""Assist analyze historical data prompt"""


async def load_help_analyze_historical_data(args: dict) -> dict:
    """Load help analyze historical data prompt"""
    asset = args.get("asset", "")
    signal = args.get("signal", "")
    time_range = args.get("time_range", "")
    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": f"I have a specific signal dataset that requires advanced processing and filtering. Please help me work through the following steps:\n\n1. Identify the signal on the asset that needs processing.\n2. Data Retrieval - Use the get-asset-historical-data tool to fetch a sample of the signal data within the specified time range '{time_range}'.\n3. Data Analysis - Perform a comprehensive analysis of the retrieved data.\n\nAsset: {asset}\nSignal: {signal}\nTime Range: {time_range}",
                },
            },
        ],
    }


help_analyze_historical_data = {
    "name": "assist-analyzing-historical-data",
    "description": "Assist in analyzing historical data by providing insights and recommendations.",
    "arguments": [
        {
            "name": "asset",
            "description": "The UUID or name of the asset that has a signal that needs processing.",
            "required": True,
        },
        {
            "name": "signal",
            "description": "The name of the signal on the asset that requires processing or filtering.",
            "required": True,
        },
        {
            "name": "time_range",
            "description": "The time range for which the signal data needs to be processed (e.g., 'last 24 hours', 'last week').",
            "required": True,
        },
    ],
    "load": load_help_analyze_historical_data,
}

