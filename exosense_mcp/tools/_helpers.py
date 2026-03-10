"""Helper functions for tools"""

from typing import Dict, Any, Type, Union, Optional, List
from pydantic import BaseModel
import json


def group_to_structured(
    g: Dict[str, Any],
    *,
    id_to_name: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Convert API group (id, name, parent_id, ...) to structured shape for LLMs:
    group_id, group_name, parent_group: { group_id, group_name }.
    id_to_name can be used to resolve parent_id -> parent name.
    """
    gid = g.get("id")
    name = g.get("name") or ""
    parent_id = g.get("parent_id")
    parent_group = None
    if parent_id:
        parent_name = (id_to_name or {}).get(parent_id) if id_to_name else None
        parent_group = {"group_id": parent_id, "group_name": parent_name}
    out = {
        "group_id": gid,
        "group_name": name,
        "parent_group": parent_group,
    }
    if "description" in g:
        out["description"] = g.get("description")
    if "custom_id" in g:
        out["custom_id"] = g.get("custom_id")
    return out


def path_from_root_for_group(
    group_id: str,
    id_to_info: Dict[str, Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    Walk parent_id from group_id up to root. id_to_info maps group_id -> { name, parent_id }.
    Returns list of { group_id, group_name } from root (first) to the given group (last).
    """
    path: List[Dict[str, str]] = []
    seen: set = set()
    cur = group_id
    while cur and cur not in seen:
        seen.add(cur)
        info = id_to_info.get(cur)
        name = (info.get("name") or "").strip() if info else ""
        path.append({"group_id": cur, "group_name": name or None})
        cur = info.get("parent_id") if info else None
    path.reverse()
    return path


def group_children_to_structured(
    children: List[Dict[str, Any]],
    *,
    parent_id: Optional[str] = None,
    parent_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert list of child groups to structured shape; each has parent_group: { group_id, group_name }."""
    result = []
    for c in children or []:
        parent_group = None
        if parent_id is not None:
            parent_group = {"group_id": parent_id, "group_name": parent_name or ""}
        result.append({
            "group_id": c.get("id"),
            "group_name": (c.get("name") or ""),
            "parent_group": parent_group,
        })
    return result


def asset_to_structured(
    a: Dict[str, Any],
    *,
    group_id: Optional[str] = None,
    group_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert API asset (id, name, ...) to structured shape for LLMs:
    asset_id, asset_name; optionally group_id, group_name.
    """
    out = {
        "asset_id": a.get("id"),
        "asset_name": (a.get("name") or "").strip() or None,
    }
    if group_id is not None:
        out["group_id"] = group_id
    if group_name is not None:
        out["group_name"] = group_name
    if a.get("description") is not None:
        out["description"] = a.get("description")
    if a.get("identity") is not None:
        out["identity"] = a.get("identity")
    return out


def pydantic_to_json_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model to JSON schema"""
    return model_class.model_json_schema()


def format_success_response(data: Any, message: Optional[str] = None) -> Dict[str, Any]:
    """Format success response for MCP"""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "data": data,
                        "message": message,
                    },
                    indent=2,
                ),
            }
        ]
    }


def format_error_response(error: Union[Exception, str]) -> Dict[str, Any]:
    """Format error response for MCP"""
    message = str(error) if isinstance(error, Exception) else error
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": False,
                        "error": message,
                    },
                    indent=2,
                ),
            }
        ]
    }

