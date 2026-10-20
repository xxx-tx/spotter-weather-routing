"""Validate departures against the hourly forecast window used by Open-Meteo.

The form intentionally sends *origin-local* wall-clock time without an offset.
TomTom resolves that timezone and returns offset-aware route timestamps.
Only reject clearly impossible dates before routing; do exact checks afterward.
"""

from datetime import datetime, timedelta, timezone
from math import isfinite

from django.utils import timezone as django_timezone
from .weather_readings import next_forecast_hour


FORECAST_DAYS = 16  # Open-Meteo /v1/forecast with timezone=GMT, forecast_days=16.
HEATMAP_EXTRA_HOURS = 48  # Slider shows hour 0 to hour 48 inclusive.


class ForecastWindowError(ValueError):
    """An input departure cannot be covered by the required forecasts."""


def _now_utc(now=None):
    value = now if now is not None else django_timezone.now()
    if value.utcoffset() is None:
        raise ValueError("Current time must include a timezone offset.")
    return value.astimezone(timezone.utc)


def forecast_last_hour(now=None):
    """Last UTC hourly sample available under the 16-day GMT request."""
    today = _now_utc(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=FORECAST_DAYS) - timedelta(hours=1)


def check_local_departure(value):
    """Reject *certainly* past/out-of-range origin-local times pre-routing.

    Global civil offsets range from UTC-12 to UTC+14. Before geocoding we
    cannot know the origin's offset, so this check deliberately errs on the
    side of allowing an ambiguous time; TomTom resolves it after routing.
    """
    local = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    now = _now_utc()
    earliest_utc = local - timedelta(hours=14)  # Origin at UTC+14.
    latest_utc = local + timedelta(hours=12)  # Origin at UTC-12.

    if latest_utc < now:
        raise ForecastWindowError(
            "Departure time is in the past. Enter a future time at the origin."
        )
    if next_forecast_hour(earliest_utc) + timedelta(hours=HEATMAP_EXTRA_HOURS) > forecast_last_hour(now):
        raise ForecastWindowError(
            "Departure is too far ahead for the full 0–48 hour weather slider "
            "within the 16-day forecast. Choose an earlier departure."
        )


def check_route_forecast_window(routes):
    """Validate provider-resolved time before spending money on weather.

    Returns routes whose checkpoint ETAs extend past the available window.
    They may still be displayed, but must be marked forecast-incomplete by
    the weather/risk pipeline; reject a trip only if *every* route overruns.
    """
    now = _now_utc()
    last_hour = forecast_last_hour(now)
    overrun_ids = []

    for route in routes:
        try:
            departure = datetime.fromisoformat(
                route["departure_time"].replace("Z", "+00:00")
            )
            if departure.utcoffset() is None:
                raise ValueError("Missing timezone offset")
            duration = route["duration_seconds"]
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not isfinite(duration) or duration < 0):
                raise ValueError("Invalid route duration")
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError("Routing provider returned an invalid departure or duration.") from exc

        departure_utc = departure.astimezone(timezone.utc)
        if departure_utc < now:
            raise ForecastWindowError(
                "Departure time has already passed at the origin. "
                "Choose a future departure in the origin's local timezone."
            )
        if next_forecast_hour(departure_utc) + timedelta(hours=HEATMAP_EXTRA_HOURS) > last_hour:
            raise ForecastWindowError(
                "The selected departure cannot show all 0–48 forecast hours. "
                "Choose an earlier departure within the 16-day forecast."
            )

        final_eta = departure_utc + timedelta(seconds=duration)
        if next_forecast_hour(final_eta) > last_hour:
            overrun_ids.append(route["id"])

    if routes and len(overrun_ids) == len(routes):
        raise ForecastWindowError(
            "Every route reaches its destination beyond the available "
            "16-day weather forecast. Choose an earlier departure "
            "or a shorter trip."
        )

    return overrun_ids
