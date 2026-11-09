"""API tests for POST /api/plan/: validation, error mapping and the JSON contract."""
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

from django.utils import timezone
from rest_framework.test import APISimpleTestCase

from routing.services.errors import GeocodingError, WeatherError

from .fakes import FakeWeather, make_providers

PLAN_URL = "/api/plan/"


@contextmanager
def stub_planner(result=None, error=None):
    """Replaces the planner behind the view; yields the mocked ``plan`` method."""
    with mock.patch("routing.views.build_default_providers"), mock.patch("routing.views.TripPlanner") as planner_class:
        plan_method = planner_class.return_value.plan
        if error is not None:
            plan_method.side_effect = error
        else:
            plan_method.return_value.to_dict.return_value = result or {"routes": []}
        yield plan_method


def request_body(**overrides):
    body = {
        "origin": "Dallas, TX",
        "destination": "Chicago, IL",
        "departure_time": (timezone.now() + timedelta(hours=2)).isoformat(),
        "load_weight_lbs": 42_000,
        "interval_miles": 25,
    }
    body.update(overrides)
    return body


class TripPlanValidationTests(APISimpleTestCase):
    def test_valid_request_reaches_the_planner_as_a_typed_dto(self):
        with stub_planner() as plan_method:
            response = self.client.post(PLAN_URL, request_body(), format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"routes": []})
        trip_request = plan_method.call_args.args[0]
        self.assertEqual(
            (trip_request.origin, trip_request.interval_miles, trip_request.load_weight_lbs),
            ("Dallas, TX", 25, 42_000),
        )
        self.assertIsNotNone(trip_request.departure.tzinfo)

    def test_invalid_inputs_are_rejected_before_any_upstream_call(self):
        cases = {
            "interval_miles": 15,
            "load_weight_lbs": -1,
            "departure_time": "not-a-date",
            "origin": "",
        }
        for field, value in cases.items():
            with self.subTest(field=field), stub_planner() as plan_method:
                response = self.client.post(PLAN_URL, request_body(**{field: value}), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                plan_method.assert_not_called()

    def test_load_weight_limits(self):
        for load, status in ((0, 200), (150_000, 200), (150_001, 400)):
            with self.subTest(load_lbs=load), stub_planner():
                response = self.client.post(PLAN_URL, request_body(load_weight_lbs=load), format="json")
                self.assertEqual(response.status_code, status)

    def test_demo_storm_flag_defaults_to_off_and_is_passed_through_when_on(self):
        cases = [({}, False), ({"demo_storm": True}, True), ({"demo_storm": False}, False)]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides), stub_planner() as plan_method:
                response = self.client.post(PLAN_URL, request_body(**overrides), format="json")
                self.assertEqual(response.status_code, 200)
                self.assertIs(plan_method.call_args.args[0].demo_storm, expected)

    def test_demo_storm_flag_must_be_boolean(self):
        response = self.client.post(PLAN_URL, request_body(demo_storm="maybe"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("demo_storm", response.json())

    def test_same_origin_and_destination_is_rejected(self):
        response = self.client.post(PLAN_URL, request_body(destination="  dallas, tx "), format="json")
        self.assertEqual(response.status_code, 400)

    def test_departure_beyond_forecast_horizon_is_rejected(self):
        far = (timezone.now() + timedelta(days=30)).isoformat()
        response = self.client.post(PLAN_URL, request_body(departure_time=far), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("departure_time", response.json())

    def test_service_errors_map_to_their_status_codes(self):
        cases = [
            (GeocodingError("No location found"), 422, "geocoding_failed"),
            (WeatherError("down"), 502, "weather_failed"),
        ]
        for error, status, code in cases:
            with self.subTest(code=code), stub_planner(error=error):
                response = self.client.post(PLAN_URL, request_body(), format="json")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {"detail": str(error), "code": code})

    def test_health_endpoint(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.json(), {"status": "ok"})


class TripPlanContractTests(APISimpleTestCase):
    """Runs the real planner behind the view with fake providers and checks the JSON keys
    the frontend depends on (frontend/src/types/routing.ts)."""

    def post_with_fakes(self, **overrides):
        providers = make_providers(weather=FakeWeather(wind_at=lambda coord, hour: 47.0))
        body = request_body(origin="origin", destination="destination", **overrides)
        with mock.patch("routing.views.build_default_providers", return_value=providers):
            return self.client.post(PLAN_URL, body, format="json")

    def test_response_contract(self):
        response = self.post_with_fakes()
        self.assertEqual(response.status_code, 200)
        plan = response.json()

        self.assertEqual(
            set(plan),
            {"origin", "destination", "departure_time", "load_weight_lbs", "interval_miles", "routes", "heatmap", "meta"},
        )
        self.assertEqual(len(plan["routes"]), 3)
        route = plan["routes"][0]
        self.assertEqual(
            set(route),
            {
                "id", "name", "source", "rank", "recommended", "distance_miles", "duration_minutes",
                "base_duration_minutes", "summary", "recommendation_reason", "geometry", "checkpoints", "alerts",
            },
        )
        self.assertEqual(
            set(route["checkpoints"][0]),
            {
                "mile", "lat", "lon", "eta", "wind_mph", "rain_in_hr", "snow_in_hr", "temperature_f",
                "risk_level", "risk_score", "load_escalated", "load_rule",
            },
        )
        self.assertEqual(set(route["alerts"][0]), {"mile", "eta", "risk_level", "load_escalated", "message"})
        self.assertEqual(set(plan["heatmap"]), {"start", "max_offset_hours", "radius_miles", "points"})
        self.assertEqual(len(plan["heatmap"]["points"][0]["risk"]), 49)
        self.assertIsNone(plan["meta"]["demo_storm"])

    def test_heavy_load_is_reported_in_the_json(self):
        plan = self.post_with_fakes(load_weight_lbs=42_000).json()
        checkpoint = plan["routes"][0]["checkpoints"][0]
        self.assertEqual(checkpoint["risk_level"], "no_travel")
        self.assertTrue(checkpoint["load_escalated"])

        lighter = self.post_with_fakes(load_weight_lbs=30_000).json()
        self.assertEqual(lighter["routes"][0]["checkpoints"][0]["risk_level"], "severe")
