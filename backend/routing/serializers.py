from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from .services.dtos import TripRequest

ALLOWED_INTERVALS = (10, 25, 50)
MAX_LOAD_LBS = 150_000
FORECAST_HORIZON_DAYS = 14
PAST_DEPARTURE_DAYS = 7


class TripPlanRequestSerializer(serializers.Serializer):
    """Validates the request body before any upstream call is made."""

    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure_time = serializers.DateTimeField()
    load_weight_lbs = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LBS)
    interval_miles = serializers.IntegerField()
    demo_storm = serializers.BooleanField(required=False, default=False)

    def validate_interval_miles(self, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise serializers.ValidationError("Must be one of 10, 25 or 50.")
        return value

    def validate_departure_time(self, value: datetime) -> datetime:
        now = timezone.now()
        if value > now + timedelta(days=FORECAST_HORIZON_DAYS):
            raise serializers.ValidationError(
                f"Forecasts are only available up to {FORECAST_HORIZON_DAYS} days ahead."
            )
        if value < now - timedelta(days=PAST_DEPARTURE_DAYS):
            raise serializers.ValidationError(
                f"Departure may be at most {PAST_DEPARTURE_DAYS} days in the past."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["origin"].strip().lower() == attrs["destination"].strip().lower():
            raise serializers.ValidationError("Origin and destination must differ.")
        return attrs

    def to_trip_request(self) -> TripRequest:
        data = self.validated_data
        return TripRequest(
            origin=data["origin"],
            destination=data["destination"],
            departure=data["departure_time"],
            load_weight_lbs=data["load_weight_lbs"],
            interval_miles=data["interval_miles"],
            demo_storm=data["demo_storm"],
        )
