# GraphQL asset type and filters

## What the Exosense docs say

- **Asset Types** (docs: [Asset Types](https://docs.exosite.io/exosense/asset-types/)): Used for fleet view and consistent metrics across similar assets. They define “Metrics” and are associated with assets (often via templates). Feature is tier-dependent.
- **Asset Templates** (docs: [Asset Templates](https://docs.exosite.io/exosense/asset-templates/)): Define configuration (signals, rules, dashboards). Assets can have `template { id name }` in the GraphQL API.
- **Our use of Asset Type**: We request each asset's type name via GraphQL `assetType { name }` (see `includeAssetType` in `graphql/assets.py`). That matches [Exosense Asset Types](https://docs.exosite.io/exosense/asset-types/): the type name is used "through-out ExoSense when assets are viewed as type or fleet." We use it for finding assets by kind (e.g. "fan" matches type name "Fan") and expose `asset_type_name` in find-asset. We do not use Asset Type Metrics (those are for the fleet grid in the UI).
- **API**: The [GraphQL API](https://docs.exosite.io/exosense/api/) supports introspection via `__schema` and `__type`. The exact shape of `AssetFilters` (and whether there is an `assetTypes` root query) is not fully documented; it can be discovered by introspection.

## Discovering filters and types on your instance

Use the introspection helpers in `exosense_mcp/graphql/introspection.py` and call them with your Exosense client (e.g. from a small script or the MCP server):

1. **AssetFilters** – which filter arguments the `assets` query accepts (e.g. `text`, `template_id`, `type_id`, `group_id`):
   - `get_asset_filters_schema()` → `__type(name: "AssetFilters")` and its `inputFields`.

2. **Query root** – whether there is an `assetTypes` (or similar) root query:
   - `get_query_root_fields()` → `__schema { queryType { fields } }`.

3. **AssetType** – if the fleet-view “Asset Type” feature is in the schema:
   - `get_asset_type_schema()` → `__type(name: "AssetType")`.

If your instance supports filter fields like `template_id` or `type_id`, you can pass them in the `filters` dict when calling `get_assets()` to narrow finds by template or type instead of (or in addition to) `text`.

## How this repo uses it

- **find-asset** uses `filters: { "text": query }` with `includeTemplates: True` and `includeAssetType: True`. We score by asset name, template name, and **assetType name** (best of the three); responses include `template_name` and `asset_type_name` when present.
- **groups_by_asset_type** uses the same fuzzy find (name + template + assetType), then aggregates by customer (customer level is chosen dynamically as the path depth with the most distinct groups).

If introspection shows that `AssetFilters` supports `template_id` or a type identifier, we can add filter-by-template or filter-by-type to reduce payload and make finds more accurate.
