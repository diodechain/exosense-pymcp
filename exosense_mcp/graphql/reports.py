"""GraphQL queries for Reports"""

from typing import Any, Dict
from ..exosense_client import GraphQLQuery


def get_report_status(job_id: str) -> GraphQLQuery:
    """Get the status of a report job"""
    return GraphQLQuery(
        query="""
        query getReportStatus($job_id: ID!) {
          reportStatus(job_id: $job_id) {
            query
            state
            format
            job_id
            length
            filename
            content_id
            start_time
            update_time
          }
        }
        """,
        variables={"job_id": job_id},
        operation_name="getReportStatus",
    )


def get_report_content(job_id: str) -> GraphQLQuery:
    """Get a URL to download the report content"""
    return GraphQLQuery(
        query="""
        query getReportContent($job_id: ID!) {
          report(job_id: $job_id, expires_in: 600)
        }
        """,
        variables={"job_id": job_id},
        operation_name="getReportContent",
    )


def create_report(report: Dict[str, Any]) -> GraphQLQuery:
    """Create a new report"""
    return GraphQLQuery(
        query="""
        mutation createReport($report: CreateReport!) {
          createReport(report_info: $report)
        }
        """,
        variables={"report": report},
        operation_name="createReport",
    )

