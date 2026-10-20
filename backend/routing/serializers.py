
from datetime import datetime
from rest_framework import serializers

from .forecast_window import check_local_departure, ForecastWindowError


class TripInputSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure_time = serializers.CharField()
    load_weight_lb = serializers.IntegerField(min_value=1)
    checkpoint_miles = serializers.ChoiceField(
        choices=[10, 25, 50],
        default=50,
    )

    def validate_departure_time(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError:
            raise serializers.ValidationError(
                "Use YYYY-MM-DDTHH:MM format."
            )
        try:
            check_local_departure(value)
        except ForecastWindowError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate(self, attrs):
        if (
            attrs["origin"].strip().lower()
            == attrs["destination"].strip().lower()
        ):
            raise serializers.ValidationError(
                "Origin and destination must be different."
            )
        return attrs
