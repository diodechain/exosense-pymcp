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


def get_asset_statuses(
    ids: List[str],
    options: Optional[Dict[str, Any]] = None,
) -> GraphQLQuery:
    """Query to get asset statuses"""
    options = options or {}
    extra_status_data = options.get("extraStatusData", False)
    
    return GraphQLQuery(
        query="""
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
        """,
        variables={"ids": ids, "statusLimit": 5 if extra_status_data else 1},
        operation_name="getAssetStatuses",
    )

