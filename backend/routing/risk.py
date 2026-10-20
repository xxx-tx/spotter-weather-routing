from math import isfinite

from .route_diversity import are_near_duplicate_routes


RISK_LEVELS = (
    "Low",
    "Moderate",
    "High",
    "Severe",
    "No Travel",
)

ALL_LEVELS = (*RISK_LEVELS, "Unknown")


def _valid_number(value):
    """Accept only finite, nonnegative numeric readings."""

    if isinstance(value, bool) or not isinstance(
        value, (int, float)
    ):
        return None

    number = float(value)

    if not isfinite(number) or number < 0:
        return None

    return number


def _score(value, thresholds, strict_top=False):
    if value is None:
        return None
    for score, limit in reversed(list(enumerate(thresholds, start=1))):
        above_limit = value > limit if strict_top and score == 4 else value >= limit
        if above_limit:
            return score
    return 0


def classify_checkpoint(weather, load_weight_lb):
    """Use the worst known risk. Missing data stays Unknown."""
    if not isinstance(weather, dict):
        return {"level": "Unknown", "score": None, "reason": "Forecast unavailable"}

    wind = _valid_number(weather.get("wind_mph"))
    rain = _valid_number(weather.get("rain_in_hr"))
    snow = _valid_number(weather.get("snow_in_hr"))

    wind_score = _score(wind, (25, 35, 45, 55))
    rain_score = _score(rain, (0.10, 0.25, 0.50, 1.0), strict_top=True)
    snow_score = _score(snow, (0.5, 1.0, 2.0, 3.0), strict_top=True)

    wind_reason = "Wind"
    if wind is not None and 45 <= wind < 55 and load_weight_lb > 30000:
        wind_score = 4
        wind_reason = "Wind and load weight"
    elif wind is not None and 35 <= wind < 45 and load_weight_lb > 40000:
        wind_score = 3
        wind_reason = "Wind and load weight"

    drivers = {
        wind_reason: wind_score,
        "Rain": rain_score,
        "Snow": snow_score,
    }
    # A known dangerous condition should never be hidden as Unknown.
    confirmed_no_travel = [
        name for name, value in drivers.items() if value == 4
    ]
    if confirmed_no_travel:
        return {"level": "No Travel", "score": 4,
                "reason": ", ".join(confirmed_no_travel)}

    if any(value is None for value in drivers.values()):
        return {"level": "Unknown", "score": None,
                "reason": "Incomplete forecast"}

    score = max(drivers.values())
    reasons = [name for name, value in drivers.items() if value == score]
    return {"level": RISK_LEVELS[score], "score": score,
            "reason": ", ".join(reasons)}


def assess_route(route, load_weight_lb):
    """Score each road section using the weather at its start."""

    checkpoints = route.get("checkpoints", [])

    distance_miles = (
        route["distance_meters"] / 1609.344
    )

    miles = {
        level: 0.0
        for level in ALL_LEVELS
    }

    weighted_risk = 0.0
    analyzed_miles = 0.0

    has_no_travel = False
    has_unknown = not checkpoints
    forecasted_checkpoints = 0

    for index, checkpoint in enumerate(checkpoints):
        risk = classify_checkpoint(
            checkpoint.get("weather"),
            load_weight_lb,
        )

        checkpoint["risk"] = risk
        if checkpoint.get("weather") is not None:
            forecasted_checkpoints += 1

        if risk["level"] == "No Travel":
            has_no_travel = True

        if risk["level"] == "Unknown":
            has_unknown = True

        # Destination is the final checkpoint.
        if index + 1 == len(checkpoints):
            continue

        next_checkpoint = checkpoints[index + 1]

        segment_miles = max(
            0.0,
            next_checkpoint["mile"] - checkpoint["mile"],
        )

        miles[risk["level"]] += segment_miles

        if risk["score"] is not None:
            analyzed_miles += segment_miles

            weighted_risk += (
                risk["score"] * segment_miles
            )

    # Determine whether the route can be recommended.
    if has_no_travel:
        route_status = "no_travel"

    elif (
        has_unknown
        or abs(sum(miles.values()) - distance_miles) > max(1e-8, distance_miles * 1e-8)
        or abs(analyzed_miles - distance_miles) > max(1e-8, distance_miles * 1e-8)
    ):
        route_status = "incomplete"

    else:
        route_status = "eligible"

    if route_status == "eligible" and distance_miles > 0:
        average_risk = weighted_risk / distance_miles
    else:
        average_risk = None

    risk_summary = {
        "status": route_status,
        "forecasted_checkpoints": forecasted_checkpoints,
        "checkpoint_count": len(checkpoints),

        "miles_by_level": dict(miles),

        "severe_miles": round(
            miles["Severe"], 2
        ),

        "high_miles": round(
            miles["High"], 2
        ),

        "no_travel_miles": round(
            miles["No Travel"], 2
        ),

        "unknown_miles": round(
            miles["Unknown"], 2
        ),

        "coverage_percent": (
            round(
                min(100, 100 * analyzed_miles / distance_miles),
                1,
            )
            if distance_miles > 0
            else 0
        ),

        "average_risk_score": (
            round(average_risk, 6)
            if average_risk is not None
            else None
        ),
    }

    route["risk_summary"] = risk_summary
    # Keep exact values for ranking; only the public summary is rounded for
    # display. These private values are removed by the API view.
    route["_risk_rank_key"] = (
        miles["Severe"], miles["High"], average_risk
    ) if route_status == "eligible" else None

    return risk_summary


