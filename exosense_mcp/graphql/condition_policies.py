"""GraphQL queries for Condition Policies"""

from typing import Any, Dict, List, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_policies(pagination: Optional[Pagination] = None) -> GraphQLQuery:
    """Get condition policies with optional pagination"""
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    
    return GraphQLQuery(
        query="""
        query getPolicies($pagination: Pagination) {
          policies(pagination: $pagination) {
            id
            priority
            workInstructionId
            workInstruction { id name }
            translations {
              language
              name
              policy
              createdAt
              updatedAt
            }
          }
        }
        """,
        variables={"pagination": pagination_dict},
        operation_name="getPolicies",
    )


def get_conditions(
    query: Optional[List[Dict[str, Any]]] = None,
    order: Optional[List[Dict[str, Any]]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Get conditions with optional query and pagination"""
    query = query or []
    order = order or []
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    
    return GraphQLQuery(
        query="""
        query getConditions($query: [ConditionQuery!], $order: [ConditionQueryOrder!], $pagination: Pagination) {
          conditionQuery(query: $query, order: $order, pagination: $pagination) {
            total
            results {
              id
              asset { id name }
              policy { id }
              level
              category
              timestamp
              value
              valueString
              additionalFields
            }
          }
        }
        """,
        variables={"query": query, "order": order, "pagination": pagination_dict},
        operation_name="getConditions",
    )


def get_condition_comments(
    condition_id: str,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Get comments for a specific condition"""
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    
    return GraphQLQuery(
        query="""
        query getConditionComments($condition_id: ID!, $pagination: Pagination) {
          conditionComments(condition_id: $condition_id, pagination: $pagination) {
            id
            comment
            user { id email name }
            createdAt
            updatedAt
          }
        }
        """,
        variables={"condition_id": condition_id, "pagination": pagination_dict},
        operation_name="getConditionComments",
    )

