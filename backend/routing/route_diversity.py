"""Conservative detection of nearly identical road corridors.

This is deliberately a *display* filter, not a routing or safety filter.
Every TomTom candidate is weather-scored before it can be de-emphasized.
The geometry comparison uses uniformly spaced samples rather than provider
vertex equality, which varies with polyline densification.
"""

from bisect import bisect_left
from math import ceil, cos, floor, hypot, isfinite, pi

# Require near-total overlap; small detours may have different weather.
OVERLAP_THRESHOLD = 0.985
PROXIMITY_METERS = 750.0
SAMPLE_SPACING_METERS = 800.0
MAX_SAMPLES = 1200


def _sample_geometry(geometry, reference_lat):
    """Sample a WGS84 polyline approximately uniformly in projected meters."""
    if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
        return None
    scale_lon = 111_195 * cos(reference_lat * pi / 180)
    if scale_lon < 1:
        return None
    points = []
    for item in geometry:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        lon, lat = item
        if (isinstance(lon, bool) or isinstance(lat, bool)
                or not isinstance(lon, (int, float))
                or not isinstance(lat, (int, float))
                or not isfinite(lon) or not isfinite(lat)
                or not -180 <= lon <= 180 or not -90 <= lat <= 90):
            return None
        point = (lon * scale_lon, lat * 111_195)
        if not points or points[-1] != point:
            points.append(point)
    if len(points) < 2:
        return None

    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + hypot(b[0] - a[0], b[1] - a[1]))
    total = cumulative[-1]
    if total <= 0:
        return None
    count = min(MAX_SAMPLES, max(2, ceil(total / SAMPLE_SPACING_METERS) + 1))
    samples = []
    for index in range(count):
        position = index * total / (count - 1)
        segment = min(max(1, bisect_left(cumulative, position)), len(points) - 1)
        a, b = points[segment - 1], points[segment]
        fraction = (position - cumulative[segment - 1]) / (
            cumulative[segment] - cumulative[segment - 1]
        )
        samples.append((a[0] + (b[0] - a[0]) * fraction,
                        a[1] + (b[1] - a[1]) * fraction))
    return samples


def _nearby_fraction(samples, others):
    """Measure what fraction of one road's sampled points lie near the other."""
    cell_size = PROXIMITY_METERS
    grid = {}
    for x, y in others:
        cell = (floor(x / cell_size), floor(y / cell_size))
        grid.setdefault(cell, []).append((x, y))

    matches = 0
    for x, y in samples:
        cell_x, cell_y = floor(x / cell_size), floor(y / cell_size)
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if any(hypot(x - ox, y - oy) <= PROXIMITY_METERS
                       for ox, oy in grid.get((cell_x + dx, cell_y + dy), ())):
                    found = True
                    break
            if found:
                break
        matches += found
    return matches / len(samples)


def are_near_duplicate_routes(left, right):
    """True only when routes have extremely similar distance AND geometry.

    Unknown/missing geometry never proves equivalence. The symmetric check
    prevents a short branch of one route from being hidden by a longer one.
    """
    length_a, length_b = left.get("distance_meters"), right.get("distance_meters")
    if (any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not isfinite(v) or v <= 0 for v in (length_a, length_b))
            or abs(length_a - length_b) > 0.03 * max(length_a, length_b)):
        return False
    geometry_a, geometry_b = left.get("geometry"), right.get("geometry")
    if not geometry_a or not geometry_b:
        return False
    try:
        reference_lat = (geometry_a[0][1] + geometry_a[-1][1] +
                         geometry_b[0][1] + geometry_b[-1][1]) / 4
    except (TypeError, IndexError, KeyError):
        return False
    if not isinstance(reference_lat, (int, float)) or not isfinite(reference_lat):
        return False
    sample_a = _sample_geometry(geometry_a, reference_lat)
    sample_b = _sample_geometry(geometry_b, reference_lat)
    if sample_a is None or sample_b is None:
        return False
    return (_nearby_fraction(sample_a, sample_b) >= OVERLAP_THRESHOLD
            and _nearby_fraction(sample_b, sample_a) >= OVERLAP_THRESHOLD)
