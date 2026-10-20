"""Opt-in end-to-end smoke check against a RUNNING Django backend.

This intentionally calls the real TomTom/Open-Meteo integrations. It does not
store keys and never assumes that the provider can return three routes.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SmokeError(Exception):
    """A readable smoke-test failure without leaking provider responses."""


def fetch_json(base_url, path, payload=None, timeout=180):
    url = f"{base_url.rstrip('/')}{path}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST" if body is not None else "GET",
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            message = {}
        explanation = (message.get("error") or message.get("errors")
                       if isinstance(message, dict) else None)
        raise SmokeError(f"{path} returned HTTP {exc.code}: {str(explanation or 'Provider/API error')[:300]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeError(f"Cannot reach {path}: {type(exc).__name__}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise SmokeError(f"{path} did not return valid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError(f"{path} returned a non-object response")
    return result


def analyze_response(data):
    """Check the documented frontend API contract without assuming fair weather.

    Returns (errors, warnings, report) for testing and for human-readable output.
    """
    errors, warnings = [], []
    routes = data.get("routes")
    if not isinstance(routes, list) or not 1 <= len(routes) <= 3:
        return ["Expected 1–3 genuine displayed routes."], warnings, {}

    recommended = data.get("recommended_route_id")
    flags = []
    ids = []
    route_stats = []
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            errors.append(f"Route {index + 1} is not an object")
            continue
        rid = route.get("id")
        ids.append(rid)
        cps = route.get("checkpoints")
        summary = route.get("risk_summary")
        if not isinstance(cps, list) or len(cps) < 2:
            errors.append(f"Route {index + 1} has insufficient checkpoints")
            continue
        if not isinstance(summary, dict):
            errors.append(f"Route {index + 1} lacks a risk summary")
            continue
        miles = [cp.get("mile") for cp in cps if isinstance(cp, dict)]
        if (len(miles) != len(cps) or any(not isinstance(n, (int, float)) or isinstance(n, bool)
              for n in miles) or any(b <= a for a, b in zip(miles, miles[1:]))):
            errors.append(f"Route {index + 1} checkpoints are not in increasing mile order")
        status = summary.get("status")
        if status not in ("eligible", "incomplete", "no_travel"):
            errors.append(f"Route {index + 1} has an invalid risk status")
        recommended_flag = route.get("is_recommended") is True
        if recommended_flag:
            flags.append(rid)
            if status != "eligible":
                errors.append(f"Route {index + 1} was recommended despite {status} status")
        for cp in cps:
            if not isinstance(cp, dict) or not isinstance(cp.get("risk"), dict):
                errors.append(f"Route {index + 1} contains a checkpoint without risk data")
                break
        route_stats.append({
            "name": route.get("name", f"Route {index + 1}"),
            "miles": route.get("distance_miles"),
            "minutes": route.get("duration_minutes"),
            "risk_status": status,
            "severe_miles": summary.get("severe_miles"),
            "high_miles": summary.get("high_miles"),
            "coverage_percent": summary.get("coverage_percent"),
            "checkpoints": len(cps),
        })

    if len(ids) != len(set(ids)):
        errors.append("Displayed route IDs are not unique")
    if recommended is None:
        if flags:
            errors.append("One or more routes are flagged recommended but recommended_route_id is null")
        if any(item.get("risk_status") == "eligible" for item in route_stats):
            errors.append("Eligible routes are present but recommendation is null")
    elif recommended not in ids or flags != [recommended]:
        errors.append("Recommendation ID and route recommendation flags disagree")

    summary = data.get("weather_summary")
    if not isinstance(summary, dict):
        errors.append("Missing weather_summary")
        summary = {}
    available, total = summary.get("available"), summary.get("total")
    if (not isinstance(total, int) or isinstance(total, bool) or not isinstance(available, int)
            or isinstance(available, bool) or not 0 <= available <= total):
        errors.append("Weather availability counts are inconsistent")
    heatmap = data.get("heatmap")
    if not isinstance(heatmap, dict) or heatmap.get("hour_count") != 49:
        errors.append("Heatmap must have 49 positions (hour 0 through 48)")
    else:
        samples = heatmap.get("samples")
        if not isinstance(samples, list):
            errors.append("Heatmap samples must be an array")
        elif any(not isinstance(s, dict) or not isinstance(s.get("hours"), list)
                 or len(s["hours"]) != 49 for s in samples):
            errors.append("At least one heatmap sample does not contain 49 hourly values")

    if len(routes) < 3:
        warnings.append(f"Only {len(routes)} usable routes returned; check route_warning and TomTom options")
    for warning_field in ("route_warning", "weather_warning"):
        if data.get(warning_field):
            warnings.append(f"{warning_field}: {data[warning_field]}")
    return errors, warnings, {"routes": route_stats, "recommendation_id": recommended,
                              "weather_available": available, "weather_total": total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--departure", required=True, help="YYYY-MM-DDTHH:MM in origin local time")
    parser.add_argument("--load-weight", required=True, type=int, help="Cargo/load weight in lb")
    parser.add_argument("--spacing", type=int, default=50, choices=(10, 25, 50))
    parser.add_argument("--timeout", type=int, default=240, help="Timeout per request in seconds")
    parser.add_argument("--save", type=Path, help="Optional JSON output; contains trip locations")
    parser.add_argument("--confirm-live", action="store_true", help="Required: API calls may consume quota")
    args = parser.parse_args(argv)
    if not args.confirm_live:
        parser.error("Add --confirm-live to acknowledge real TomTom/Open-Meteo calls")
    try:
        datetime.strptime(args.departure, "%Y-%m-%dT%H:%M")
    except ValueError:
        parser.error("--departure must use YYYY-MM-DDTHH:MM")
    if args.load_weight < 1 or args.timeout < 1:
        parser.error("--load-weight and --timeout must be positive")
    payload = {"origin": args.origin, "destination": args.destination,
               "departure_time": args.departure, "load_weight_lb": args.load_weight,
               "checkpoint_miles": args.spacing}
    try:
        health = fetch_json(args.base_url, "/api/health/", timeout=10)
        if health.get("status") != "ok":
            raise SmokeError("Backend health endpoint did not report ok")
        validated = fetch_json(args.base_url, "/api/trips/validate/", payload, timeout=10)
        if "trip" not in validated:
            raise SmokeError("Validation did not return a normalized trip")
        started = perf_counter()
        response = fetch_json(args.base_url, "/api/routes/", payload, timeout=args.timeout)
        elapsed = perf_counter() - started
        errors, warnings, report = analyze_response(response)
        print(f"Live routing API elapsed: {elapsed:.2f}s")
        print(f"Routes returned: {len(report.get('routes', []))}")
        for route in report.get("routes", []):
            print(f"  {route['name']}: {route['miles']} mi; {route['minutes']} min; "
                  f"risk={route['risk_status']}; severe={route['severe_miles']} mi; "
                  f"high={route['high_miles']} mi; coverage={route['coverage_percent']}%; "
                  f"checkpoints={route['checkpoints']}")
        print(f"Recommended route ID: {report.get('recommendation_id')}")
        print(f"Weather available: {report.get('weather_available')} / {report.get('weather_total')}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if args.save:
            args.save.write_text(json.dumps(response, indent=2), encoding="utf-8")
            print(f"Full API response saved locally to {args.save} (contains trip locations)")
        if errors:
            return 1
        print("PASS: API contract and basic route safety checks")
        return 0
    except SmokeError as exc:
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
