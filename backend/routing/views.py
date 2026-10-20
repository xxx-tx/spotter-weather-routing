"""Validate trips and return routes with weather risks."""

import logging

import requests
from rest_framework.decorators import api_view, throttle_classes
from .throttles import RouteMinuteThrottle, RouteDailyThrottle
from rest_framework.response import Response
from rest_framework import status

from django.conf import settings
from .serializers import TripInputSerializer
from .services import get_trip_routes, TomTomError

from .checkpoints import create_checkpoints
from .weather import attach_weather

from .risk import add_route_recommendation, select_display_routes
from .route_diversity import are_near_duplicate_routes
from .forecast_window import (
    ForecastWindowError,
    check_route_forecast_window,
)


logger = logging.getLogger(__name__)
MAX_CHECKPOINTS_PER_REQUEST = 400


def _route_warning(routes):
    """Tell the UI when three genuinely different options weren't available."""
    count = len(routes)
    if count < 3:
        return (f"TomTom returned only {count} usable route "
                f"{'option' if count == 1 else 'options'} for this trip. "
                "Other routes cannot be generated reliably.")
    if any(are_near_duplicate_routes(first, second)
           for index, first in enumerate(routes)
           for second in routes[index + 1:]):
        return ("Some route options use very similar road corridors. "
                "The safest available alternatives are shown.")
    return None


@api_view(['GET'])
def health_check(request):
    return Response({
        'status': 'ok',
        'message': 'Routing BE is running'
    })


@api_view(['POST'])
def validate_trip(request):
    # Use the exact same rules as /api/routes/, including departure-window
    # checks and allowed checkpoint spacing. Keep `error` for older callers.
    serializer = TripInputSerializer(data=request.data)
    if not serializer.is_valid():
        errors = serializer.errors
        first_error = next(iter(errors.values()), ["Invalid trip input."])
        if isinstance(first_error, (list, tuple)) and first_error:
            message = str(first_error[0])
        else:
            message = str(first_error)
        return Response(
            {"error": message, "errors": errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    trip = serializer.validated_data
    return Response({
        'message': 'Trip validated successfully',
        'trip': dict(trip),
    })


@api_view(["POST"])
@throttle_classes([RouteMinuteThrottle, RouteDailyThrottle])
def plan_routes(request):
    serializer = TripInputSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {"errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    api_key = settings.TOMTOM_API_KEY

    if not api_key:
        return Response(
            {"error": "TOMTOM_API_KEY is not configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    trip = serializer.validated_data
    spacing = trip["checkpoint_miles"]

    try:
        # 1. Get available truck routes.
        result = get_trip_routes(trip, api_key)
        if (not isinstance(result, dict)
                or not isinstance(result.get("routes"), list)
                or not result["routes"]):
            raise TomTomError("No usable truck routes were returned by TomTom.")

        # Validate TomTom's origin-local departure after it is converted
        # into a timezone-aware timestamp; do this before weather requests.
        overrun_route_ids = set(check_route_forecast_window(result["routes"]))
        for route in result["routes"]:
            route["_forecast_overrun"] = route["id"] in overrun_route_ids

        # 2. Generate distance-based checkpoints.
        all_checkpoints = []

        for route in result["routes"]:
            if len(all_checkpoints) + 2 + int(
                (route["distance_meters"] / 1609.344) / spacing
            ) > MAX_CHECKPOINTS_PER_REQUEST:
                return Response(
                    {"error": "Trip has too many weather checkpoints. Try 25 or 50 mile spacing, or a shorter trip."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            checkpoints = create_checkpoints(
                route,
                spacing_miles=spacing,
            )

            route["checkpoints"] = checkpoints
            route.pop("_timing_progress", None)
            anchors = route.pop("_geometry_progress", None)
            if anchors:
                route["geometry_road_progress"] = anchors
            all_checkpoints.extend(checkpoints)

    except ForecastWindowError as exc:
        return Response(
            {"errors": {"departure_time": [str(exc)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except TomTomError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
        logger.warning("Malformed route data: %s", type(exc).__name__)
        return Response(
            {"error": "The routing provider returned unusable route data. Please try again."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # 3. Attach weather forecasts. Individual missing locations/batches are
    # handled by attach_weather as Unknown risk. A malformed service response
    # is a 502 rather than an unhandled server error.
    try:
        weather_summary = attach_weather(
            all_checkpoints,
            forecast_start=result["routes"][0]["departure_time"],
            load_weight_lb=trip["load_weight_lb"],
        )
        if (not isinstance(weather_summary, dict)
                or isinstance(weather_summary.get("failed_batches"), bool)
                or not isinstance(weather_summary.get("failed_batches"), int)
                or weather_summary["failed_batches"] < 0):
            raise ValueError("Invalid weather summary")
        heatmap = weather_summary.pop("heatmap", None)
        if (heatmap is not None and
                (not isinstance(heatmap, dict)
                 or not isinstance(heatmap.get("samples"), list))):
            raise ValueError("Invalid weather heatmap")
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        logger.warning("Weather response could not be processed: %s", type(exc).__name__)
        return Response(
            {"error": "Weather data could not be processed. Please try again."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # 4. Rank all forecasted candidates, then return only the best three.
    # This prevents a safe TomTom alternative from being discarded before
    # the weather assessment. Do not send the other candidates' heatmap data.
    result["routes"] = select_display_routes(
        result["routes"], trip["load_weight_lb"], max_display=3,
    )
    selected_checkpoints = [
        checkpoint for route in result["routes"]
        for checkpoint in route["checkpoints"]
    ]
    weather_summary["total"] = len(selected_checkpoints)
    weather_summary["available"] = sum(
        checkpoint["weather"] is not None for checkpoint in selected_checkpoints
    )
    if heatmap is not None:
        selected_coordinates = {
            (round(checkpoint["lat"], 4), round(checkpoint["lon"], 4))
            for checkpoint in selected_checkpoints
        }
        heatmap["samples"] = [
            sample for sample in heatmap["samples"]
            if (round(sample["lat"], 4), round(sample["lon"], 4))
            in selected_coordinates
        ]

    has_selected_overrun = any(
        route.pop("_forecast_overrun", False) for route in result["routes"]
    )
    recommendation = add_route_recommendation(
        result["routes"], trip["load_weight_lb"],
    )
    for route in result["routes"]:
        route.pop("_risk_rank_key", None)

    # 5. Return everything to React.
    result["checkpoint_spacing_miles"] = spacing
    result["route_warning"] = _route_warning(result["routes"])
    result["weather_summary"] = weather_summary
    result["heatmap"] = heatmap

    result.update(recommendation)

    if weather_summary["available"] < weather_summary["total"]:
        result["weather_warning"] = (
            "Some checkpoint forecasts are unavailable. "
            "Routes with incomplete weather information "
            "cannot receive a recommendation."
        )
    else:
        result["weather_warning"] = None

    if has_selected_overrun:
        coverage_note = (
            "Some routes extend beyond the 16-day weather forecast. "
            "Their later checkpoints cannot be evaluated or recommended "
            "until forecasts become available."
        )
        result["weather_warning"] = " ".join(filter(None, (
            result["weather_warning"], coverage_note,
        )))

    return Response(result)