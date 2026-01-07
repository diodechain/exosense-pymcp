"""GraphQL queries for Devices and Products"""

from typing import Any, Dict, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_all_products() -> GraphQLQuery:
    """Query to get a list of the connected IoT Connectors (aka products)"""
    return GraphQLQuery(
        query="""
        query getAllProducts {
          products {
            pid
            name
            isSimulator
            settings {
              fqdn
            }
          }
        }
        """,
        operation_name="getAllProducts",
    )


def get_devices(
    product: str,
    filters: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Query to get devices"""
    filters = filters or {}
    options = options or {}
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination

    include_tags = options.get("includeTags", False)
    include_res = options.get("includeRes", False)
    include_state = options.get("includeState", False)
    ids = options.get("ids")

    return GraphQLQuery(
        query="""
        query getDevices($filters: DeviceFilters,
            $product: String,
            $includeTags: Boolean = false,
            $includeRes: Boolean = false,
            $includeState: Boolean = false,
            $pagination: Pagination = null,
            $ids: [ID] = null) {
          devices(product: $product, filters: $filters, ids: $ids, pagination: $pagination) {
            id identity name description locked
            tags @include(if: $includeTags) { name value }
            resources @include(if: $includeRes) { name value }
            state @include(if: $includeState) { connected lastHeard }
          }
        }
        """,
        variables={
            "filters": filters,
            "product": product,
            "includeTags": include_tags,
            "includeRes": include_res,
            "includeState": include_state,
            "pagination": pagination_dict,
            "ids": ids,
        },
        operation_name="getDevices",
    )

