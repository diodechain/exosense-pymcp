"""GraphQL queries for Assets"""

from typing import Any, Dict, List, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination

# Large GraphQL fragments and queries - keeping structure similar to TypeScript version
ASSETS_FRAGMENTS = """
fragment SLC on SignalLinkageCheck {
  id
  check {
    ... on LinkageCheckBoolean { kind invert}
    ... on LinkageCheckString { kind contains }
    ... on LinkageCheckNumber { kind inside upper lower }
    ... on LinkageCheckTime { kind range tz}
    ... on LinkageCheckJSON { kind path }
  }
}
fragment Units on Unit {
  id
  name
  convert
  abbr
  channelDataUnit
  usCustomaryConvert
  siConvert
  nonCompliant
}
fragment MetricDatapoint on MetricDatapoint {
  timestamp
  valueString
  value
  protocol
  receivedTime
}
fragment SignalChannelConfig on SignalChannelConfig {
  value
  channel
  signal
}
"""

ASSETS_QUERY = """
query getAssets($filters: AssetFilters,
  $includeTemplates: Boolean = false,
  $includeAssetType: Boolean = false,
  $includeParent: Boolean = false,
  $includeMeta: Boolean = false,
  $includeLocation: Boolean = false,
  $includeData: Boolean = false,
  $ruleLimit: Int = 1,
  $pagination: Pagination = null,
  $ids: [ID] = null) {
  assets(filters: $filters, ids: $ids, pagination: $pagination, includeTemplates: $includeTemplates) {
    id name description locked
    parent @include(if: $includeParent) { id name }
    meta @include(if: $includeMeta)
    location @include(if: $includeLocation) { mode signal }
    template @include(if: $includeTemplates) { id name }
    assetType @include(if: $includeAssetType) { name }
    signals {
      id
      name
      locked
      visualize
      record
      favorite
      type {
        id
        name
        convertable
        units { ...Units }
        conversions {
          id
          name
          unit
          offset
          multiplier
        }
        primitive_type
      }
      tag
      channel {
        id
        properties
        display_name
        data(options: {limit: 1}) @include(if: $includeData) {
          ...MetricDatapoint
        }
      }
      root
      archived
      data(options: {limit: 1}) @include(if: $includeData) {
        ...MetricDatapoint
      }
      units { ...Units }
      precision { ...SignalChannelConfig }
      primitive_type
      baseline
      min
      max
      signalMin { ...SignalChannelConfig }
      signalMax { ...SignalChannelConfig }
      sampleRate
      reportRate { ...SignalChannelConfig }
      target
      timeout { ...SignalChannelConfig }
      displayFormat
      visualizationUnitsMetric
      visualizationUnitsUS
      deviceDiagnostic
      control
      templateKey
      templateOverrides
    }
    transformations {
      ... on InsightTransformation {
        id insight_id function_id group_id
        locked
        name
        subscribes { id tag }
        publishes { id }
        checks {
          pre { ...SLC }
          post { ...SLC }
        }
        constants
        templateOverrides
      }
    }
    rulez {
      id insight_id function_id group_id
      locked
      name
      subscribes { id tag }
      category
      constants
      checks {
        pre { ...SLC }
      }
      templateOverrides
      data(options: {limit: $ruleLimit}) @include(if: $includeData) {
        timestamp
        category
        type
        level
        value
        valueString
        additionalFields
      }
    }
    actions {
      id insight_id function_id group_id
      locked enabled
      action_definition_id
      name
      subscribes { id }
      constants
      checks {
        pre { ...SLC }
      }
      templateOverrides
    }
  }
}
"""


