"""Find assets by fuzzy name matching"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from ..graphql.assets import get_assets
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


def calculate_similarity(query: str, target: str) -> float:
    """Calculate similarity score between two strings using multiple heuristics"""
    if not target:
        return 0.0

    query_lower = query.lower().strip()
    target_lower = target.lower().strip()

    # Exact match
    if query_lower == target_lower:
        return 1.0

    # Substring match
    if query_lower in target_lower:
        ratio = len(query_lower) / len(target_lower)
        return 0.8 + (ratio * 0.2)

    # Word-based matching
    query_words = [w for w in query_lower.split() if w]
    target_words = [w for w in target_lower.split() if w]

    if query_words:
        matching_words = [
            qw
            for qw in query_words
            if any(tw in qw or qw in tw for tw in target_words)
        ]
        word_match_ratio = len(matching_words) / len(query_words) if query_words else 0

        if word_match_ratio == 1.0:
            return 0.6 + (0.2 * (len(matching_words) / max(len(query_words), len(target_words))))
        elif word_match_ratio > 0.5:
            return 0.4 + (0.2 * word_match_ratio)

    # Character-based similarity
    max_len = max(len(query_lower), len(target_lower))
    if max_len == 0:
        return 0

    matches = 0
    query_idx = 0
    for i in range(len(target_lower)):
        if query_idx < len(query_lower) and target_lower[i] == query_lower[query_idx]:
            matches += 1
            query_idx += 1

    char_similarity = matches / max_len
    return max(0.1, char_similarity * 0.3)


def _build_no_match_payload(query: str) -> Dict[str, Any]:
    """Payload when no assets match the main query."""
    return {
        "query": query,
        "matches": [],
        "count": 0,
        "message": "No assets found matching the query",
    }


async def _fallback_searches_by_word(
    client: Any,
    args: Any,
    options: dict,
    pagination: Any,
    context: ToolContext,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    When the main query has multiple words and returns no matches, search each word
    independently and return compact results so the LLM can suggest or use them.
    """
    words = [w.strip() for w in args.query.split() if w.strip()]
    if len(words) < 2:
        return None
    fallback: Dict[str, Dict[str, Any]] = {}
    limit_per_word = min(10, args.limit * 2)  # cap size
    for word in words:
        filters = {"text": word}
        query = get_assets(filters, options, pagination)
        result = await client.query(query)
        assets = result.get("assets", []) or []
        scored = []
        for asset in assets:
            name = asset.get("name") or "Unnamed Asset"
            sim = calculate_similarity(word, name)
            if sim >= args.min_similarity:
                scored.append({"asset": asset, "similarity": sim})
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        scored = scored[:limit_per_word]
        matches = [
            {"asset_id": a["asset"].get("id"), "asset_name": a["asset"].get("name") or ""}
            for a in scored
        ]
        if matches:
            fallback[word] = {"matches": matches, "count": len(matches)}
    return fallback if fallback else None


