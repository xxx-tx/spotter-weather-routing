"""Get truck routes and locations from TomTom."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
from math import isfinite
from time import perf_counter
from urllib.parse import quote

import requests

TOMTOM_BASE = "https://api.tomtom.com"
logger = logging.getLogger(__name__)
# Limit checkpoint/forecast costs even when TomTom returns many alternatives.
ROUTE_CANDIDATE_LIMIT = 6
MAX_ROUTE_VERTICES = 30000
MAX_ROUTE_METERS = 10000 * 1609.344


def _finite_number(value, minimum=0, maximum=float("inf")):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and minimum <= value <= maximum)


def _valid_position(lat, lon):
    return _finite_number(lat, -90, 90) and _finite_number(lon, -180, 180)


def _route_times(summary):
    departure, arrival = summary.get("departureTime"), summary.get("arrivalTime")
    if not isinstance(departure, str) or not isinstance(arrival, str):
        return None
    try:
        start = datetime.fromisoformat(departure.replace("Z", "+00:00"))
        end = datetime.fromisoformat(arrival.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.utcoffset() is None or end.utcoffset() is None or end < start:
        return None
    return departure, arrival



class TomTomError(Exception):
    """Safe user-facing TomTom API error."""


def tomtom_get(url, params):
    try:
        response = requests.get(url, params=params, timeout=25)

        if response.status_code in (401, 403):
            raise TomTomError("TomTom API key is invalid or lacks permission.")
        if response.status_code == 429:
            raise TomTomError("TomTom rate limit reached. Try again later.")
        if response.status_code >= 400:
            raise TomTomError(f"TomTom returned HTTP {response.status_code}.")

        return response.json()

    except requests.Timeout as exc:
        raise TomTomError("TomTom request timed out.") from exc
    except requests.RequestException as exc:
        raise TomTomError("Cannot connect to the TomTom service.") from exc
    except ValueError as exc:
        raise TomTomError("Invalid response from TomTom.") from exc


def geocode_address(address, api_key):
    encoded = quote(address, safe="")
    url = f"{TOMTOM_BASE}/search/2/geocode/{encoded}.json"
    data = tomtom_get(url, {"key": api_key, "limit": 1})
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise TomTomError("Invalid geocoding response from TomTom.")
    results = data["results"]
    if not results:
        raise TomTomError(f"Location not found: {address}")

    result = results[0]
    if not isinstance(result, dict) or not isinstance(result.get("position"), dict):
        raise TomTomError("Invalid geocoding response from TomTom.")
    position = result["position"]
    lat, lon = position.get("lat"), position.get("lon")
    if not _valid_position(lat, lon):
        raise TomTomError("Invalid geocoding coordinates from TomTom.")
    address_details = result.get("address")
    name = (address_details.get("freeformAddress")
            if isinstance(address_details, dict) else None)
    return {
        "name": name if isinstance(name, str) and name.strip() else address,
        "lat": lat,
        "lon": lon,
    }



def _timing_progress(raw_route, distance_meters, duration_seconds):
    """Validate TomTom's cumulative distance/time progress anchors.

    The provider's `progress` values are not guaranteed on every response.
    Reject partial or inconsistent progress instead of using misleading ETAs;
    create_checkpoints then falls back to distance-proportional timing.
    """
    raw_progress = raw_route.get("progress")
    if not isinstance(raw_progress, list) or len(raw_progress) < 2:
        return None

    anchors = []
    previous_index = -1
    for point in raw_progress:
        if not isinstance(point, dict):
            return None
        index = point.get("pointIndex")
        distance = point.get("distanceInMeters")
        elapsed = point.get("travelTimeInSeconds")
        if (isinstance(index, bool) or not isinstance(index, int)
                or index <= previous_index):
            return None
        if not _finite_number(distance) or not _finite_number(elapsed):
            return None
        if anchors and (distance <= anchors[-1][0] or elapsed < anchors[-1][1]):
            return None
        anchors.append((float(distance), float(elapsed)))
        previous_index = index

    # Both endpoints must refer to the route summary. Small rounding
    # differences are acceptable, but substantial disagreement is not.
    first_distance, first_elapsed = anchors[0]
    last_distance, last_elapsed = anchors[-1]
    if (first_distance > 1 or first_elapsed > 1
            or abs(last_distance - distance_meters) > 5
            or abs(last_elapsed - duration_seconds) > 2):
        return None

    # Snap slightly rounded provider endpoints to the authoritative summary.
    anchors[0] = (0.0, 0.0)
    anchors[-1] = (float(distance_meters), float(duration_seconds))
    if any(b[0] <= a[0] or b[1] < a[1]
           for a, b in zip(anchors, anchors[1:])):
        return None
    return anchors


def _process_route(raw_route):
    """Convert one raw TomTom route into our stable frontend API format.

    Return None when essential route fields are missing.
    """
    try:
        summary = raw_route["summary"]
        distance_meters = summary["lengthInMeters"]
        duration_seconds = summary["travelTimeInSeconds"]
        if (not _finite_number(distance_meters, 0.001, MAX_ROUTE_METERS)
                or not _finite_number(duration_seconds, 0, 16 * 24 * 3600)):
            return None
        times = _route_times(summary)
        if times is None:
            return None
        if not isinstance(raw_route["legs"], list):
            return None

        geometry = []
        # TomTom progress.pointIndex refers to raw route points. Track the
        # original indices while removing duplicate vertices from our polyline.
        raw_index_to_geometry = []
        for leg in raw_route["legs"]:
            if not isinstance(leg, dict) or not isinstance(leg.get("points"), list):
                return None
            for point in leg["points"]:
                if not isinstance(point, dict):
                    return None
                lon, lat = point.get("longitude"), point.get("latitude")
                if not _valid_position(lat, lon):
                    return None
                coordinate = [lon, lat]
                if not geometry or geometry[-1] != coordinate:
                    geometry.append(coordinate)
                    if len(geometry) > MAX_ROUTE_VERTICES:
                        return None
                raw_index_to_geometry.append(len(geometry) - 1)

        if len(geometry) < 2:
            return None
        departure, arrival = times

        route = {
            "id": None,
            "name": None,
            "distance_meters": distance_meters,
            "distance_miles": round(distance_meters / 1609.344, 1),
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_seconds / 60),
            "departure_time": departure,
            "arrival_time": arrival,
            "geometry": geometry,
        }
        progress = _timing_progress(raw_route, distance_meters, duration_seconds)
        if progress is not None:
            # Internal-only data: removed before the API response is sent.
            route["_timing_progress"] = progress

            # Preserve index-anchored road distances as well as travel times.
            # This allows checkpoint *positions*, not only ETAs, to use the
            # provider's cumulative road distance. If raw indices and the
            # deduplicated geometry cannot be aligned, keep ETA improvements
            # but fall back to geometry-based checkpoint positions.
            raw_anchors = raw_route["progress"]
            indices = [point["pointIndex"] for point in raw_anchors]
            if (indices[0] == 0
                    and indices[-1] == len(raw_index_to_geometry) - 1
                    and all(0 <= index < len(raw_index_to_geometry)
                            for index in indices)):
                geometry_anchors = [
                    (raw_index_to_geometry[index], distance)
                    for index, (distance, _elapsed) in zip(indices, progress)
                ]
                if all(b[0] > a[0] for a, b in
                       zip(geometry_anchors, geometry_anchors[1:])):
                    route["_geometry_progress"] = geometry_anchors
        return route
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def calculate_truck_routes(origin, destination, departure_time, api_key, max_routes=3):
    """Fetch up to `max_routes` genuine TomTom truck routes.

    By default keep the existing three-route contract. The trip-planning
    endpoint asks for a bounded pool of six candidates to evaluate weather
    before it chooses the three options shown to the driver.
    """
    if isinstance(max_routes, bool) or not isinstance(max_routes, int) or not 1 <= max_routes <= ROUTE_CANDIDATE_LIMIT:
        raise ValueError("max_routes must be between 1 and 6.")
    started = perf_counter()
    locations = (
        f"{origin['lat']},{origin['lon']}:"
        f"{destination['lat']},{destination['lon']}"
    )
    url = f"{TOMTOM_BASE}/routing/1/calculateRoute/{locations}/json"

    params = {
        "key": api_key,
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "traffic": "true",
        "maxAlternatives": 2,
        "alternativeType": "anyRoute",
        "routeRepresentation": "polyline",
        # requests serializes a list as two repeated query parameters.
        "extendedRouteRepresentation": ["distance", "travelTime"],
        "departAt": f"{departure_time}:00",
    }
    strategies = ("fastest", "short", "eco")

    def fetch_strategy(strategy):
        # A separate params dict prevents requests sharing mutable state.
        strategy_params = {**params, "routeType": strategy}
        return tomtom_get(url, strategy_params)

    responses = {}
    failures = {}

    # I/O-bound HTTP calls can overlap; route selection below stays deterministic.
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fetch_strategy, strategy): strategy
            for strategy in strategies
        }
        for future in as_completed(futures):
            strategy = futures[future]
            try:
                responses[strategy] = future.result()
            except TomTomError as exc:
                failures[strategy] = exc
                logger.warning("TomTom %s strategy failed: %s", strategy, exc)

    # Retain every valid route returned by each strategy. TomTom may return
    # a main route plus alternatives in a single strategy response.
    candidates_by_strategy = {}
    for strategy in strategies:
        response = responses.get(strategy)
        raw_routes = response.get("routes") if isinstance(response, dict) else None
        if not isinstance(raw_routes, list):
            if response is not None:
                logger.warning("TomTom %s strategy returned an invalid route list.", strategy)
            raw_routes = []
        candidates_by_strategy[strategy] = [
            route for raw in raw_routes
            if (route := _process_route(raw)) is not None
        ]

    seen_geometry = set()
    routes = []

    def add_distinct_route(route):
        signature = tuple(
            (round(lon, 4), round(lat, 4))
            for lon, lat in route["geometry"]
        )
        if signature in seen_geometry:
            return False
        seen_geometry.add(signature)
        routes.append(route)
        return True

    # First pass: aim for one distinct representative per strategy.
    for strategy in strategies:
        if len(routes) >= max_routes:
            break
        for candidate in candidates_by_strategy[strategy]:
            if add_distinct_route(candidate):
                break

    # Second pass: fill remaining slots from TomTom's genuine alternatives.
    # Previously these routes were discarded, even when fewer than 3
    # options were displayed to the driver.
    if len(routes) < max_routes:
        for strategy in strategies:
            for candidate in candidates_by_strategy[strategy]:
                if len(routes) >= max_routes:
                    break
                add_distinct_route(candidate)
            if len(routes) >= max_routes:
                break

    if not routes:
        if failures and len(failures) == len(strategies):
            # Avoid reporting "no routes" when the actual problem is an API outage.
            raise TomTomError(
                "All TomTom routing strategies failed. Please try again."
            )
        raise TomTomError("No usable truck routes were returned by TomTom.")

    routes.sort(key=lambda route: route["duration_seconds"])
    for index, route in enumerate(routes):
        route["id"] = index
        route["name"] = f"Route {index + 1}"

    logger.info(
        "TomTom truck routing completed in %.2fs; %d routes; %d failed strategies",
        perf_counter() - started,
        len(routes),
        len(failures),
    )
    return routes


def get_trip_routes(trip, api_key):
    origin = geocode_address(trip["origin"], api_key)
    destination = geocode_address(trip["destination"], api_key)
    routes = calculate_truck_routes(
        origin, destination, trip["departure_time"], api_key,
        max_routes=ROUTE_CANDIDATE_LIMIT,
    )
    return {
        "trip": trip,
        "origin": origin,
        "destination": destination,
        "routes": routes,
    }
