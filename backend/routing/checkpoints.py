import math
from bisect import bisect_left
from datetime import datetime, timedelta


EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(point_a, point_b):
    """Distance between two [longitude, latitude] points."""

    lon1, lat1 = point_a
    lon2, lat2 = point_b

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    delta_lat = lat2 - lat1
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return (
        2
        * EARTH_RADIUS_MILES
        * math.asin(min(1.0, math.sqrt(a)))
    )


def cumulative_geometry_miles(geometry):
    """Measure the route line once for fast checkpoint lookup."""
    distances = [0.0]
    for start, end in zip(geometry, geometry[1:]):
        distances.append(distances[-1] + haversine_miles(start, end))
    return distances


def interpolate_position(geometry, fraction, distances=None):
    """Find a point along the drawn route."""
    if fraction <= 0:
        return geometry[0]
    if fraction >= 1:
        return geometry[-1]
    distances = distances if distances is not None else cumulative_geometry_miles(geometry)
    if distances[-1] <= 0:
        raise ValueError("Route geometry has zero length.")
    return _position_at_road_distance(geometry, distances, fraction * distances[-1])



def _elapsed_seconds_at_mile(mile, route, distance_miles, progress_distances):
    """Interpolate provider travel time at a cumulative *road* distance.

    Progress anchors account for TomTom's varying travel speeds, unlike
    distance / total distance. Preserve the original approximation when
    usable provider progress is unavailable.
    """
    fraction = mile / distance_miles
    progress = route.get("_timing_progress")
    if not progress:
        return route["duration_seconds"] * fraction

    if mile <= 0:
        return 0.0
    if mile >= distance_miles:
        return route["duration_seconds"]

    target_meters = mile * 1609.344
    index = bisect_left(progress_distances, target_meters)
    if index <= 0 or index >= len(progress):
        return route["duration_seconds"] * fraction

    d0, t0 = progress[index - 1]
    d1, t1 = progress[index]
    return t0 + (target_meters - d0) / (d1 - d0) * (t1 - t0)


def _vertex_road_distances(geometry, anchors):
    """Map TomTom's cumulative road distances onto polyline vertices.

    Progress is sparse: each anchor associates road mileage with a route point
    index. Per TomTom's specification, distribute distance between consecutive
    anchors in proportion to great-circle lengths along that polyline section.
    Return None when progress cannot be reconciled with the actual geometry.
    """
    if not isinstance(anchors, list) or len(anchors) < 2:
        return None

    vertex_count = len(geometry)
    try:
        if anchors[0][0] != 0 or anchors[-1][0] != vertex_count - 1:
            return None
        if any(not isinstance(index, int) or isinstance(index, bool)
               or not 0 <= index < vertex_count
               or not isinstance(distance, (float, int))
               or not math.isfinite(distance)
               for index, distance in anchors):
            return None
        if any(i1 <= i0 or d1 <= d0 for (i0, d0), (i1, d1)
               in zip(anchors, anchors[1:])):
            return None
    except (TypeError, ValueError, IndexError):
        return None

    cumulative_geometry = [0.0]
    for a, b in zip(geometry, geometry[1:]):
        cumulative_geometry.append(
            cumulative_geometry[-1] + haversine_miles(a, b)
        )

    distances = [0.0] * vertex_count
    for (i0, d0), (i1, d1) in zip(anchors, anchors[1:]):
        section_length = cumulative_geometry[i1] - cumulative_geometry[i0]
        if section_length <= 0:
            return None
        for index in range(i0, i1 + 1):
            fraction = (
                cumulative_geometry[index] - cumulative_geometry[i0]
            ) / section_length
            distances[index] = d0 + fraction * (d1 - d0)

    if any(b <= a for a, b in zip(distances, distances[1:])):
        return None
    return distances


def _position_at_road_distance(geometry, cumulative_meters, target_meters):
    """Interpolate a road-distance checkpoint without leaving the polyline."""
    if target_meters <= 0:
        return geometry[0]
    if target_meters >= cumulative_meters[-1]:
        return geometry[-1]

    index = bisect_left(cumulative_meters, target_meters)
    if cumulative_meters[index] == target_meters:
        return geometry[index]
    before, after = cumulative_meters[index - 1], cumulative_meters[index]
    fraction = (target_meters - before) / (after - before)
    start, end = geometry[index - 1], geometry[index]
    return [
        start[0] + fraction * (end[0] - start[0]),
        start[1] + fraction * (end[1] - start[1]),
    ]


def create_checkpoints(route, spacing_miles=50):
    """
    Generate checkpoints along a route.

    Always include origin and destination.
    Prefer TomTom's distance/time progress when available; otherwise
    estimate ETAs proportionally to distance as before.
    """

    if spacing_miles not in (10, 25, 50):
        raise ValueError("Spacing must be 10, 25, or 50 miles.")

    geometry = route["geometry"]
    distance_miles = route["distance_meters"] / 1609.344

    if (len(geometry) < 2 or not math.isfinite(distance_miles)
            or distance_miles <= 0 or len(geometry) > 30000):
        raise ValueError("Invalid route geometry or distance.")

    departure_value = route.get("departure_time")

    if not departure_value:
        raise ValueError("Route departure time is missing.")

    departure = datetime.fromisoformat(
        departure_value.replace("Z", "+00:00")
    )

    if departure.utcoffset() is None:
        raise ValueError(
            "Route departure time must include a UTC offset."
        )

    # Origin, intermediate checkpoints, destination.
    distances = [0.0]

    number_of_steps = math.floor(distance_miles / spacing_miles)
    if number_of_steps > 500:
        raise ValueError("Too many checkpoints for a single route.")

    for step in range(1, number_of_steps + 1):
        mile = step * spacing_miles

        if mile < distance_miles:
            distances.append(float(mile))

    distances.append(distance_miles)

    checkpoints = []
    progress_distances = [distance for distance, _ in route.get("_timing_progress", [])]
    vertex_road_distances = _vertex_road_distances(
        geometry, route.get("_geometry_progress")
    )
    geometry_distances = (
        None if vertex_road_distances is not None else cumulative_geometry_miles(geometry)
    )

    for index, mile in enumerate(distances):
        fraction = mile / distance_miles

        if vertex_road_distances is not None:
            position = _position_at_road_distance(
                geometry, vertex_road_distances, mile * 1609.344
            )
        else:
            # Preserve backwards compatibility with providers that do not
            # return usable index-anchored road distances.
            position = interpolate_position(geometry, fraction, geometry_distances)

        elapsed_seconds = _elapsed_seconds_at_mile(
            mile, route, distance_miles, progress_distances
        )

        eta = departure + timedelta(
            seconds=elapsed_seconds
        )

        checkpoints.append({
            "id": index,
            "mile": mile,
            "lat": round(position[1], 6),
            "lon": round(position[0], 6),
            "eta": eta.isoformat(),
            "weather": None,
        })

    return checkpoints