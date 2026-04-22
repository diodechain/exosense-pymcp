"""RMS trend and anomaly detection for an asset's signal. Efficient GraphQL and compact LLM response."""

import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pydantic import Field, ValidationError
from ..graphql.assets import get_asset_signals_list, get_asset_signal_data
from .mcp_params import McpToolParams
from .types import ToolContext
from ._helpers import pydantic_to_json_schema, format_success_response, format_error_response


def _normalize_signal_ref(s: Optional[str]) -> str:
    """Normalize for comparison: strip, collapse unicode dashes/hyphens to ASCII."""
    if not s:
        return ""
    t = (s or "").strip()
    for c in ("\u2011", "\u2010", "\u2012", "\u2013", "\u2014", "\u2212"):
        t = t.replace(c, "-")
    return t


class SignalRmsTrendParams(McpToolParams):
    asset_id: str = Field(..., description="Asset UUID (required).")
    signal_id: Optional[str] = Field(None, description="Signal UUID or signal name (e.g. 'Moving Average RMS-X Front'). If omitted, returns list of signals.")
    duration_days: Optional[float] = Field(7.0, ge=0.1, le=365, description="Analysis window in days (default 7). Tell the LLM when defaulted.")
    rollup_interval_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=10080,
        description="If set, roll raw points into time buckets (e.g. 60 = hourly, 1440 = daily); RMS is over bucket means so result is independent of point frequency. Omit for raw-point RMS.",
    )


def _numeric_values(data: List[Dict]) -> List[float]:
    """Extract numeric values for RMS; skip non-numeric."""
    out = []
    for point in data or []:
        v = point.get("value")
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _rms(values: List[float]) -> float:
    if not values:
        return float("nan")
    return math.sqrt(sum(x * x for x in values) / len(values))


