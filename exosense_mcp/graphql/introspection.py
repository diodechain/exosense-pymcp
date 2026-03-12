"""GraphQL introspection queries to discover schema (e.g. AssetFilters, assetTypes).
Run against your ExoSense instance to see available filters and types.
See: https://docs.exosite.io/exosense/api/ (Schema / Introspection)."""

from typing import Any, Dict
from ..exosense_client import GraphQLQuery


def get_asset_filters_schema() -> GraphQLQuery:
    """Introspect AssetFilters input type to see which filter fields the API supports (e.g. text, template_id, type_id)."""
    return GraphQLQuery(
        query="""
        query IntrospectAssetFilters {
          __type(name: "AssetFilters") {
            name
            kind
            inputFields {
              name
              type { name kind ofType { name kind } }
              description
            }
          }
        }
        """,
        operation_name="IntrospectAssetFilters",
    )


def get_query_root_fields() -> GraphQLQuery:
    """Introspect Query type to see root fields (e.g. assets, assetTypes, groups)."""
    return GraphQLQuery(
        query="""
        query IntrospectQueryRoot {
          __schema {
            queryType {
              name
              fields {
                name
                description
                type { name kind }
              }
            }
          }
        }
        """,
        operation_name="IntrospectQueryRoot",
    )


def get_asset_type_schema() -> GraphQLQuery:
    """Introspect AssetType if it exists (for fleet view / asset types feature)."""
    return GraphQLQuery(
        query="""
        query IntrospectAssetType {
          __type(name: "AssetType") {
            name
            kind
            fields {
              name
              type { name kind }
            }
          }
        }
        """,
        operation_name="IntrospectAssetType",
    )


def get_signal_data_options_schema() -> GraphQLQuery:
    """Introspect the options type for signal.data() (e.g. PanelMetricOptions) to see if roll-up/interval/start/end exist."""
    return GraphQLQuery(
        query="""
        query IntrospectSignalDataOptions {
          signal: __type(name: "Signal") {
            name
            fields {
              name
              args {
                name
                type { name kind ofType { name kind } }
                description
              }
            }
          }
          panelMetricOptions: __type(name: "PanelMetricOptions") {
            name
            kind
            inputFields {
              name
              type { name kind ofType { name kind } }
              description
            }
          }
        }
        """,
        operation_name="IntrospectSignalDataOptions",
    )
