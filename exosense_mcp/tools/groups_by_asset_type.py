"""Find top-level groups (customers) that have assets of a given type, with counts. Use for 'which customer has the most fan-related assets?'."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ValidationError
from ..graphql.assets import get_assets
from ..graphql.groups import get_groups_with_asset_ids
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import (
    pydantic_to_json_schema,
    format_success_response,
    format_error_response,
    path_from_root_for_group,
)
from .find_asset import calculate_similarity


class GroupsByAssetTypeParams(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Asset type or name to search (e.g. 'fan', 'circulation fan', 'pump'). Uses same fuzzy matching as find-asset.",
    )
    max_assets: int = Field(
        100,
        ge=1,
        le=500,
        description="Max matching assets to consider when aggregating by group (default 100).",
    )
    min_similarity: float = Field(
        0.3,
        ge=0,
        le=1,
        description="Minimum similarity score for asset name match (default 0.3).",
    )


def _build_asset_to_group_and_info(groups: List[Dict]) -> tuple:
    """Build asset_id -> group_id and group_id -> { name, parent_id }."""
    asset_to_group: Dict[str, str] = {}
    group_info: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        gid = g.get("id")
        if not gid:
            continue
        group_info[gid] = {"name": g.get("name") or "Unnamed", "parent_id": g.get("parent_id")}
        for a in g.get("assets") or []:
            aid = a.get("id") if isinstance(a, dict) else a
            if aid:
                asset_to_group[aid] = gid
    return asset_to_group, group_info


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    try:
        args_in = dict(arguments)
        if args_in.get("max_assets") is None:
            args_in["max_assets"] = 100
        else:
            try:
                args_in["max_assets"] = int(args_in["max_assets"])
            except (TypeError, ValueError):
                args_in["max_assets"] = 100
        if args_in.get("min_similarity") is None:
            args_in["min_similarity"] = 0.3
        try:
            args = GroupsByAssetTypeParams(**args_in)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None
        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # 1) Fuzzy-find assets of this type (same logic as find-asset; include template for type matching)
        filters = {"text": args.query.strip()}
        options = {
            "includeTemplates": True,
            "includeParent": False,
            "includeMeta": False,
            "includeLocation": False,
            "includeData": False,
            "extraRuleData": False,
        }
        pagination = Pagination(limit=200, offset=0)
        query = get_assets(filters, options, pagination)
        result = await client.query(query)
        assets = result.get("assets", []) or []
        scored = []
        for asset in assets:
            name = asset.get("name") or "Unnamed Asset"
            name_sim = calculate_similarity(args.query, name)
            template = asset.get("template")
            template_name = (template.get("name") or "").strip() if isinstance(template, dict) else ""
            template_sim = calculate_similarity(args.query, template_name) if template_name else 0.0
            sim = max(name_sim, template_sim) if template_sim > 0 else name_sim
            if sim >= args.min_similarity:
                scored.append({"asset": asset, "similarity": sim})
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        scored = scored[: args.max_assets]
        matching_asset_ids = [s["asset"].get("id") for s in scored if s["asset"].get("id")]
        if not matching_asset_ids:
            return format_success_response(
                {
                    "query": args.query,
                    "total_assets_matched": 0,
                    "top_level_groups": [],
                    "message": "No assets found matching the query; try a different term or check fallback_searches from exosense-find-asset.",
                },
                f'No assets found matching "{args.query}".',
            )

        # 2) Fetch groups with asset IDs to map asset_id -> group_id and build hierarchy
        all_groups: List[Dict] = []
        offset = 0
        limit = 200
        max_total = 1000
        while offset < max_total:
            pagination = Pagination(limit=limit, offset=offset)
            gquery = get_groups_with_asset_ids({}, pagination)
            gresult = await client.query(gquery)
            groups = gresult.get("groups", [])
            all_groups.extend(groups)
            if len(groups) < limit:
                break
            offset += limit
        asset_to_group, group_info = _build_asset_to_group_and_info(all_groups)

        # 3) For each matching asset, get top-level group and aggregate counts
        top_level_counts: Dict[str, int] = {}
        top_level_names: Dict[str, str] = {}
        unmapped = 0
        for asset_id in matching_asset_ids:
            gid = asset_to_group.get(asset_id)
            if not gid:
                unmapped += 1
                continue
            path = path_from_root_for_group(gid, group_info)
            top = path[0] if path else None
            if top:
                tid = top.get("group_id")
                tname = top.get("group_name") or "Unnamed"
                if tid:
                    top_level_counts[tid] = top_level_counts.get(tid, 0) + 1
                    top_level_names[tid] = tname

        # 4) Build response: top-level groups sorted by asset count desc
        top_level_groups = [
            {
                "group_id": tid,
                "group_name": top_level_names.get(tid) or "Unnamed",
                "asset_count": count,
            }
            for tid, count in sorted(top_level_counts.items(), key=lambda x: -x[1])
        ]
        payload = {
            "query": args.query,
            "total_assets_matched": len(matching_asset_ids),
            "top_level_groups": top_level_groups,
        }
        if unmapped:
            payload["assets_not_in_any_group"] = unmapped
        msg = f'Found {len(matching_asset_ids)} asset(s) matching "{args.query}" across {len(top_level_groups)} top-level group(s).'
        return format_success_response(payload, msg)
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


schema = pydantic_to_json_schema(GroupsByAssetTypeParams)
TOOL_METADATA = {
    "name": "exosense-groups-by-asset-type",
    "description": "Use for: 'Which customer has the most fan-related assets?', 'Which group has the most pumps?', 'Top-level groups by asset type'. Runs a fuzzy asset search (like find-asset) for the query (e.g. 'fan'), then maps each asset to its top-level group (customer) and returns top_level_groups: [{ group_id, group_name, asset_count }] sorted by asset_count descending. Answer 'which customer has the most X' by taking the first entry in top_level_groups.",
    "inputSchema": schema,
}
