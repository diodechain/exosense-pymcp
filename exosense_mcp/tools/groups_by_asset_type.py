"""Find top-level groups (customers) that have assets of a given type, with counts. Use for 'which customer has the most fan-related assets?'."""

from typing import Dict, Any, List, Optional
from pydantic import Field, ValidationError
from ..graphql.assets import get_assets
from ..graphql.groups import get_groups_with_asset_ids
from ..types.graphql import Pagination
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import (
    pydantic_to_json_schema,
    format_success_response,
    format_error_response,
    path_from_root_for_group,
)
from .find_asset import calculate_similarity


class GroupsByAssetTypeParams(McpToolParams):
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
            "includeAssetType": True,
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
            asset_type = asset.get("assetType")
            type_name = (asset_type.get("name") or "").strip() if isinstance(asset_type, dict) else ""
            type_sim = calculate_similarity(args.query, type_name) if type_name else 0.0
            sim = max(name_sim, template_sim, type_sim) if (template_sim or type_sim) else name_sim
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

        # 3) Find "customer" level = depth with the most distinct groups (e.g. under Farms -> Mahr Brothers, Customer2, ...)
        #    so we don't hardcode path[1]; we use the level that has the most branching.
        paths_per_asset: List[List[Dict[str, str]]] = []
        unmapped = 0
        for asset_id in matching_asset_ids:
            gid = asset_to_group.get(asset_id)
            if not gid:
                unmapped += 1
                continue
            path = path_from_root_for_group(gid, group_info)
            if path:
                paths_per_asset.append(path)
        # Count distinct group_ids per depth; pick depth with max distinct count (prefer deeper if tie)
        distinct_at_depth: Dict[int, set] = {}
        for path in paths_per_asset:
            for d in range(len(path)):
                gid = path[d].get("group_id")
                if gid:
                    distinct_at_depth.setdefault(d, set()).add(gid)
        # customer_depth = depth with most distinct groups; if tie, prefer larger d (more granular)
        if not distinct_at_depth:
            customer_depth = 0
        else:
            max_distinct = max(len(s) for s in distinct_at_depth.values())
            candidate_depths = [d for d, s in distinct_at_depth.items() if len(s) == max_distinct]
            customer_depth = max(candidate_depths)

        # 4) Aggregate by group at customer_depth; store path from root to that group
        top_level_counts: Dict[str, int] = {}
        top_level_names: Dict[str, str] = {}
        top_level_paths: Dict[str, List[Dict[str, str]]] = {}
        for path in paths_per_asset:
            if customer_depth < len(path):
                ent = path[customer_depth]
            else:
                ent = path[-1] if path else None
            if not ent:
                continue
            tid = ent.get("group_id")
            tname = ent.get("group_name") or "Unnamed"
            if tid:
                top_level_counts[tid] = top_level_counts.get(tid, 0) + 1
                top_level_names[tid] = tname
                # path from root to this customer (inclusive)
                if tid not in top_level_paths:
                    top_level_paths[tid] = path[: customer_depth + 1]

        # 5) Build response: same shape as groups-with-asset-issues (customer, path_from_root, path, parent_group, asset_count)
        sorted_tids = sorted(top_level_counts.items(), key=lambda x: -x[1])
        top_level_groups = []
        for tid, count in sorted_tids:
            tname = top_level_names.get(tid) or "Unnamed"
            path_from_root = top_level_paths.get(tid) or [{"group_id": tid, "group_name": tname}]
            path_str = " > ".join((p.get("group_name") or "") for p in path_from_root) or tname
            parent_ent = path_from_root[-2] if len(path_from_root) >= 2 else (path_from_root[0] if path_from_root else None)
            parent_group = {"group_id": parent_ent.get("group_id"), "group_name": parent_ent.get("group_name")} if parent_ent else None
            top_level_groups.append({
                "group_id": tid,
                "group_name": tname,
                "customer": tname,
                "parent_group": parent_group,
                "path_from_root": path_from_root,
                "path": path_str,
                "asset_count": count,
            })
        payload = {
            "query": args.query,
            "total_assets_matched": len(matching_asset_ids),
            "top_level_groups": top_level_groups,
            "total_customers_with_assets": len(top_level_groups),
        }
        if unmapped:
            payload["assets_not_in_any_group"] = unmapped
        msg = f'Found {len(matching_asset_ids)} asset(s) matching "{args.query}" across {len(top_level_groups)} customer(s).'
        return format_success_response(payload, msg)
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


schema = pydantic_to_json_schema(GroupsByAssetTypeParams)
TOOL_METADATA = {
    "name": "exosense-groups-by-asset-type",
    "description": "Use for: 'Which customers have [fan/pump/...] assets?', 'Which customer has the most fan-related assets?', 'How many customers have X assets?'. Same approach as exosense-groups-with-asset-issues but by asset type: detects customer level dynamically (the path depth with the most distinct groups, e.g. under Farms the customers are Mahr Brothers, etc.). Returns group_id, group_name, customer, parent_group, path_from_root, path, asset_count. When answering reply with a concise list of customer names and asset counts only. Query is the asset type (e.g. 'fan', 'pump'); uses fuzzy match on name, template, and assetType.",
    "inputSchema": schema,
}
