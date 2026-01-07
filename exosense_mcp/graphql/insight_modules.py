"""GraphQL queries for Insight Modules"""

from typing import Any, Dict, Optional
from ..exosense_client import GraphQLQuery
from ..types.graphql import Pagination


def get_internal_insight_modules(
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """List all internal insight modules"""
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    
    return GraphQLQuery(
        query="""
        query getInternalInsightModules($pagination: Pagination = null) {
          internalInsightModules(pagination: $pagination) {
            id
            name
            description
          }
        }
        """,
        variables={"pagination": pagination_dict},
        operation_name="getInternalInsightModules",
    )


def get_insight_module(
    id: str,
    options: Optional[Dict[str, bool]] = None,
    pagination: Optional[Pagination] = None,
) -> GraphQLQuery:
    """Get detailed information about a specific insight module"""
    options = options or {}
    # Convert Pagination object to dict if it's a Pydantic model
    if pagination is None:
        pagination_dict = None
    elif isinstance(pagination, Pagination):
        pagination_dict = pagination.model_dump(exclude_none=True)
    else:
        pagination_dict = pagination
    include_translations = options.get("includeTranslations", False)
    
    return GraphQLQuery(
        query="""
        query getInsightModule($id: ID!,
            $includeTranslations: Boolean = false,
            $pagination: Pagination = null) {
          internalInsightModule(id: $id, pagination: $pagination) {
            id
            name
            description
            translations @include(if: $includeTranslations) {
              lang
              name
              description
            }
            functions {
              id
              name
              description
              type
              dsl
              action
              inlets {
                name
                description
                tag
                units
                types
                primitive
              }
              outlets {
                name
                description
                tag
                units
                types
                primitive
              }
            }
          }
        }
        """,
        variables={
            "id": id,
            "includeTranslations": include_translations,
            "pagination": pagination_dict,
        },
        operation_name="getInsightModule",
    )

