"""GraphQL queries for Logs"""

from typing import Any, Dict, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_event_logs(
    filters: Optional[Dict[str, Any]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Query to get Event logs"""
    filters = filters or {}
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    
    return GraphQLQuery(
        query="""
        query getEventLogs($filters: LogFilters, $pagination: Pagination = null) {
          logs(filters: $filters, pagination: $pagination) {
            id
            timestamp
            level
            category
            asset { id name }
            user { id email name }
            template_parameters
          }
        }
        """,
        operation_name="getEventLogs",
        variables={
            "filters": filters,
            "pagination": pagination_dict,
        },
    )

