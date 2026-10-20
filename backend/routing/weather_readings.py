"""Read hourly forecasts without losing risk-relevant precision."""

from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from math import isfinite


def next_forecast_hour(moment):
    """Round an aware time up to the next UTC hour."""
    if moment.utcoffset() is None:
        raise ValueError("Forecast timestamp needs a UTC offset.")
    utc = moment.astimezone(timezone.utc)
    hour = utc.replace(minute=0, second=0, microsecond=0)
    return hour if utc == hour else hour + timedelta(hours=1)


def get_forecast_timestamp(eta_string):
    """Return the next UTC whole-hour UNIX timestamp."""
    eta = datetime.fromisoformat(eta_string.replace("Z", "+00:00"))
    if eta.utcoffset() is None:
        raise ValueError("Forecast timestamp needs a UTC offset.")
    return int(next_forecast_hour(eta).timestamp())


def weather_at(hourly, timestamp):
    """Read exact-hour weather; never replace missing readings with zero."""
    timestamps = hourly.get("time", [])
    if not isinstance(timestamps, list):
        return None
    try:
        position = bisect_left(timestamps, timestamp)
    except TypeError:
        return None
    if position >= len(timestamps) or timestamps[position] != timestamp:
        return None
    try:
        wind = float(hourly["wind_speed_10m"][position])
        rain = float(hourly["rain"][position])
        showers = float(hourly["showers"][position])
        snow = float(hourly["snowfall"][position])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if not all(isfinite(value) and value >= 0 for value in (wind, rain, showers, snow)):
        return None
    return {
        "wind_mph": wind,
        "rain_in_hr": (rain + showers) / 25.4,
        "snow_in_hr": snow / 2.54,
        "forecast_time": datetime.fromtimestamp(
            timestamp, tz=timezone.utc
        ).isoformat(),
    }


def weather_for_arrival(hourly, eta_string):
    """Use the arrival hour's rain and the higher adjacent wind reading.

    Rain and snow are hourly totals ending at the next whole hour.
    Wind is a point forecast, so check both hours around the ETA.
    If the needed hour is missing, leave the forecast unknown.
    """
    timestamp = get_forecast_timestamp(eta_string)
    current = weather_at(hourly, timestamp)
    if current is None:
        return None
    eta = datetime.fromisoformat(eta_string.replace("Z", "+00:00"))
    if int(eta.timestamp()) == timestamp:
        return current
    previous = weather_at(hourly, timestamp - 3600)
    if previous is None:
        return None
    current["wind_mph"] = max(current["wind_mph"], previous["wind_mph"])
    return current


