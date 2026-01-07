"""GraphQL queries for Groups"""

from typing import Any, Dict, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_root_group_id() -> GraphQLQuery:
    """Query to get the root Group ID"""
    return GraphQLQuery(
        query='query getRootGroupId { groups(filters: { text: "root" }) { id name } }',
        operation_name="getRootGroupId",
    )


def get_all_groups(
    filters: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, bool]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """
    Query to get all Groups and a basic overview of their contents
    To get a single group, use the filters.
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

    include_children = options.get("includeChildren", False)
    include_assets = options.get("includeAssets", False)
    include_devices = options.get("includeDevices", False)
    include_users = options.get("includeUsers", False)
    include_roles = options.get("includeRoles", False)

    return GraphQLQuery(
        query="""
        query getAllGroups($filters: GroupFilters,
            $includeChildren: Boolean = false,
            $includeAssets: Boolean = false,
            $includeDevices: Boolean = false,
            $includeUsers: Boolean = false,
            $includeRoles: Boolean = false,
            $pagination: Pagination = null
            ) {
            groups(filters: $filters, pagination: $pagination) {
              id name parent_id
              node_type_id custom_id description
              assets(pagination: $pagination) @include(if: $includeAssets) { id name }
              devices(pagination: $pagination) @include(if: $includeDevices) { id identity }
              users(pagination: $pagination) @include(if: $includeUsers) { id email name }
              children(pagination: $pagination) @include(if: $includeChildren) { id name }
              roles @include(if: $includeRoles) { name }
              totals(recurse: false) {
                devices @include(if: $includeDevices)
                assets @include(if: $includeAssets)
                groups @include(if: $includeChildren)
                users @include(if: $includeUsers)
              }
            }
          }""",
        variables={
            "filters": filters,
            "includeChildren": include_children,
            "includeAssets": include_assets,
            "includeDevices": include_devices,
            "includeUsers": include_users,
            "includeRoles": include_roles,
            "pagination": pagination_dict,
        },
        operation_name="getAllGroups",
    )

