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
    include_details: Optional[bool] = Field(False, description="MANDATORY: Set to true when user asks for asset NAMES, lists, 'how many/which assets reported on [date]?', 'reported today', or specific assets. Triggers: 'what are the names', 'which assets', 'reported on [date]', 'reported today', 'how many reported on X', 'successfully reported data on X', 'names of [condition] assets'. When true, includes last_heard per asset (needed for 'reported on date' questions) plus assets_with_issues_details, assets_by_category_level, assets_offline_details, assets_healthy_details. Default false for overview/summary only.")
    filter_category: Optional[str] = Field(None, description="Filter results to only include assets with issues in this category (e.g., 'timeout', 'default'). When provided, only assets with issues in this category will be included in the response. Use this to reduce data when asking about specific categories like 'critical assets in timeouts' - set filter_category='timeout' and filter_level='critical'.")
    filter_level: Optional[str] = Field(None, description="Filter results to only include assets with issues at this level (e.g., 'critical', 'warning', 'error', 'alarm'). Must be used with filter_category. When both are provided, only assets matching both category and level will be included. Use this to reduce data when asking about specific issues like 'critical assets in timeouts' - set filter_category='timeout' and filter_level='critical'.")


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
                    # 'None' or empty -> None
                    if asset_ids.lower() == 'none' or asset_ids == '':
                        arguments['asset_ids'] = None
                    else:
                        # LLMs often send comma-separated IDs; split so we get a real list (batch_size=1 then runs one ID per request)
                        parts = [p.strip() for p in asset_ids.split(",") if p and p.strip()]
                        arguments['asset_ids'] = parts if parts else [asset_ids]
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
            
            # Treat "all" / empty as no filter so LLMs don't accidentally get zero results
            if arguments.get("filter_category") is not None:
                fc = arguments["filter_category"]
                if fc == "" or (isinstance(fc, str) and fc.strip().lower() == "all"):
                    arguments["filter_category"] = None
            if arguments.get("filter_level") is not None:
                fl = arguments["filter_level"]
                if fl == "" or (isinstance(fl, str) and fl.strip().lower() == "all"):
                    arguments["filter_level"] = None
            
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
            # Fetch assets in smaller batches to avoid memory issues
            # Reduced from 100 to 50 to prevent "Exceeded allotted memory" errors
            batch_size = 50
            all_asset_ids = []
            offset = 0
            
            while len(all_asset_ids) < args.max_assets:
                context.log.info(f"Fetching batch at offset {offset}, limit {batch_size}")
                pagination = Pagination(limit=batch_size, offset=offset)
                # Use minimal options to reduce memory usage - only fetch id and name
                minimal_options = {
                    "includeTemplates": False,
                    "includeParent": False,
                    "includeMeta": False,
                    "includeLocation": False,
                    "includeData": False,
                }
                assets_query = get_assets(filters={}, options=minimal_options, pagination=pagination)
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
                # Use minimal options to reduce memory usage - only fetch id and name
                minimal_options = {
                    "ids": batch_ids,
                    "includeTemplates": False,
                    "includeParent": False,
                    "includeMeta": False,
                    "includeLocation": False,
                    "includeData": False,
                }
                assets_query = get_assets(filters={}, options=minimal_options, pagination=None)
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
        # example_problems removed - will be available via separate tool
        assets_with_issues_list = []  # Track which specific assets have issues
        assets_offline_list = []  # Track which specific assets are offline (only if they match filter)
        assets_healthy_list = []  # Track which specific assets are healthy
        # Track all problem categories (before filtering) for summary
        all_problem_categories = {}
        
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
            # Note: We'll only include offline assets in the response if they match the filter (or no filter)
            is_offline = False
            if not last_heard and not has_categories:
                is_offline = True
                has_issues = True
                issue_reasons.append("offline (no communication)")
            elif not last_heard:
                # Has status data but no last_heard - might be offline but has historical status
                is_offline = True
                issue_reasons.append("offline (no recent communication)")
            
            # Only count offline if no filter is applied, or if offline matches the filter
            if is_offline:
                if not args.filter_category and not args.filter_level:
                    # No filter - count all offline
                    assets_offline += 1
                    assets_offline_list.append({
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                        "last_heard": last_heard,
                    })
                elif args.filter_category == "offline":
                    # Filter is for offline - include it
                    assets_offline += 1
                    assets_offline_list.append({
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                        "last_heard": last_heard,
                    })
                # If filter is for a different category (e.g., timeout), don't count offline separately
            
            # Check categories for problems
            for cat in categories:
                category_name = cat.get("category", "unknown")
                values = cat.get("values", [])
                if values:
                    latest_value = values[0]
                    level = latest_value.get("level", "").lower()
                    
                    # Track problem categories (track all, but filter later if needed)
                    if category_name not in all_problem_categories:
                        all_problem_categories[category_name] = {"count": 0, "levels": {}}
                    all_problem_categories[category_name]["count"] += 1
                    
                    if level:
                        if level not in all_problem_categories[category_name]["levels"]:
                            all_problem_categories[category_name]["levels"][level] = 0
                        all_problem_categories[category_name]["levels"][level] += 1
                    
                    # Consider critical/error/warning levels as issues
                    if level in ["critical", "error", "warning", "alarm"]:
                        has_issues = True
                        issue_reasons.append(f"{category_name} ({level})")
                        # Example problems removed - will be available via separate tool
            
            # Track assets by status
            if has_issues:
                # Apply server-side filtering if filter_category and/or filter_level are specified
                should_include = True
                if args.filter_category or args.filter_level:
                    # Check if this asset matches the filter criteria
                    matches_category = False
                    matches_level = False
                    
                    # Check if asset has issues in the specified category
                    if args.filter_category:
                        # Check if any issue matches the category
                        for reason in issue_reasons:
                            if "(" in reason and ")" in reason:
                                category = reason.split("(")[0].strip()
                                if category == args.filter_category:
                                    matches_category = True
                                    # If filter_level is also specified, check level
                                    if args.filter_level:
                                        level = reason.split("(")[1].rstrip(")").strip()
                                        if level == args.filter_level:
                                            matches_level = True
                                            break
                                    else:
                                        # Category matches, no level filter
                                        matches_level = True
                                        break
                        should_include = matches_category and (not args.filter_level or matches_level)
                    elif args.filter_level:
                        # Only level filter (no category) - check if any issue has this level
                        for reason in issue_reasons:
                            if "(" in reason and ")" in reason:
                                level = reason.split("(")[1].rstrip(")").strip()
                                if level == args.filter_level:
                                    matches_level = True
                                    break
                        should_include = matches_level
                
                # Only include if it matches filters (or no filters specified)
                if should_include:
                    assets_with_issues += 1
                    # Build structured issue information for easier filtering
                    issue_details = []
                    category_levels = {}  # {category: [levels]}
                    for reason in issue_reasons:
                        # Parse "category (level)" format
                        if "(" in reason and ")" in reason:
                            parts = reason.split("(")
                            category = parts[0].strip()
                            level = parts[1].rstrip(")").strip()
                            if category not in category_levels:
                                category_levels[category] = []
                            category_levels[category].append(level)
                        issue_details.append({
                            "description": reason,
                            "category": reason.split("(")[0].strip() if "(" in reason else reason,
                            "level": reason.split("(")[1].rstrip(")").strip() if "(" in reason else None
                        })
                    
                    asset_info = {
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                        "issues": issue_reasons,  # Keep for backward compatibility
                        "issue_details": issue_details,  # Structured format
                        "categories": category_levels,  # Quick lookup: {category: [levels]}
                        "last_heard": last_heard,
                    }
                    assets_with_issues_list.append(asset_info)
                else:
                    # Asset has issues but doesn't match filter - don't count it at all when filtered
                    # Skip this asset entirely from the filtered view
                    pass
            elif has_categories or last_heard:
                # Only count as healthy if no filter is applied
                # When filtering, healthy assets that don't match the filter should be excluded
                if not args.filter_category and not args.filter_level:
                    assets_healthy += 1
                    assets_healthy_list.append({
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                    })
                # If filter is applied, don't count healthy assets (they don't match the filter)
            else:
                # No data but assume healthy if we have last_heard
                # Only count if no filter is applied
                if not args.filter_category and not args.filter_level:
                    assets_healthy += 1
                    assets_healthy_list.append({
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                    })
        
        # Apply filters to problem_categories if filters are set
        if args.filter_category or args.filter_level:
            # Only include the filtered category in problem_categories
            if args.filter_category and args.filter_category in all_problem_categories:
                problem_categories = {args.filter_category: all_problem_categories[args.filter_category].copy()}
                # If filter_level is set, further filter the levels
                if args.filter_level and args.filter_level in problem_categories[args.filter_category]["levels"]:
                    # Only show the filtered level
                    problem_categories[args.filter_category] = {
                        "count": problem_categories[args.filter_category]["levels"][args.filter_level],
                        "levels": {args.filter_level: problem_categories[args.filter_category]["levels"][args.filter_level]}
                    }
            else:
                # Filter category not found in results
                problem_categories = {}
        else:
            # No filter - use all categories
            problem_categories = all_problem_categories
        
        # Adjust counts when filters are applied
        if args.filter_category or args.filter_level:
            # When filtered, counts should reflect only filtered assets
            # Only count assets that match the filter (assets_with_issues)
            total_checked = assets_with_issues
            assets_healthy = 0  # Don't count healthy assets when filtering - they don't match
            # assets_offline is already adjusted (only counted if matches filter)
        
        # Build summary response
        summary = {
            "total_assets_checked": total_checked,
            "assets_with_issues": assets_with_issues,
            "assets_offline": assets_offline,
            "assets_healthy": assets_healthy,
            "problem_categories": problem_categories if problem_categories else None,
        }
        
        # Cap detail lists so response stays under ~4k chars; counts above are already full totals
        MAX_DETAIL_ENTRIES = 5
        if args.include_details:
            if assets_with_issues_list:
                summary["assets_with_issues_details"] = assets_with_issues_list[:MAX_DETAIL_ENTRIES]
                if len(assets_with_issues_list) > MAX_DETAIL_ENTRIES:
                    summary["assets_with_issues_total"] = len(assets_with_issues_list)
                # Add a helper field for filtering by category/level
                if not args.filter_category and not args.filter_level:
                    assets_by_category_level = {}
                    for asset in assets_with_issues_list[:MAX_DETAIL_ENTRIES]:
                        categories = asset.get("categories", {})
                        for category, levels in categories.items():
                            if category not in assets_by_category_level:
                                assets_by_category_level[category] = {}
                            for level in levels:
                                if level not in assets_by_category_level[category]:
                                    assets_by_category_level[category][level] = []
                                assets_by_category_level[category][level].append({
                                    "asset_id": asset["asset_id"],
                                    "asset_name": asset["asset_name"]
                                })
                    if assets_by_category_level:
                        summary["assets_by_category_level"] = assets_by_category_level
                else:
                    summary["filter_applied"] = {
                        "category": args.filter_category,
                        "level": args.filter_level
                    }
            if assets_offline_list and (not args.filter_category or args.filter_category == "offline"):
                summary["assets_offline_details"] = assets_offline_list[:MAX_DETAIL_ENTRIES]
                if len(assets_offline_list) > MAX_DETAIL_ENTRIES:
                    summary["assets_offline_total"] = len(assets_offline_list)
            if assets_healthy_list and not args.filter_category and not args.filter_level:
                summary["assets_healthy_details"] = assets_healthy_list[:MAX_DETAIL_ENTRIES]
                if len(assets_healthy_list) > MAX_DETAIL_ENTRIES:
                    summary["assets_healthy_total"] = len(assets_healthy_list)
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
            # When details are included and user asks about offline assets, list them in message
            if args.include_details and assets_offline_list:
                offline_names = [a["asset_name"] for a in assets_offline_list]
                if len(offline_names) <= 10:  # List up to 10 offline assets in message
                    message_parts.append(f"{assets_offline} offline: {', '.join(offline_names)}")
                else:
                    message_parts.append(f"{assets_offline} offline (see assets_offline_details for full list)")
            else:
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
    "description": "CALL THIS when the user asks 'how many assets reported on [date]?', 'reported today', 'which assets reported on X?', or 'successfully reported data on X' — do not say you lack data without calling. Omit asset_ids so the tool fetches assets (set max_assets as needed, e.g. 500); set include_details=true to get last_heard (ISO timestamp) per asset, then filter by date and count. Also use for: 'how long has X had issues?', 'duration of the issue' (last_heard in response), offline/healthy lists, or when given specific asset_ids. For overview counts only prefer exosense-asset-health-summary. For 'which assets have issues?' prefer exosense-asset-issues-list.",
    "inputSchema": schema
}
