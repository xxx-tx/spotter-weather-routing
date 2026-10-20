"""Small tests for the rules used to choose truck routes."""

from datetime import datetime, timezone
from math import inf

import pytest

from routing.checkpoints import create_checkpoints
from routing.risk import assess_route, classify_checkpoint
from routing.services import _process_route
from routing.weather_readings import weather_at, weather_for_arrival


def risk(wind=0, rain=0, snow=0, weight=20000):
    return classify_checkpoint({
        "wind_mph": wind, "rain_in_hr": rain, "snow_in_hr": snow,
    }, weight)["level"]


@pytest.mark.parametrize("wind,weight,expected", [
    (24.999, 20000, "Low"), (25, 20000, "Moderate"),
    (35, 40000, "High"), (35, 40001, "Severe"),
    (45, 30000, "Severe"), (45, 30001, "No Travel"),
    (54.999, 20000, "Severe"), (55, 20000, "No Travel"),
])
def test_wind_rules(wind, weight, expected):
    assert risk(wind=wind, weight=weight) == expected


@pytest.mark.parametrize("rain,snow,expected", [
    (0.10, 0, "Moderate"), (0.25, 0, "High"),
    (0.50, 0, "Severe"), (1.0, 0, "Severe"),
    (1.0000001, 0, "No Travel"), (0, 3.0, "Severe"),
    (0, 3.0000001, "No Travel"),
])
def test_precipitation_rules(rain, snow, expected):
    assert risk(rain=rain, snow=snow) == expected


def test_missing_weather_is_not_safe():
    assert classify_checkpoint({"wind_mph": 20}, 20000)["level"] == "Unknown"
    assert classify_checkpoint({"wind_mph": 55}, 20000)["level"] == "No Travel"


def readings(first_wind=5, second_wind=5, rain_mm=0, snow_cm=0):
    first = int(datetime(2026, 10, 21, 9, tzinfo=timezone.utc).timestamp())
    return {
        "time": [first, first + 3600],
        "wind_speed_10m": [first_wind, second_wind],
        "rain": [0, rain_mm],
        "showers": [0, 0],
        "snowfall": [0, snow_cm],
    }


def test_converted_weather_keeps_threshold_precision():
    hourly = readings(second_wind=54.999, rain_mm=25.40001, snow_cm=7.62001)
    timestamp = hourly["time"][1]
    weather = weather_at(hourly, timestamp)
    assert weather["wind_mph"] == 54.999
    assert weather["rain_in_hr"] > 1.0
    assert weather["snow_in_hr"] > 3.0
    assert classify_checkpoint(weather, 20000)["level"] == "No Travel"


def test_arrival_weather_uses_both_wind_hours_and_end_of_hour_rain():
    weather = weather_for_arrival(
        readings(first_wind=56, second_wind=20, rain_mm=2.54),
        "2026-10-21T09:01:00Z",
    )
    assert weather["wind_mph"] == 56
    assert weather["rain_in_hr"] == pytest.approx(0.1)
    assert risk(wind=weather["wind_mph"]) == "No Travel"


def test_missing_earlier_hour_does_not_become_clear_skies():
    hourly = readings()
    for name, values in hourly.items():
        hourly[name] = values[1:]
    assert weather_for_arrival(hourly, "2026-10-21T09:15:00Z") is None


def sample_route(miles):
    return {
        "distance_meters": miles * 1609.344,
        "duration_seconds": 60,
        "departure_time": "2026-10-21T09:00:00+00:00",
        "geometry": [[-112, 34], [-111.9999, 34]],
    }


@pytest.mark.parametrize("miles", [0.004, 0.008, 100.0])
def test_checkpoint_distance_keeps_precision(miles):
    route = sample_route(miles)
    route["checkpoints"] = create_checkpoints(route, 10)
    for checkpoint in route["checkpoints"]:
        checkpoint["weather"] = {
            "wind_mph": 35, "rain_in_hr": 0, "snow_in_hr": 0,
        }
    result = assess_route(route, 20000)
    assert result["status"] == "eligible"
    assert result["coverage_percent"] == 100
    assert result["average_risk_score"] == 2
    assert result["miles_by_level"]["High"] == pytest.approx(miles)
    assert route["checkpoints"][-1]["mile"] == pytest.approx(miles)


def raw_provider_route(distance=5000, latitude=34, duration=500):
    return {
        "summary": {
            "lengthInMeters": distance,
            "travelTimeInSeconds": duration,
            "departureTime": "2026-10-21T09:00:00Z",
            "arrivalTime": "2026-10-21T09:10:00Z",
        },
        "legs": [{"points": [
            {"longitude": -112, "latitude": latitude},
            {"longitude": -111, "latitude": latitude},
        ]}],
    }


@pytest.mark.parametrize("distance,latitude,duration", [
    (inf, 34, 500), (float("nan"), 34, 500),
    (5000, 97, 500), (5000, 34, inf), (True, 34, 500),
])
def test_reject_bad_provider_data(distance, latitude, duration):
    assert _process_route(raw_provider_route(distance, latitude, duration)) is None


def test_good_provider_data_is_accepted():
    assert _process_route(raw_provider_route()) is not None
