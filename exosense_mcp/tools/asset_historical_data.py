"""Generate and retrieve historical data reports"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError
from ..graphql.reports import create_report, get_report_status, get_report_content
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class SignalInput(BaseModel):
    """Signal input for historical data"""

    id: str
    name: str


class AssetHistoricalDataParams(BaseModel):
    """Parameters for asset historical data tool"""

    asset_name: str = Field(..., description="Name of the asset to generate historical data report for")
    signals: List[SignalInput] = Field(..., description="Array of signals to include in the report")
    start_timestamp: str = Field(..., description="Start timestamp in ISO8601 format")
    end_timestamp: str = Field(..., description="End timestamp in ISO8601 format")
    timezone_format: str = Field("%Y-%m-%dT%H:%M:%S.%f%z", description="Format for timestamps in the report")
    timezone_offset: int = Field(0, description="Timezone offset in hours")
    max_wait_time: int = Field(300, description="Maximum time to wait for report completion in seconds (default: 5 minutes)")
    poll_interval: int = Field(5, description="Polling interval in seconds to check report status (default: 5 seconds)")

    @field_validator("start_timestamp", "end_timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Must be a valid ISO8601 timestamp")
        return v

    @model_validator(mode="after")
    def validate_timestamps(self):
        start_time = datetime.fromisoformat(self.start_timestamp.replace("Z", "+00:00")).timestamp()
        end_time = datetime.fromisoformat(self.end_timestamp.replace("Z", "+00:00")).timestamp()
        if start_time >= end_time:
            raise ValueError("Start timestamp must be before end timestamp")
        return self


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Generate and retrieve historical data report for an asset"""
    try:
        # Validate arguments with Pydantic
        try:
            args = AssetHistoricalDataParams(**arguments)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Step 1: Create the report
        context.log.info(f"Creating report for asset: {args.asset_name}")
        await context.report_progress({"progress": 1})

        start_timestamp = int(datetime.fromisoformat(args.start_timestamp.replace("Z", "+00:00")).timestamp())
        end_timestamp = int(datetime.fromisoformat(args.end_timestamp.replace("Z", "+00:00")).timestamp())

        create_report_input: dict = {
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "signals": [{"id": s.id, "name": s.name} for s in args.signals],
            "assetNames": [args.asset_name],
            "timezone": {
                "format": args.timezone_format,
                "offset": args.timezone_offset,
            },
        }

        query = create_report(create_report_input)
        context.log.debug("Creating report with parameters", create_report_input)
        result = await client.mutate(query)
        job_id = result.get("createReport")

        context.log.info(f"Report created with job ID: {job_id}")
        await context.report_progress({"progress": 2})

        # Step 2: Poll for report completion
        start_time = datetime.now().timestamp()
        max_wait_ms = args.max_wait_time * 1000

        while True:
            if (datetime.now().timestamp() - start_time) * 1000 > max_wait_ms:
                return format_error_response(Exception(f"Report generation timed out after {args.max_wait_time} seconds"))

            status_query = get_report_status(job_id)
            context.log.debug(f"Checking report status for job ID: {job_id}")
            status_result = await client.query(status_query)
            report_status = status_result.get("reportStatus")

            context.log.info(f"Report status: {report_status.get('state')}, Job ID: {job_id}")
            await context.report_progress({"progress": 3})

            state = report_status.get("state")
            if state == "completed":
                context.log.info("Report completed successfully")
                break
            elif state == "failed":
                return format_error_response(Exception(f"Report generation failed for job ID: {job_id}"))
            elif state == "expired":
                return format_error_response(Exception(f"Report generation expired for job ID: {job_id}"))

            await asyncio.sleep(args.poll_interval)

        # Step 3: Get the report download URL
        context.log.info(f"Retrieving report content URL for job ID: {job_id}")
        content_query = get_report_content(job_id)
        content_result = await client.query(content_query)
        download_url = content_result.get("report")

        context.log.info(f"Report ready for download: {download_url}")
        await context.report_progress({"progress": 4, "total": 4})

        return format_success_response(
            {
                "job_id": job_id,
                "download_url": download_url,
                "asset_name": args.asset_name,
                "signals": [{"id": s.id, "name": s.name} for s in args.signals],
                "start_timestamp": args.start_timestamp,
                "end_timestamp": args.end_timestamp,
                "timezone": {
                    "format": args.timezone_format,
                    "offset": args.timezone_offset,
                },
            },
            f"Historical data report generated successfully for asset {args.asset_name}. Report is ready for download.",
        )
    except Exception as error:
        context.log.error("Error generating asset historical data report", {"error": str(error)})
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(AssetHistoricalDataParams)
TOOL_METADATA = {
    "name": "exosense-get-asset-historical-data",
    "description": "Generate and retrieve historical data report for an asset with specified signals and time range",
    "inputSchema": schema
}
