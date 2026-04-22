"""Pydantic base for MCP tool arguments (handles explicit JSON null from clients)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class McpToolParams(BaseModel):
    """
    MCP/JSON tool calls often pass explicit ``null`` for optional or defaulted args.
    Pydantic only applies a default when the key is missing, so ``null`` fails.
    For fields that are not required (they have a default or default factory),
    remove the key when the value is null so the normal default applies.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_json_null_for_defaulted_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, finfo in cls.model_fields.items():
            if name not in out or out[name] is not None:
                continue
            if finfo.is_required():
                continue
            del out[name]
        return out