def add_route_recommendation(routes, load_weight_lb):
    """
    Rank eligible routes by:
      1. Fewest Severe miles
      2. Fewest High miles
      3. Lowest average risk
      4. Shortest travel time

    Routes with No Travel conditions or missing forecasts
    cannot receive the recommendation.
    """

    for route in routes:
        assess_route(route, load_weight_lb)
        route["is_recommended"] = False

    eligible_routes = [
        route
        for route in routes
        if route["risk_summary"]["status"] == "eligible"
    ]

    if not eligible_routes:
        return {
            "recommended_route_id": None,
            "recommendation_message": (
                "No route can be recommended. "
                "Every route has a No Travel condition "
                "or incomplete weather information."
            ),
        }

    recommended = min(
        eligible_routes,
        key=lambda route: (
            *route["_risk_rank_key"], route["duration_seconds"], route["id"],
        ),
    )

    recommended["is_recommended"] = True

    return {
        "recommended_route_id": recommended["id"],

        "recommendation_message": (
            f"{recommended.get('name') or 'The selected route'} is recommended "
            "among routes with complete weather data "
            "and no No Travel checkpoints. "
            "Routes are ranked by Severe miles, "
            "High miles, average risk, and travel time."
        ),
    }

def select_display_routes(routes, load_weight_lb, max_display=3):
    """Choose the safest three among the bounded provider candidate pool.

    Eligible candidates follow the four assessment priorities using exact
    unrounded risk measurements. Incomplete forecasts are not treated as
    safe; No Travel candidates always come last. When fewer than three
    eligible routes exist, include other genuine alternatives for comparison.
    Display order remains by travel time and IDs are reassigned 0..N-1.
    """
    for route in routes:
        assess_route(route, load_weight_lb)

    def sort_key(route):
        status = route["risk_summary"]["status"]
        if status == "eligible":
            return (0, *route["_risk_rank_key"], route["duration_seconds"], route["id"])
        # Incomplete routes are unverified; known No Travel routes come last.
        return (1 if status == "incomplete" else 2, route["duration_seconds"], route["id"])

    ranked = sorted(routes, key=sort_key)
    shown = []
    deferred_similar = []
    for route in ranked:
        if len(shown) >= max_display:
            break
        # Assess candidates BEFORE diversity filtering: if two nearly
        # identical corridors have different forecasts, keep the safer one.
        if any(are_near_duplicate_routes(route, chosen) for chosen in shown):
            deferred_similar.append(route)
        else:
            shown.append(route)

    # Prefer three distinct choices, but do not fabricate alternatives.
    # If the provider offers only similar genuine routes, backfill the display
    # from those instead of returning fewer than the assessment asks for.
    if len(shown) < max_display:
        shown.extend(deferred_similar[:max_display - len(shown)])

    shown.sort(key=lambda route: (route["duration_seconds"], route["id"]))
    for index, route in enumerate(shown):
        route["id"] = index
        route["name"] = f"Route {index + 1}"
    return shown
