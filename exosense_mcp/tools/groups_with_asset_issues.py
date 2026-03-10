"""Find which groups/customers have assets with issues (e.g. connectivity). Use for 'which customers have connectivity problems?'."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ValidationError
from ..graphql.groups import get_groups_with_asset_ids
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response, path_from_root_for_group
from . import asset_statuses


# Issue types that mean "connectivity" for the LLM
CONNECTIVITY_CATEGORIES = frozenset({"timeout", "offline"})


class GroupsWithAssetIssuesParams(BaseModel):
    issue_type: str = Field(
        "connectivity",
        description="'connectivity' = offline + timeout only; 'all' = any issue. Use 'connectivity' for 'which customers have connectivity problems?'.",
    )
    include_asset_details: bool = Field(
        False,
        description="If false (default), each group has affected_assets: [{asset_id, asset_name}] for links (compact). Set true to include issues per asset.",
    )
    max_groups: int = Field(500, ge=1, le=1000, description="Max groups to load for hierarchy (default 500, omit for default)")
    max_assets: int = Field(100, ge=1, le=500, description="Max assets to check status (default 100, omit for default)")


def _build_asset_to_group_and_paths(groups: List[Dict]) -> tuple:
    """Build asset_id -> group_id, group_id -> { name, parent_id }, and group_id -> path."""
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

    def path_for(gid: str) -> str:
        parts = []
        cur = gid
        while cur:
            info = group_info.get(cur)
            if not info:
                break
            parts.append(info["name"])
            cur = info.get("parent_id")
        return " > ".join(reversed(parts)) if parts else ""

    group_path: Dict[str, str] = {gid: path_for(gid) for gid in group_info}
    return asset_to_group, group_info, group_path


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    # Tolerate omitted or null max_groups/max_assets (LLM often sends only issue_type)
    args_in = dict(arguments)
    if args_in.get("max_groups") is None:
        args_in["max_groups"] = 500
    else:
        try:
            args_in["max_groups"] = int(args_in["max_groups"])
        except (TypeError, ValueError):
            args_in["max_groups"] = 500
    if args_in.get("max_assets") is None:
        args_in["max_assets"] = 100
    else:
        try:
            args_in["max_assets"] = int(args_in["max_assets"])
        except (TypeError, ValueError):
            args_in["max_assets"] = 100
    if args_in.get("include_asset_details") is None:
        args_in["include_asset_details"] = False
    elif isinstance(args_in.get("include_asset_details"), str):
        args_in["include_asset_details"] = args_in["include_asset_details"].lower() in ("true", "1", "yes", "on")
    try:
        args = GroupsWithAssetIssuesParams(**args_in)
    except ValidationError as e:
        return format_error_response(Exception(f"Invalid arguments: {e}"))

    auth = context.session.get("authorization") if context.session else None
    import exosense_mcp.server as server_module
    client = server_module.get_exosense_client(auth)

    # 1) Fetch all groups with asset IDs (paginate so we map every asset to a group)
    all_groups: List[Dict] = []
    offset = 0
    limit = min(args.max_groups, 200)  # per-request page size
    max_total_groups = 1000  # cap to avoid runaway
    while offset < max_total_groups:
        pagination = Pagination(limit=limit, offset=offset)
        query = get_groups_with_asset_ids({}, pagination)
        result = await client.query(query)
        groups = result.get("groups", [])
        all_groups.extend(groups)
        if len(groups) < limit:
            break
        offset += limit
    asset_to_group, group_info, group_path = _build_asset_to_group_and_paths(all_groups)

    # 2) Get asset statuses (include_details=true)
    status_args = {
        "include_details": True,
        "max_assets": args.max_assets,
        "extra_status_data": False,
        "filter_category": None,
        "filter_level": None,
    }
    status_result = await asset_statuses.execute(status_args, context)
    content = status_result.get("content", [])
    if not content or content[0].get("type") != "text":
        return status_result

    import json
    try:
        data = json.loads(content[0]["text"])
        if not data.get("success"):
            return status_result
        payload = data.get("data", {})
    except (json.JSONDecodeError, KeyError, TypeError):
        return status_result

    # 3) Collect affected assets: offline + by issue_type (connectivity = timeout + offline)
    affected_assets: Dict[str, Dict[str, Any]] = {}  # asset_id -> { name, issues[], from_offline }

    for item in payload.get("assets_offline_details") or []:
        aid = item.get("asset_id")
        if not aid:
            continue
        affected_assets[aid] = {
            "asset_name": item.get("asset_name") or "Unnamed",
            "issues": ["offline (no recent communication)"],
            "from_offline": True,
            "last_heard": item.get("last_heard"),
        }

    for item in payload.get("assets_with_issues_details") or []:
        aid = item.get("asset_id")
        if not aid:
            continue
        issue_strs = []
        for raw in (item.get("issue_details") or item.get("issues") or []):
            if isinstance(raw, dict):
                issue_strs.append(raw.get("description") or f"{raw.get('category', '')} ({raw.get('level', '')})".strip())
            else:
                issue_strs.append(str(raw))
        if args.issue_type == "connectivity":
            relevant = [i for i in issue_strs if any(c in (i or "").lower() for c in ("timeout", "offline"))]
            if not relevant and aid in affected_assets:
                relevant = affected_assets[aid].get("issues", [])
            if not relevant:
                continue
        else:
            relevant = issue_strs or ["(issue)"]
        if aid not in affected_assets:
            affected_assets[aid] = {
                "asset_name": item.get("asset_name") or "Unnamed",
                "issues": relevant,
                "from_offline": False,
                "last_heard": item.get("last_heard"),
            }
        else:
            existing = affected_assets[aid]["issues"]
            for r in relevant:
                if r not in existing:
                    existing.append(r)
            if item.get("last_heard") is not None:
                affected_assets[aid]["last_heard"] = item.get("last_heard")

    # 4) Map to groups and build path / customer
    by_group: Dict[str, Dict[str, Any]] = {}
    unmapped_count = 0
    for aid, info in affected_assets.items():
        gid = asset_to_group.get(aid)
        if not gid:
            gid = "_unmapped_"
            unmapped_count += 1
        if gid not in by_group:
            ginfo = group_info.get(gid, {})
            path = group_path.get(gid, "") or (ginfo.get("name") or gid)
            top = path.split(" > ")[1] if " > " in path else (ginfo.get("name") or "Unmapped")
            parent_id = ginfo.get("parent_id")
            parent_group = None
            if parent_id and gid != "_unmapped_":
                parent_ginfo = group_info.get(parent_id, {})
                parent_group = {"group_id": parent_id, "group_name": parent_ginfo.get("name")}
            path_from_root = path_from_root_for_group(gid, group_info) if gid != "_unmapped_" else None
            by_group[gid] = {
                "group_id": gid if gid != "_unmapped_" else None,
                "group_name": ginfo.get("name", "Unmapped (group not in hierarchy)"),
                "parent_group": parent_group,
                "path_from_root": path_from_root,
                "path": path if gid != "_unmapped_" else "Group not found in fetched hierarchy",
                "customer": top,
                "affected_asset_count": 0,
                "affected_assets": [],
            }
        by_group[gid]["affected_asset_count"] += 1
        by_group[gid]["affected_assets"].append({
            "asset_id": aid,
            "asset_name": info["asset_name"],
            "issues": info["issues"][:5],
            "last_heard": info.get("last_heard"),
        })

    # Sort: known groups first (by count desc), then unmapped last
    groups_with_issues = sorted(
        by_group.values(),
        key=lambda x: (x["group_id"] == "_unmapped_", -x["affected_asset_count"], x["group_name"] or ""),
    )
    # Normalize unmapped entry for response (no fake group_id for links)
    for g in groups_with_issues:
        if g.get("group_id") == "_unmapped_":
            g["group_id"] = None
            g["group_name"] = "Unmapped (group not in hierarchy)"
            g["path"] = "Group not found in fetched hierarchy"
            g["customer"] = "Unmapped"
            break

    # Compact response when include_asset_details is False: id, name, last_heard (for links and duration)
    if not getattr(args, "include_asset_details", False):
        for g in groups_with_issues:
            g["affected_assets"] = [
                {
                    "asset_id": a.get("asset_id"),
                    "asset_name": a.get("asset_name") or a.get("asset_id", ""),
                    "last_heard": a.get("last_heard"),
                }
                for a in g.get("affected_assets", [])
            ]

    out = {
        "issue_type": args.issue_type,
        "groups_with_issues": groups_with_issues,
        "total_groups_affected": len([g for g in groups_with_issues if g.get("group_id")]),
        "total_assets_affected": len(affected_assets),
    }
    if unmapped_count:
        out["unmapped_asset_count"] = unmapped_count
        out["note"] = "Some assets could not be mapped to a group (they may belong to groups beyond the fetched set)."

    message = f"{out['total_groups_affected']} group(s) have assets with {'connectivity ' if args.issue_type == 'connectivity' else ''}issues ({len(affected_assets)} asset(s))."
    if unmapped_count:
        message += f" {unmapped_count} asset(s) could not be mapped to a group."

    return format_success_response(out, message)


schema = pydantic_to_json_schema(GroupsWithAssetIssuesParams)
TOOL_METADATA = {
    "name": "exosense-groups-with-asset-issues",
    "description": "Use for: 'Which customers are being impacted?', 'Which customer has been impacted the longest?' - returns groups with group_id, group_name, parent_group, path_from_root, path, and affected_assets (asset_id, asset_name, last_heard). When answering 'which customers are impacted?' reply with a concise list of customer/site names (group_name) and affected asset counts only; do NOT include path, path_from_root, or a 'Path:' line in the user-facing answer. Use path_from_root only when the user asks 'who is the customer?', 'who owns?', or for hierarchy. Use last_heard to compute duration. Set include_asset_details=true for full issue list per asset.",
    "inputSchema": schema,
}