class FindAssetParams(BaseModel):
    """Parameters for find asset tool"""

    query: str = Field(..., min_length=1, description="Search query to find assets by name (e.g., 'my battery', 'battery bank')")
    limit: Optional[int] = Field(default=5, ge=1, le=20, description="Maximum number of matching assets to return (1-20, default: 5)")
    min_similarity: Optional[float] = Field(default=0.3, ge=0, le=1, description="Minimum similarity score threshold (0-1, default: 0.3)")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Find assets by fuzzy name matching"""
    try:
        # Validate arguments with Pydantic
        try:
            args = FindAssetParams(**arguments)
            # Ensure defaults are set if None values are provided
            if args.limit is None:
                args.limit = 5
            if args.min_similarity is None:
                args.min_similarity = 0.3
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Use text filter as a first pass to narrow down results
        filters: dict = {"text": args.query}
        options: dict = {
            "includeTemplates": False,
            "includeParent": False,
            "includeMeta": False,
            "includeLocation": False,
            "includeData": False,
            "extraRuleData": False,
        }
        pagination = Pagination(limit=100, offset=0)  # Get up to 100 assets for fuzzy matching

        query = get_assets(filters, options, pagination)
        context.log.debug("Executing query to find assets", {"query": args.query, "filters": filters, "pagination": pagination.model_dump()})
        result = await client.query(query)

        assets = result.get("assets", [])
        if not assets:
            # No hits: try each word independently so the LLM has alternatives (e.g. "circulation fan" -> "circulation", "fan")
            payload = _build_no_match_payload(args.query)
            fallback = await _fallback_searches_by_word(client, args, options, pagination, context)
            if fallback:
                payload["fallback_searches"] = fallback
                payload["message"] = "No assets found for the full query; search each word separately for alternatives."
            return format_success_response(
                payload,
                f'No assets found matching "{args.query}"' + ("; see fallback_searches for results by word." if fallback else ""),
            )

        # Calculate similarity scores for all assets
        assets_with_scores = []
        for asset in assets:
            asset_name = asset.get("name") or "Unnamed Asset"
            similarity = calculate_similarity(args.query, asset_name)

            if similarity >= args.min_similarity:
                assets_with_scores.append(
                    {
                        "asset": {
                            "id": asset.get("id"),
                            "name": asset_name,
                            "description": asset.get("description") or "",
                            "locked": asset.get("locked"),
                        },
                        "similarity": similarity,
                    }
                )

        # Sort by similarity descending and take top N
        assets_with_scores.sort(key=lambda x: x["similarity"], reverse=True)
        assets_with_scores = assets_with_scores[: args.limit]

        # If main query returned assets but none passed similarity, try fallback by word
        if not assets_with_scores:
            words = [w.strip() for w in args.query.split() if w.strip()]
            if len(words) >= 2:
                fallback = await _fallback_searches_by_word(client, args, options, pagination, context)
                if fallback:
                    payload = {
                        "query": args.query,
                        "matches": [],
                        "count": 0,
                        "min_similarity": args.min_similarity,
                        "message": "No assets matched the full query; search each word separately for alternatives.",
                        "fallback_searches": fallback,
                    }
                    return format_success_response(
                        payload,
                        f'No assets found matching "{args.query}"; see fallback_searches for results by word.',
                    )

        # Keep response under ~4k chars: use compact format (id + name only) when many matches
        max_full = 10
        compact = len(assets_with_scores) > max_full
        matches = []
        for item in assets_with_scores:
            a = item["asset"]
            if compact:
                matches.append({
                    "asset_id": a.get("id"),
                    "asset_name": a.get("name") or "",
                })
            else:
                matches.append({
                    "asset_id": a.get("id"),
                    "asset_name": a.get("name") or "",
                    "description": a.get("description") or "",
                    "locked": a.get("locked"),
                    "similarity_score": round(item["similarity"], 3),
                })

        payload = {
            "query": args.query,
            "matches": matches,
            "count": len(matches),
            "min_similarity": args.min_similarity,
        }
        if compact:
            payload["response_compact"] = True  # Only id/name to stay under size limits

        return format_success_response(
            payload,
            f'Found {len(assets_with_scores)} asset(s) matching "{args.query}"',
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(FindAssetParams)
TOOL_METADATA = {
    "name": "exosense-find-asset",
    "description": "Find assets by type, category, or name. CALL THIS whenever the user asks about assets, devices, or infrastructure by kind (e.g. 'circulation fans', 'pumps', 'sensors'). Use the asset type/category as the query (e.g. 'circulation fan'). When the full query returns no matches, the tool may return fallback_searches: results for each word separately (e.g. 'circulation' and 'fan') — use those asset_ids to answer the user (e.g. 'No exact match; found N assets for \"circulation\" (Circulation Group 01). Checking their status.') and call exosense-get-asset-statuses with the chosen fallback asset_ids. Returns asset_id, asset_name; then use get-asset-statuses with ALL relevant asset_ids.",
    "inputSchema": schema
}