def get_assets(
    filters: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """
    Query to get Assets
    """
    filters = filters or {}
    options = options or {}
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination

    include_templates = options.get("includeTemplates", False)
    include_asset_type = options.get("includeAssetType", False)
    include_parent = options.get("includeParent", False)
    include_meta = options.get("includeMeta", False)
    include_location = options.get("includeLocation", False)
    include_data = options.get("includeData", False)
    extra_rule_data = options.get("extraRuleData", False)
    ids = options.get("ids")

    return GraphQLQuery(
        query=ASSETS_FRAGMENTS + ASSETS_QUERY,
        variables={
            "filters": filters,
            "includeTemplates": include_templates,
            "includeAssetType": include_asset_type,
            "includeParent": include_parent,
            "includeMeta": include_meta,
            "includeLocation": include_location,
            "includeData": include_data,
            "ruleLimit": 5 if extra_rule_data else 1,
            "pagination": pagination_dict,
            "ids": ids,
        },
        operation_name="getAssets",
    )


def get_asset_details(
    asset_id: Optional[str] = None,
    asset_name: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> GraphQLQuery:
    """
    Query to get a single asset with full details by ID or name
    """
    options = options or {}
    filters: Dict[str, Any] = {}
    
    if asset_name:
        filters["text"] = asset_name
    
    ids = [asset_id] if asset_id else None

    include_templates = options.get("includeTemplates", True)
    include_parent = options.get("includeParent", True)
    include_meta = options.get("includeMeta", True)
    include_location = options.get("includeLocation", True)
    include_data = options.get("includeData", False)
    extra_rule_data = options.get("extraRuleData", False)

    # Same query structure as getAssets but with different defaults
    return GraphQLQuery(
        query=ASSETS_FRAGMENTS + ASSETS_QUERY,
        variables={
            "filters": filters,
            "includeTemplates": include_templates,
            "includeParent": include_parent,
            "includeMeta": include_meta,
            "includeLocation": include_location,
            "includeData": include_data,
            "ruleLimit": 5 if extra_rule_data else 1,
            "pagination": {"limit": 1, "offset": 0},
            "ids": ids,
        },
        operation_name="getAssets",  # Must match the operation name in ASSETS_QUERY
    )


# Minimal status query for health checks: only id, lastHeard, category + level.
# Avoids timestamp, value, valueString, additionalFields to reduce backend load and response size.
ASSET_STATUSES_MINIMAL_QUERY = """
query getAssetStatuses($ids: [ID]!) {
  assetStatuses(ids: $ids) {
    id
    lastHeard
    categories(options: { limit: 1 }) {
      category
      values {
        level
      }
    }
  }
}
"""

# Full status query when extra status data (e.g. duration, history) is needed.
ASSET_STATUSES_FULL_QUERY = """
query getAssetStatuses($ids: [ID]!, $statusLimit: Int = 1) {
  assetStatuses(ids: $ids) {
    id
    lastHeard
    categories(options: { limit: $statusLimit }) {
      category
      values {
        timestamp
        level
        value
        valueString
        additionalFields
      }
    }
  }
}
"""


# Minimal query: one asset, signals id+name only (for listing signals to choose from).
ASSET_SIGNALS_LIST_QUERY = """
query getAssetSignalsList($assetId: ID!) {
  assets(ids: [$assetId], pagination: { limit: 1, offset: 0 }) {
    id
    name
    signals {
      id
      name
    }
  }
}
"""

# One asset, signals with data in time range for RMS computation. Request only timestamp and value.
# start/end: Unix seconds (Int). Omit for "last N" only.
ASSET_SIGNAL_DATA_QUERY = """
query getAssetSignalData($assetId: ID!, $dataLimit: Int!, $start: Int, $end: Int) {
  assets(ids: [$assetId], pagination: { limit: 1, offset: 0 }) {
    id
    name
    signals {
      id
      name
      data(options: { limit: $dataLimit, start: $start, end: $end }) {
        timestamp
        value
      }
    }
  }
}
"""


def get_asset_signals_list(asset_id: str) -> GraphQLQuery:
    """Minimal query: asset id, name, and list of signals (id, name) only. Use to list signals for user to pick."""
    return GraphQLQuery(
        query=ASSET_SIGNALS_LIST_QUERY,
        variables={"assetId": asset_id},
        operation_name="getAssetSignalsList",
    )


def get_asset_signal_data(
    asset_id: str,
    data_limit: int = 2000,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
) -> GraphQLQuery:
    """Query one asset's signals with time-series data for the given range. Use for RMS/trend. start/end are Unix seconds."""
    variables: Dict[str, Any] = {"assetId": asset_id, "dataLimit": min(data_limit, 5000)}
    if start_ts is not None:
        variables["start"] = int(start_ts)
    if end_ts is not None:
        variables["end"] = int(end_ts)
    return GraphQLQuery(
        query=ASSET_SIGNAL_DATA_QUERY,
        variables=variables,
        operation_name="getAssetSignalData",
    )


def get_asset_statuses(
    ids: List[str],
    options: Optional[Dict[str, Any]] = None,
) -> GraphQLQuery:
    """Query to get asset statuses. Use minimal query when extraStatusData is False to reduce backend memory and payload."""
    options = options or {}
    extra_status_data = options.get("extraStatusData", False)

    if extra_status_data:
        return GraphQLQuery(
            query=ASSET_STATUSES_FULL_QUERY,
            variables={"ids": ids, "statusLimit": 5},
            operation_name="getAssetStatuses",
        )
    return GraphQLQuery(
        query=ASSET_STATUSES_MINIMAL_QUERY,
        variables={"ids": ids},
        operation_name="getAssetStatuses",
    )

