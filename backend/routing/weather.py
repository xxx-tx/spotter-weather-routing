"""Fetch weather for checkpoints and the map forecast slider."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging

from django.utils import timezone as django_timezone

import requests

from .risk import classify_checkpoint
from .weather_readings import get_forecast_timestamp, weather_at, weather_for_arrival
from .forecast_window import FORECAST_DAYS, HEATMAP_EXTRA_HOURS


logger = logging.getLogger(__name__)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 25
MAX_WORKERS = 1
FORECAST_HOURS = HEATMAP_EXTRA_HOURS + 1


def forecast_days_for_batch(coordinates, coordinate_groups, heatmap_timestamps=None, now=None):
    """Request only the GMT calendar days needed by this batch.

    All 49 slider hours and every checkpoint's ETA must be covered. Open-Meteo
    starts `forecast_days` at 00:00 GMT today, not at the departure hour.
    Forecasts outside the maximum 16 days remain unknown, never fabricated.
    """
    current = now if now is not None else django_timezone.now()
    if current.utcoffset() is None:
        raise ValueError("Current time must include a timezone offset.")
    current_utc = current.astimezone(timezone.utc)

    needed_hours = [get_forecast_timestamp(cp["eta"])
                    for coordinate in coordinates
                    for cp in coordinate_groups[coordinate]]
    if heatmap_timestamps:
        needed_hours.append(max(heatmap_timestamps))
    if not needed_hours:
        return 1

    # Use UTC dates: a request for 00:00 UTC tomorrow needs two GMT days.
    last_day = datetime.fromtimestamp(max(needed_hours), tz=timezone.utc).date()
    requested_days = (last_day - current_utc.date()).days + 1
    return min(FORECAST_DAYS, max(1, requested_days))


def fetch_weather_batch(coordinates, coordinate_groups, heatmap_timestamps=None, load_weight_lb=None,
                        forecast_days=FORECAST_DAYS):
    """Fetch once per coordinate batch; reuse hourly readings for ETA and slider."""
    params = {
        "latitude": ",".join(str(lat) for lat, _ in coordinates),
        "longitude": ",".join(str(lon) for _, lon in coordinates),
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "forecast_days": forecast_days,
    }
    response = requests.get(WEATHER_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) != len(coordinates):
        raise ValueError("Unexpected Open-Meteo locations response.")

    forecast_samples = []
    for coordinate, location_data in zip(coordinates, data):
        # An incomplete result for one location must not discard the valid
        # hourly forecasts for every other location in the same batch.
        hourly = location_data.get("hourly") if isinstance(location_data, dict) else None
        if not isinstance(hourly, dict):
            logger.warning("Open-Meteo returned no hourly data for one location.")
            hourly = {}

        # Preserve the original risk/recommendation model: each checkpoint
        # is scored using the forecast at that checkpoint's own ETA.
        for checkpoint in coordinate_groups[coordinate]:
            checkpoint["weather"] = weather_for_arrival(hourly, checkpoint["eta"])

        if heatmap_timestamps is None:
            continue

        hours = []
        for timestamp in heatmap_timestamps:
            weather = weather_at(hourly, timestamp)
            if weather is None:
                hours.append(None)
                continue
            risk = classify_checkpoint(weather, load_weight_lb)
            hours.append({
                "level": risk["level"],
                "score": risk["score"],
                "wind_mph": weather["wind_mph"],
                "rain_in_hr": weather["rain_in_hr"],
                "snow_in_hr": weather["snow_in_hr"],
            })

        forecast_samples.append({
            "lat": coordinate[0],
            "lon": coordinate[1],
            "hours": hours,
        })
    return forecast_samples


def attach_weather(checkpoints, forecast_start=None, load_weight_lb=None):
    """Enrich checkpoints; optionally attach a 0–48h map-ready forecast.

    An absent Open-Meteo forecast stays unavailable, not a low-risk zero.
    The forecast slider data is independent of ETA-based route ranking.
    """
    coordinate_groups = {}
    for checkpoint in checkpoints:
        coordinate = (round(checkpoint["lat"], 4), round(checkpoint["lon"], 4))
        coordinate_groups.setdefault(coordinate, []).append(checkpoint)
    coordinates = list(coordinate_groups)

    heatmap_timestamps = None
    if forecast_start is not None:
        if load_weight_lb is None:
            raise ValueError("A load weight is needed for the weather heatmap.")
        start = get_forecast_timestamp(forecast_start)
        heatmap_timestamps = [start + 3600 * i for i in range(FORECAST_HOURS)]

    batches = [coordinates[i:i + BATCH_SIZE] for i in range(0, len(coordinates), BATCH_SIZE)]
    # Hold a single UTC reference date for all batches to avoid mixed request
    # horizons if multiple calls happen to cross midnight.
    request_time = django_timezone.now()
    failed_batches = 0
    samples = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                fetch_weather_batch,
                batch,
                coordinate_groups,
                heatmap_timestamps,
                load_weight_lb,
                forecast_days_for_batch(
                    batch, coordinate_groups, heatmap_timestamps, now=request_time
                ),
            )
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                samples.extend(future.result())
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                failed_batches += 1
                logger.warning("Weather batch failed: %s", exc)

    summary = {
        "total": len(checkpoints),
        "available": sum(checkpoint["weather"] is not None for checkpoint in checkpoints),
        "failed_batches": failed_batches,
    }

    if heatmap_timestamps is not None:
        # Deterministic order keeps API responses and UI tests reproducible.
        samples.sort(key=lambda item: (item["lat"], item["lon"]))
        summary["heatmap"] = {
            "start_time": datetime.fromtimestamp(
                heatmap_timestamps[0], tz=timezone.utc
            ).isoformat(),
            "hour_count": FORECAST_HOURS,
            "step_hours": 1,
            "samples": samples,
        }

    return summary
