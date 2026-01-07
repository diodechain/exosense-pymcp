"""Assist write IIMF prompt"""


async def load_help_write_iimf(args: dict) -> dict:
    """Load help write IIMF prompt"""
    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": "I need help writing an Inline Insight Module Function (IIMF). Please guide me through the process.",
                },
            },
        ],
    }


help_write_iimf = {
    "name": "assist-write-iimf",
    "description": "Assist in writing Inline Insight Module Functions (IIMF)",
    "arguments": [],
    "load": load_help_write_iimf,
}

