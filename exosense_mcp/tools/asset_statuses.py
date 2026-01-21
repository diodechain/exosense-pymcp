"""Get status information for specific assets"""

import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
from ..graphql.assets import get_asset_statuses, get_assets
from ..types.graphql import Pagination
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


class AssetStatusesParams(BaseModel):
    """Parameters for asset statuses tool"""

    asset_ids: Optional[List[str]] = Field(None, description="Optional list of specific asset IDs (UUIDs) to check. If not provided, will automatically fetch and check all assets (up to max_assets limit). You do NOT need to call get-assets first - this tool handles asset fetching internally.")
    max_assets: Optional[int] = Field(100, ge=1, le=500, description="Maximum number of assets to check when asset_ids is not provided (default: 100, max: 500). Only used when asset_ids is not provided.")
    extra_status_data: Optional[bool] = Field(False, description="Get additional status data (up to 5 entries instead of 1) for more detailed historical status information")
    include_details: Optional[bool] = Field(False, description="Include detailed lists of assets (assets_with_issues_details, assets_offline_details, assets_healthy_details). Default is false for concise responses. Set to true when user asks for specific asset names or details.")


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    """Get status information for specific assets or all assets"""
    try:
        # Validate arguments with Pydantic
        try:
            # Pre-process arguments to handle LLM quirks
            # Handle string to int conversion for max_assets (LLMs sometimes send strings)
            if 'max_assets' in arguments and isinstance(arguments['max_assets'], str):
                try:
                    arguments['max_assets'] = int(arguments['max_assets'])
                except (ValueError, TypeError):
                    arguments['max_assets'] = 100
            
            # Handle asset_ids being sent as a string instead of a list
            if 'asset_ids' in arguments:
                asset_ids = arguments['asset_ids']
                # Handle None, 'None', or empty string as None
                if asset_ids is None or asset_ids == 'None' or asset_ids == '' or (isinstance(asset_ids, str) and asset_ids.lower() == 'none'):
                    arguments['asset_ids'] = None
                elif isinstance(asset_ids, str):
                    # Single ID as string - but check if it's 'None' first
                    if asset_ids.lower() == 'none' or asset_ids == '':
                        arguments['asset_ids'] = None
                    else:
                        # Single ID as string - convert to list
                        arguments['asset_ids'] = [asset_ids]
                elif isinstance(asset_ids, list):
                    # Filter out None, 'None', and empty strings from list
                    filtered = [aid for aid in asset_ids if aid is not None and aid != 'None' and aid != '' and str(aid).lower() != 'none']
                    # If list is empty after filtering, set to None
                    if not filtered:
                        arguments['asset_ids'] = None
                    else:
                        arguments['asset_ids'] = filtered
                elif not isinstance(asset_ids, list):
                    # Try to convert other types
                    arguments['asset_ids'] = [str(asset_ids)]
            
            # Handle extra_status_data being sent as string
            if 'extra_status_data' in arguments:
                extra = arguments['extra_status_data']
                if isinstance(extra, str):
                    # Convert string to boolean
                    extra_lower = extra.lower()
                    if extra_lower in ('true', '1', 'yes', 'on'):
                        arguments['extra_status_data'] = True
                    elif extra_lower in ('false', '0', 'no', 'off', ''):
                        arguments['extra_status_data'] = False
                    else:
                        # If it's a number string, treat as False (it's a boolean flag)
                        arguments['extra_status_data'] = False
            
            # Handle include_details being sent as string
            if 'include_details' in arguments:
                include = arguments['include_details']
                if isinstance(include, str):
                    # Convert string to boolean
                    include_lower = include.lower()
                    if include_lower in ('true', '1', 'yes', 'on'):
                        arguments['include_details'] = True
                    elif include_lower in ('false', '0', 'no', 'off', ''):
                        arguments['include_details'] = False
                    else:
                        arguments['include_details'] = False
            
            args = AssetStatusesParams(**arguments)
            # Ensure defaults are set if None values are provided
            if args.extra_status_data is None:
                args.extra_status_data = False
            if args.max_assets is None:
                args.max_assets = 100
            # Clean up asset_ids - filter out 'None' strings
            if args.asset_ids:
                args.asset_ids = [aid for aid in args.asset_ids if aid is not None and aid != 'None' and aid != '' and str(aid).lower() != 'none']
                # If all were filtered out, set to None
                if not args.asset_ids:
                    args.asset_ids = None
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None

        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # Build asset_id -> asset_name mapping for including names in responses
        asset_names = {}  # {asset_id: asset_name}
        
        # If asset_ids not provided, fetch assets in batches
        # Handle case where asset_ids might be ['None'] or contain 'None' strings
        asset_ids_to_check = args.asset_ids or []
        if asset_ids_to_check:
            # Filter out None, 'None', and empty strings
            asset_ids_to_check = [aid for aid in asset_ids_to_check if aid is not None and aid != 'None' and aid != '' and str(aid).lower() != 'none']
            # If all were filtered out, treat as empty
            if not asset_ids_to_check:
                asset_ids_to_check = []
        
        context.log.info(f"Initial asset_ids_to_check: {asset_ids_to_check}, length: {len(asset_ids_to_check) if asset_ids_to_check else 0}")
        
        if not asset_ids_to_check:
            context.log.info(f"=== STARTING ASSET FETCH (max: {args.max_assets}) ===")
            # Fetch assets in batches to avoid overwhelming the LLM
            batch_size = 100
            all_asset_ids = []
            offset = 0
            
            while len(all_asset_ids) < args.max_assets:
                context.log.info(f"Fetching batch at offset {offset}, limit {batch_size}")
                pagination = Pagination(limit=batch_size, offset=offset)
                assets_query = get_assets(filters={}, options={}, pagination=pagination)
                context.log.info(f"Executing GraphQL query...")
                assets_result = await client.query(assets_query)
                context.log.info(f"GraphQL query completed. Response type: {type(assets_result)}")
                
                # Debug: Log what we got back
                if isinstance(assets_result, dict):
                    context.log.info(f"GraphQL response keys: {list(assets_result.keys())}")
                    context.log.info(f"GraphQL response structure: {json.dumps({k: type(v).__name__ for k, v in assets_result.items()}, indent=2)}")
                else:
                    context.log.error(f"GraphQL response is not a dict! Type: {type(assets_result)}, Value: {str(assets_result)[:200]}")
                
                assets = assets_result.get("assets", []) if isinstance(assets_result, dict) else []
                context.log.info(f"Fetched {len(assets)} assets at offset {offset}")
                
                # If no assets in "assets" key, check other possible keys
                if not assets:
                    context.log.warning(f"No 'assets' key found. Available keys: {list(assets_result.keys())}")
                    # Try common alternative keys
                    for key in ["data", "results", "items", "nodes"]:
                        if key in assets_result:
                            context.log.info(f"Found alternative key '{key}': {type(assets_result[key])}")
                            if isinstance(assets_result[key], list):
                                assets = assets_result[key]
                                context.log.info(f"Using '{key}' as assets list with {len(assets)} items")
                                break
                
                if not assets:
                    context.log.debug("No more assets found, stopping fetch")
                    break
                
                # Log first asset structure for debugging
                if assets:
                    first_asset = assets[0]
                    if isinstance(first_asset, dict):
                        context.log.info(f"First asset keys: {list(first_asset.keys())}")
                        context.log.info(f"First asset 'id' value: {first_asset.get('id')}")
                        context.log.info(f"First asset sample (first 10 fields): {json.dumps({k: str(v)[:100] for k, v in list(first_asset.items())[:10]}, indent=2)}")
                        # Check for ID in various possible formats
                        possible_id_keys = ["id", "ID", "_id", "assetId", "asset_id", "uuid", "UUID"]
                        found_id_key = None
                        for key in possible_id_keys:
                            if key in first_asset and first_asset[key]:
                                found_id_key = key
                                context.log.info(f"Found ID field: '{key}' = {first_asset[key]}")
                                break
                        if not found_id_key:
                            context.log.error(f"No ID field found! Checked keys: {possible_id_keys}")
                            context.log.error(f"Full first asset: {json.dumps(first_asset, default=str, indent=2)}")
                    else:
                        context.log.error(f"First asset is not a dict, it's: {type(first_asset)} = {first_asset}")
                
                # Store asset IDs and names
                assets_with_ids = 0
                for idx, asset in enumerate(assets):
                    if not isinstance(asset, dict):
                        context.log.warning(f"Asset at index {idx} is not a dict: {type(asset)}")
                        continue
                    
                    # Try multiple possible ID field names
                    asset_id = None
                    for key in ["id", "ID", "_id", "assetId", "asset_id", "uuid", "UUID"]:
                        if key in asset and asset[key]:
                            asset_id = asset[key]
                            break
                    
                    if asset_id:
                        all_asset_ids.append(asset_id)
                        asset_name = asset.get("name") or asset.get("Name") or asset.get("assetName") or "Unnamed Asset"
                        asset_names[asset_id] = asset_name
                        assets_with_ids += 1
                    else:
                        context.log.warning(f"Asset at index {idx} missing ID field. Asset keys: {list(asset.keys())}")
                        if idx == 0:  # Log full first asset if it's missing ID
                            context.log.error(f"First asset (missing ID): {json.dumps(asset, default=str, indent=2)}")
                
                context.log.info(f"Extracted {assets_with_ids} asset IDs from {len(assets)} assets in this batch")
                
                offset += batch_size
                
                if len(assets) < batch_size:  # Last page
                    context.log.debug(f"Last page reached (got {len(assets)} < {batch_size})")
                    break
                
                if len(all_asset_ids) >= args.max_assets:
                    all_asset_ids = all_asset_ids[:args.max_assets]
                    context.log.debug(f"Reached max_assets limit ({args.max_assets})")
                    break
            
            # Filter out any None values that might have been added
            all_asset_ids = [aid for aid in all_asset_ids if aid is not None and aid != "None" and aid != ""]
            asset_ids_to_check = all_asset_ids
            context.log.info(f"Found {len(asset_ids_to_check)} assets to check (from {len(asset_names)} with names)")
            if not asset_ids_to_check:
                context.log.error("No asset IDs were fetched! This should not happen. Check if assets have 'id' field.")
                return format_success_response(
                    {
                        "summary": {
                            "total_assets_checked": 0,
                            "assets_with_issues": 0,
                            "assets_offline": 0,
                            "assets_healthy": 0,
                        },
                        "message": "No assets found to check - assets may not have IDs"
                    },
                    "No assets found to check status"
                )
            else:
                context.log.info(f"First few asset IDs: {asset_ids_to_check[:3]}")
                # Validate all IDs are valid
                invalid_ids = [aid for aid in asset_ids_to_check if not aid or aid == "None" or aid is None]
                if invalid_ids:
                    context.log.error(f"Found {len(invalid_ids)} invalid asset IDs in list! This should not happen.")
                    asset_ids_to_check = [aid for aid in asset_ids_to_check if aid and aid != "None" and aid is not None]
        else:
            # If asset_ids provided, fetch names for those specific assets
            context.log.debug(f"Fetching names for {len(asset_ids_to_check)} provided asset IDs")
            # Fetch in batches to avoid query size limits
            batch_size = 50
            for i in range(0, len(asset_ids_to_check), batch_size):
                batch_ids = asset_ids_to_check[i:i + batch_size]
                assets_query = get_assets(filters={}, options={"ids": batch_ids}, pagination=None)
                assets_result = await client.query(assets_query)
                assets = assets_result.get("assets", [])
                for asset in assets:
                    asset_id = asset.get("id")
                    if asset_id:
                        asset_names[asset_id] = asset.get("name") or "Unnamed Asset"

        # Final validation: filter out any None values from asset_ids_to_check
        if asset_ids_to_check:
            original_count = len(asset_ids_to_check)
            asset_ids_to_check = [aid for aid in asset_ids_to_check if aid is not None and aid != "None" and aid != ""]
            if len(asset_ids_to_check) != original_count:
                context.log.warning(f"Filtered out {original_count - len(asset_ids_to_check)} None/invalid asset IDs")
        
        if not asset_ids_to_check:
            context.log.error("No valid asset IDs to check after all filtering!")
            return format_success_response(
                {
                    "summary": {
                        "total_assets_checked": 0,
                        "assets_with_issues": 0,
                        "assets_offline": 0,
                        "assets_healthy": 0,
                    },
                    "message": "No valid assets found to check"
                },
                "No valid assets found to check status"
            )
        
        context.log.info(f"Final asset_ids_to_check count: {len(asset_ids_to_check)}, first ID: {asset_ids_to_check[0] if asset_ids_to_check else 'N/A'}")

        # Check status for all assets (process in batches to avoid query size limits)
        batch_size = 50  # Process status checks in batches
        all_statuses = []
        # Track which asset_ids we're checking in each batch to match with responses
        status_to_asset_id_map = {}  # Maps status index to asset_id
        
        for i in range(0, len(asset_ids_to_check), batch_size):
            batch_ids = asset_ids_to_check[i:i + batch_size]
            options: dict = {"extraStatusData": args.extra_status_data}
            query = get_asset_statuses(batch_ids, options)
            context.log.debug(f"Checking status for batch {i//batch_size + 1} ({len(batch_ids)} assets)")
            result = await client.query(query)
            batch_statuses = result.get("assetStatuses", [])
            
            # Match status responses to asset IDs (in case status doesn't have id field)
            # The statuses should be returned in the same order as the IDs we requested
            # ALWAYS use batch_ids as the authoritative source since we know what we requested
            for idx, status in enumerate(batch_statuses):
                # Calculate the global index for this status
                global_idx = len(all_statuses) + idx
                
                # Always use batch_ids as authoritative - we know which IDs we requested
                if idx < len(batch_ids):
                    authoritative_id = batch_ids[idx]
                    # Set the ID in the status object for consistency
                    status["id"] = authoritative_id
                    # Map this global index to the asset ID
                    status_to_asset_id_map[global_idx] = authoritative_id
                    context.log.debug(f"Status at global index {global_idx} (batch idx {idx}) mapped to asset_id: {authoritative_id}")
                else:
                    # This shouldn't happen, but handle it gracefully
                    status_id = status.get("id")
                    if status_id and status_id != "None":
                        status_to_asset_id_map[global_idx] = status_id
                        context.log.warning(f"Status at index {idx} beyond batch_ids length, using status.id: {status_id}")
                    else:
                        context.log.error(f"Could not determine asset_id for status at index {idx} in batch (batch has {len(batch_ids)} items, status keys: {list(status.keys())})")
            
            all_statuses.extend(batch_statuses)
            context.log.debug(f"Batch {i//batch_size + 1}: Got {len(batch_statuses)} statuses for {len(batch_ids)} requested assets")

        # Aggregate results into a summary
        total_checked = len(all_statuses)
        assets_with_issues = 0
        assets_offline = 0
        assets_healthy = 0
        problem_categories = {}
        example_problems = []
        assets_with_issues_list = []  # Track which specific assets have issues
        assets_offline_list = []  # Track which specific assets are offline
        assets_healthy_list = []  # Track which specific assets are healthy
        
        for idx, status in enumerate(all_statuses):
            # Get asset_id - prioritize our mapping since we set it during batch processing
            asset_id = status_to_asset_id_map.get(idx)
            context.log.debug(f"Processing status at index {idx}: mapping has {len(status_to_asset_id_map)} entries, mapping[{idx}] = {asset_id}, status.id = {status.get('id')}, asset_ids_to_check[{idx}] = {asset_ids_to_check[idx] if idx < len(asset_ids_to_check) else 'N/A'}")
            
            # Fallback to status.get("id") if mapping doesn't have it
            if not asset_id or asset_id == "None" or asset_id is None:
                asset_id = status.get("id")
                context.log.debug(f"  After checking status.id: asset_id = {asset_id}")
            
            # Last resort: try to get from asset_ids_to_check by index
            if not asset_id or asset_id == "None" or asset_id is None:
                if idx < len(asset_ids_to_check):
                    asset_id = asset_ids_to_check[idx]
                    context.log.info(f"Using asset_ids_to_check[{idx}] = {asset_id} for status at index {idx} (mapping was empty)")
                    # Update the mapping and status for consistency
                    status_to_asset_id_map[idx] = asset_id
                    status["id"] = asset_id
                else:
                    # If we still can't find it, log and skip
                    context.log.error(f"Status response at index {idx} has no asset_id and couldn't be matched, skipping. Status keys: {list(status.keys())}, total statuses: {len(all_statuses)}, total asset_ids: {len(asset_ids_to_check)}, mapping keys: {list(status_to_asset_id_map.keys())}")
                    continue
            
            # Ensure asset_id is a valid string, not None or "None"
            if asset_id == "None" or asset_id is None:
                context.log.error(f"Asset ID is None or 'None' at index {idx} after all fallbacks, skipping. Mapping: {status_to_asset_id_map.get(idx)}, status.id: {status.get('id')}, asset_ids_to_check[{idx}]: {asset_ids_to_check[idx] if idx < len(asset_ids_to_check) else 'N/A'}")
                continue
            
            # Ensure we have the asset name - if not in our map, try to fetch it
            asset_name = asset_names.get(asset_id)
            if not asset_name:
                # Try to get from status if available, or mark as unknown
                asset_name = status.get("name") or "Unknown Asset"
                # Store it for future reference
                asset_names[asset_id] = asset_name
            last_heard = status.get("lastHeard")
            categories = status.get("categories", [])
            
            has_issues = False
            has_categories = len(categories) > 0
            issue_reasons = []  # Track why this asset has issues
            
            # Check if offline (no last_heard)
            # Only mark as offline if there's no last_heard AND no status data
            # (some assets might not have last_heard but still have status categories)
            if not last_heard and not has_categories:
                assets_offline += 1
                has_issues = True
                issue_reasons.append("offline (no communication)")
                assets_offline_list.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                })
            elif not last_heard:
                # Has status data but no last_heard - might be offline but has historical status
                assets_offline += 1
                issue_reasons.append("offline (no recent communication)")
                assets_offline_list.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                })
            
            # Check categories for problems
            for cat in categories:
                category_name = cat.get("category", "unknown")
                values = cat.get("values", [])
                if values:
                    latest_value = values[0]
                    level = latest_value.get("level", "").lower()
                    
                    # Track problem categories
                    if category_name not in problem_categories:
                        problem_categories[category_name] = {"count": 0, "levels": {}}
                    problem_categories[category_name]["count"] += 1
                    
                    if level:
                        if level not in problem_categories[category_name]["levels"]:
                            problem_categories[category_name]["levels"][level] = 0
                        problem_categories[category_name]["levels"][level] += 1
                    
                    # Consider critical/error/warning levels as issues
                    if level in ["critical", "error", "warning", "alarm"]:
                        has_issues = True
                        issue_reasons.append(f"{category_name} ({level})")
                        if len(example_problems) < 5:  # Keep a few examples
                            example_problems.append({
                                "asset_id": asset_id,
                                "asset_name": asset_name,
                                "category": category_name,
                                "level": level,
                                "value": latest_value.get("valueString"),
                                "timestamp": latest_value.get("timestamp"),
                            })
            
            # Track assets by status
            if has_issues:
                assets_with_issues += 1
                assets_with_issues_list.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "issues": issue_reasons,
                    "last_heard": last_heard,
                })
            elif has_categories or last_heard:
                assets_healthy += 1
                assets_healthy_list.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                })
            else:
                assets_healthy += 1  # No data but assume healthy if we have last_heard
                assets_healthy_list.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                })
        
        # Build summary response
        summary = {
            "total_assets_checked": total_checked,
            "assets_with_issues": assets_with_issues,
            "assets_offline": assets_offline,
            "assets_healthy": assets_healthy,
            "problem_categories": problem_categories if problem_categories else None,
            "example_problems": example_problems if example_problems else None,
        }
        
        # Only include detailed asset lists if explicitly requested (for concise responses by default)
        if args.include_details:
            if assets_with_issues_list:
                summary["assets_with_issues_details"] = assets_with_issues_list
            if assets_offline_list:
                summary["assets_offline_details"] = assets_offline_list
            # Only include healthy assets if there are few enough (avoid overwhelming response)
            if len(assets_healthy_list) <= 10:
                summary["assets_healthy_details"] = assets_healthy_list
        else:
            # For concise responses, only include asset names in the message, not full details
            # The example_problems already provide some asset names
            pass
        
        # Add health percentage
        if total_checked > 0:
            summary["health_percentage"] = round((assets_healthy / total_checked) * 100, 1)
        
        # Build informative message
        message_parts = [f"Checked {total_checked} asset(s)"]
        if assets_healthy > 0:
            message_parts.append(f"{assets_healthy} healthy")
        if assets_with_issues > 0:
            # Only include asset names in message if details are requested or there are very few
            if args.include_details and assets_with_issues_list:
                asset_names_with_issues = [a["asset_name"] for a in assets_with_issues_list]
                if len(asset_names_with_issues) <= 3:
                    message_parts.append(f"{assets_with_issues} with issues: {', '.join(asset_names_with_issues)}")
                else:
                    message_parts.append(f"{assets_with_issues} with issues")
            else:
                message_parts.append(f"{assets_with_issues} with issues")
        if assets_offline > 0:
            message_parts.append(f"{assets_offline} offline")
        
        return format_success_response(
            summary,
            ". ".join(message_parts) + "."
        )
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


# Tool metadata for MCP protocol
schema = pydantic_to_json_schema(AssetStatusesParams)
TOOL_METADATA = {
    "name": "exosense-get-asset-statuses",
    "description": "Check asset health, connectivity, and status conditions across one or many assets. Use this tool DIRECTLY for questions about asset health - it automatically fetches assets internally if needed. You do NOT need to call get-assets first. Returns an aggregated health summary including: total assets checked, count of assets with issues, offline assets, problem categories, and example problems. By default, returns a concise summary without detailed asset lists. Set include_details=true when user asks for specific asset names or 'which assets have issues'. If asset_ids is not provided, automatically fetches and checks all assets (up to max_assets limit, default 100). IMPORTANT: asset_ids must be a list/array of strings, e.g. ['id1', 'id2'] or ['id1']. For a single asset, use ['asset_id'] not 'asset_id'. Ideal for questions like 'give me an overview of asset health', 'are there any error conditions?', or 'summarize problems with my assets'.",
    "inputSchema": schema
}