def _timestamp_sec(p: Dict[str, Any]) -> Optional[float]:
    """Parse point timestamp to seconds since epoch; return None if invalid."""
    ts = p.get("timestamp")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            t = float(ts)
            if t > 1e12:
                t = t / 1000.0
            return t
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _rollup_to_bucket_means(
    data: List[Dict[str, Any]],
    interval_minutes: int,
) -> Tuple[List[float], List[Any], int, int]:
    """Bucket points by time interval; return (bucket_means, bucket_timestamps, n_buckets, n_raw_points). Sorted by time."""
    interval_sec = interval_minutes * 60
    buckets: Dict[int, List[float]] = {}
    for p in data or []:
        t = _timestamp_sec(p)
        if t is None:
            continue
        v = p.get("value")
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        key = int(t // interval_sec) * interval_sec
        buckets.setdefault(key, []).append(val)
    if not buckets:
        return [], [], 0, 0
    n_raw = sum(len(vals) for vals in buckets.values())
    keys_sorted = sorted(buckets.keys())
    means = [sum(buckets[k]) / len(buckets[k]) for k in keys_sorted]
    timestamps = [k for k in keys_sorted]  # epoch sec; can be formatted by caller if needed
    return means, timestamps, len(means), n_raw


def _anomalies(values: List[float], timestamps: List[str], n_std: float = 2.5) -> List[Dict[str, Any]]:
    """Points where value deviates from mean by more than n_std standard deviations."""
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 0
    if std == 0:
        return []
    anomalies = []
    for i, v in enumerate(values):
        if abs(v - mean) > n_std * std:
            anomalies.append({
                "t": timestamps[i] if i < len(timestamps) else None,
                "value": round(v, 4),
                "deviation": round((v - mean) / std, 2) if std else 0,
            })
    return anomalies[:20]  # cap for compact response


async def execute(arguments: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
    try:
        args_in = dict(arguments)
        if args_in.get("duration_days") is None:
            args_in["duration_days"] = 7.0
        try:
            args = SignalRmsTrendParams(**args_in)
        except ValidationError as e:
            return format_error_response(Exception(f"Invalid arguments: {e}"))

        auth = context.session.get("authorization") if context.session else None
        import exosense_mcp.server as server_module
        client = server_module.get_exosense_client(auth)

        # No signal specified: return list of signals only (one light GraphQL call).
        if not args.signal_id or str(args.signal_id).strip().lower() in ("", "none"):
            query = get_asset_signals_list(args.asset_id)
            result = await client.query(query)
            assets = result.get("assets", []) or []
            if not assets:
                return format_success_response(
                    {"asset_id": args.asset_id, "signals": [], "message": "Asset not found or has no signals."},
                    "Asset not found or has no signals.",
                )
            asset = assets[0]
            signals = [{"id": s.get("id"), "name": s.get("name") or ""} for s in (asset.get("signals") or []) if s.get("id")]
            return format_success_response(
                {
                    "asset_id": args.asset_id,
                    "asset_name": asset.get("name") or "",
                    "signals": signals,
                    "message": "Specify signal_id to get RMS trend. Duration default: last 7 days if not set.",
                },
                f"Asset has {len(signals)} signal(s). Specify signal_id for RMS trend (default duration: 7 days).",
            )

        # Compute time range (default last 7 days; tell LLM we defaulted).
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.duration_days)
        start_ts = start.timestamp()
        end_ts = end.timestamp()
        duration_defaulted = arguments.get("duration_days") in (None, "")

        # One GraphQL call: limit per signal kept low (500) to avoid backend overload when asset has many signals.
        query = get_asset_signal_data(args.asset_id, data_limit=500)
        result = await client.query(query)
        assets = result.get("assets", []) or []
        if not assets:
            return format_success_response(
                {"asset_id": args.asset_id, "signal_id": args.signal_id, "rms": None, "message": "No asset or no data."},
                "No data for this asset.",
            )
        asset = assets[0]
        signals = asset.get("signals") or []
        ref = _normalize_signal_ref(args.signal_id)
        # Match by UUID or by signal name (user may pass "Moving Average RMS-X Front")
        signal = next(
            (s for s in signals if s.get("id") == args.signal_id or _normalize_signal_ref(s.get("name")) == ref),
            None,
        )
        if not signal:
            sig_list = [{"id": s.get("id"), "name": s.get("name") or ""} for s in signals if s.get("id")]
            return format_success_response(
                {"asset_id": args.asset_id, "signal_id": args.signal_id, "signals": sig_list, "message": "Signal not found. Use signal id or exact name from the list."},
                "Signal not found; use signal id or exact name from the list.",
            )
        raw_data = signal.get("data") or []
        # Filter to requested time window (API has no start/end)
        data = []
        for p in raw_data:
            ts = p.get("timestamp")
            if ts is None:
                continue
            try:
                if isinstance(ts, (int, float)):
                    t = float(ts)
                    if t > 1e12:
                        t = t / 1000.0  # milliseconds
                else:
                    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                if start_ts <= t <= end_ts:
                    data.append(p)
            except (ValueError, TypeError):
                continue
        data.sort(key=lambda x: (x.get("timestamp") or 0))
        timestamps = [p.get("timestamp") for p in data]
        values = _numeric_values(data)
        if not values:
            return format_success_response(
                {
                    "asset_id": args.asset_id,
                    "asset_name": asset.get("name") or "",
                    "signal_id": args.signal_id,
                    "signal_name": signal.get("name") or "",
                    "rms": None,
                    "n_points": 0,
                    "duration_days": args.duration_days,
                    "duration_defaulted": duration_defaulted,
                    "anomalies": [],
                    "message": "No numeric data in range.",
                },
                "No numeric signal data in range.",
            )

        if args.rollup_interval_minutes:
            bucket_means, bucket_ts, n_buckets, n_raw = _rollup_to_bucket_means(data, args.rollup_interval_minutes)
            if not bucket_means:
                return format_success_response(
                    {
                        "asset_id": args.asset_id,
                        "signal_id": args.signal_id,
                        "rms": None,
                        "rollup_interval_minutes": args.rollup_interval_minutes,
                        "message": "No data in buckets.",
                    },
                    "No data in roll-up buckets.",
                )
            rms_val = _rms(bucket_means)
            anomalies = _anomalies(bucket_means, bucket_ts)
            payload = {
                "asset_id": args.asset_id,
                "asset_name": asset.get("name") or "",
                "signal_id": args.signal_id,
                "signal_name": signal.get("name") or "",
                "rms": round(rms_val, 4),
                "n_buckets": n_buckets,
                "rollup_interval_minutes": args.rollup_interval_minutes,
                "n_raw_points": n_raw,
                "duration_days": args.duration_days,
                "duration_defaulted": duration_defaulted,
            }
            if anomalies:
                payload["anomalies"] = anomalies
                payload["anomaly_count"] = len(anomalies)
            else:
                payload["anomalies"] = []
            msg = f"RMS={rms_val:.4f} over {n_buckets} buckets ({args.rollup_interval_minutes} min roll-up, {n_raw} raw points, {args.duration_days} days)."
        else:
            rms_val = _rms(values)
            anomalies = _anomalies(values, timestamps)
            payload = {
                "asset_id": args.asset_id,
                "asset_name": asset.get("name") or "",
                "signal_id": args.signal_id,
                "signal_name": signal.get("name") or "",
                "rms": round(rms_val, 4),
                "n_points": len(values),
                "duration_days": args.duration_days,
                "duration_defaulted": duration_defaulted,
            }
            if anomalies:
                payload["anomalies"] = anomalies
                payload["anomaly_count"] = len(anomalies)
            else:
                payload["anomalies"] = []
            msg = f"RMS={rms_val:.4f} over {len(values)} points ({args.duration_days} days)."
        if duration_defaulted:
            msg += " Duration defaulted to last 7 days."
        if payload.get("anomalies"):
            msg += f" {len(payload['anomalies'])} anomaly(ies) in RMS data."
        return format_success_response(payload, msg)
    except Exception as error:
        return format_error_response(
            error if isinstance(error, Exception) else Exception(str(error))
        )


schema = pydantic_to_json_schema(SignalRmsTrendParams)
TOOL_METADATA = {
    "name": "exosense-signal-rms-trend",
    "description": "RMS trend and anomalies for an asset signal. Call with asset_id. signal_id can be the signal UUID or the signal name (e.g. 'Moving Average RMS-X Front'); omit to get a list of signals. duration_days defaults to 7 if omitted. Optional rollup_interval_minutes (e.g. 60=hourly, 1440=daily) rolls raw points into time buckets and computes RMS over bucket means so the result is independent of point frequency; omit for raw-point RMS. Returns: rms, n_points or n_buckets/n_raw_points when using roll-up, duration_days, anomalies.",
    "inputSchema": schema,
}
