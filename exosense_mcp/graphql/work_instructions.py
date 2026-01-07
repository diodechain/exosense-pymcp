"""GraphQL queries for Work Instructions"""

from typing import Any, Dict, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_work_instructions(
    filters: Optional[Dict[str, Any]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Get work instructions with optional filters and pagination"""
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
        query getWorkInstructions($filters: WorkInstructionFilters, $pagination: Pagination) {
          workInstructions(filters: $filters, pagination: $pagination) {
            id
            name
            filename
            version
            extension
            group { id name }
            versions {
              id
              workInstructionId
              name
              version
              filename
              extension
              group { id name }
              fileData
              updatedAt
              createdAt
              fileLastModified
            }
            contents {
              id
              name
              version
              filename
              extension
              updatedAt
              createdAt
              fileLastModified
            }
            fileData
            updatedAt
            createdAt
            fileLastModified
          }
        }
        """,
        variables={"filters": filters, "pagination": pagination_dict},
        operation_name="getWorkInstructions",
    )

