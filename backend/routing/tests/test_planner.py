"""The planner end to end with fake providers: route discovery, ETA sampling, risk and ranking."""
from datetime import datetime, timezone

from django.test import SimpleTestCase

from routing.services.errors import PlanningError

from .fakes import (
    SAME_AS_ORIGIN,
    DirectOnlyRouter,
    DuplicateOnlyRouter,
    FakeGeocoder,
    FakeWeather,
    ShortForecastWeather,
    ThreeAlternativesRouter,
    ViaFailingRouter,
    make_providers,
    run_plan,
    trip,
)

UTC = timezone.utc


def osrm_route(plan):
    for route in plan["routes"]:
        if route["source"] == "osrm":
            return route
    raise AssertionError("plan has no OSRM route")


class RouteDiscoveryTests(SimpleTestCase):
    def test_lateral_routes_fill_the_gap_when_osrm_returns_one_route(self):
        router = DirectOnlyRouter()
        plan = run_plan(trip(), make_providers(router=router))

        self.assertEqual(len(plan["routes"]), 3)
        self.assertEqual({r["source"] for r in plan["routes"]}, {"osrm", "lateral-north", "lateral-south"})
        via_calls = [waypoints for waypoints, _ in router.calls if len(waypoints) == 3]
        self.assertEqual(len(via_calls), 2)
        latitudes = sorted(waypoints[1][0] for waypoints in via_calls)
        self.assertLess(latitudes[0], 35.0)
        self.assertGreater(latitudes[1], 35.0)
        self.assertAlmostEqual(via_calls[0][1][1], -97.0, places=3)

    def test_routes_are_geometrically_distinct(self):
        plan = run_plan(trip(), make_providers())
        peak_latitudes = sorted(max(lat for lat, _ in r["geometry"]) for r in plan["routes"])
        self.assertEqual(peak_latitudes[0], peak_latitudes[1])
        self.assertGreater(peak_latitudes[2] - peak_latitudes[1], 0.3)
        self.assertEqual(plan["meta"]["warnings"], [])

    def test_three_osrm_alternatives_need_no_lateral_queries(self):
        router = ThreeAlternativesRouter()
        plan = run_plan(trip(), make_providers(router=router))
        self.assertEqual(len(plan["routes"]), 3)
        self.assertEqual(len(router.calls), 1)
        self.assertEqual(router.calls[0][1], 3)
        self.assertEqual({r["source"] for r in plan["routes"]}, {"osrm"})

    def test_duplicate_geometries_are_reported_not_hidden(self):
        plan = run_plan(trip(), make_providers(router=DuplicateOnlyRouter()))
        self.assertEqual(len(plan["routes"]), 1)
        self.assertEqual(plan["meta"]["warnings"][0], "Only 1 of 3 distinct drivable routes were found for this corridor")

    def test_lateral_routing_failures_degrade_to_a_warning(self):
        plan = run_plan(trip(), make_providers(router=ViaFailingRouter()))
        self.assertEqual(len(plan["routes"]), 1)
        self.assertTrue(plan["meta"]["warnings"])

    def test_heavy_truck_factor_scales_duration(self):
        plan = run_plan(trip(), make_providers())
        for route in plan["routes"]:
            self.assertAlmostEqual(route["duration_minutes"], route["base_duration_minutes"] * 1.12, delta=0.2)

    def test_identical_endpoints_are_rejected(self):
        with self.assertRaises(PlanningError):
            run_plan(trip(), make_providers(geocoder=FakeGeocoder(SAME_AS_ORIGIN)))


class WeatherSamplingTests(SimpleTestCase):
    def test_checkpoint_weather_comes_from_the_hour_of_arrival_not_departure(self):
        weather = FakeWeather(wind_at=lambda coord, hour: float(hour))
        plan = run_plan(trip(interval=50), make_providers(weather=weather))
        route = osrm_route(plan)
        day_start = datetime(2026, 3, 10, tzinfo=UTC)
        for checkpoint in route["checkpoints"]:
            self.assertNotIn(".", checkpoint["eta"])
            eta = datetime.fromisoformat(checkpoint["eta"])
            expected_hour = int((eta - day_start).total_seconds() // 3600)
            self.assertEqual(checkpoint["wind_mph"], float(expected_hour))
        self.assertEqual(route["checkpoints"][0]["wind_mph"], 6.0)
        self.assertGreater(route["checkpoints"][-1]["wind_mph"], 6.0)

    def test_checkpoints_follow_the_selected_interval(self):
        for interval in (10, 25, 50):
            with self.subTest(interval=interval):
                plan = run_plan(trip(interval=interval), make_providers())
                route = osrm_route(plan)
                miles = [c["mile"] for c in route["checkpoints"]]
                self.assertEqual(miles[0], 0.0)
                self.assertEqual(miles[1], float(interval))
                self.assertAlmostEqual(miles[-1], route["distance_miles"], delta=0.1)

    def test_weather_points_are_deduplicated_and_fetched_in_one_call(self):
        weather = FakeWeather()
        plan = run_plan(trip(interval=10), make_providers(weather=weather))
        self.assertEqual(len(weather.calls), 1)
        keys = weather.calls[0]
        self.assertEqual(len(keys), len(set(keys)))
        raw_samples = sum(len(r["checkpoints"]) for r in plan["routes"]) + len(plan["heatmap"]["points"])
        self.assertLess(len(keys), raw_samples)
        self.assertEqual(plan["meta"]["weather_points"], len(keys))

    def test_heatmap_payload_is_a_48_hour_series_anchored_at_departure(self):
        weather = FakeWeather(wind_at=lambda coord, hour: float(hour))
        plan = run_plan(trip(), make_providers(weather=weather))
        heatmap = plan["heatmap"]
        self.assertEqual(heatmap["start"], "2026-03-10T06:00:00+00:00")
        self.assertEqual(heatmap["max_offset_hours"], 48)
        point = heatmap["points"][0]
        for series in (point["risk"], point["wind"], point["rain"], point["snow"]):
            self.assertEqual(len(series), 49)
        self.assertEqual(point["wind"][0], 6.0)
        self.assertEqual(point["wind"][10], 16.0)

    def test_heatmap_risk_includes_the_load_rules(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 40.0)
        heavy = run_plan(trip(load=45_000), make_providers(weather=weather))
        light = run_plan(trip(load=40_000), make_providers(weather=weather))
        self.assertEqual(set(heavy["heatmap"]["points"][0]["risk"]), {4})
        self.assertEqual(set(light["heatmap"]["points"][0]["risk"]), {3})

    def test_checkpoints_outside_the_forecast_window_are_flagged(self):
        plan = run_plan(trip(), make_providers(weather=ShortForecastWeather()))
        self.assertTrue(any("outside the forecast window" in w for w in plan["meta"]["warnings"]))


class RiskIntegrationTests(SimpleTestCase):
    def test_load_weight_escalates_checkpoints_through_the_whole_pipeline(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 40.0)
        heavy = run_plan(trip(load=45_000), make_providers(weather=weather))
        light = run_plan(trip(load=40_000), make_providers(weather=weather))
        for checkpoint in heavy["routes"][0]["checkpoints"]:
            self.assertEqual(checkpoint["risk_level"], "severe")
            self.assertTrue(checkpoint["load_escalated"])
            self.assertEqual(checkpoint["load_rule"], "35-44 mph wind with a load over 40,000 lb is Severe")
        for checkpoint in light["routes"][0]["checkpoints"]:
            self.assertEqual(checkpoint["risk_level"], "high")
            self.assertFalse(checkpoint["load_escalated"])
            self.assertIsNone(checkpoint["load_rule"])

    def test_30000_lb_is_not_over_the_30000_lb_limit(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 47.0)
        at_limit = run_plan(trip(load=30_000), make_providers(weather=weather))
        over_limit = run_plan(trip(load=30_001), make_providers(weather=weather))
        self.assertEqual({c["risk_level"] for c in at_limit["routes"][0]["checkpoints"]}, {"severe"})
        self.assertEqual({c["risk_level"] for c in over_limit["routes"][0]["checkpoints"]}, {"no_travel"})

    def test_stormy_corridor_is_ranked_last_with_an_explanation(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 60.0 if coord[0] > 35.4 else 5.0)
        plan = run_plan(trip(interval=10), make_providers(weather=weather))
        routes = plan["routes"]

        self.assertEqual([r["rank"] for r in routes], [1, 2, 3])
        self.assertTrue(routes[0]["recommended"])
        self.assertEqual(routes[0]["source"], "osrm")
        self.assertEqual(routes[0]["summary"]["no_travel_miles"], 0.0)
        self.assertTrue(routes[0]["recommendation_reason"].startswith("Recommended: Zero Severe or No-Travel miles"))
        stormy = routes[-1]
        self.assertEqual(stormy["source"], "lateral-north")
        self.assertGreater(stormy["summary"]["no_travel_miles"], 0.0)
        self.assertTrue(stormy["recommendation_reason"].startswith("Avoided:"))
        self.assertIn("No-Travel miles", stormy["recommendation_reason"])

    def test_category_miles_cover_the_route_length(self):
        plan = run_plan(trip(interval=10), make_providers())
        for route in plan["routes"]:
            summary = route["summary"]
            covered = 0.0
            for name in ("no_travel", "severe", "high", "moderate", "low"):
                covered += summary[f"{name}_miles"]
            self.assertAlmostEqual(covered, route["distance_miles"], delta=0.6)
            self.assertEqual(summary["average_risk_score"], 1.0)


class DispatcherAlertTests(SimpleTestCase):
    """Every Severe or No Travel checkpoint is listed with its cause, none are left out."""

    def test_every_severe_or_no_travel_checkpoint_has_an_alert(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 60.0 if coord[0] > 35.4 else 47.0)
        plan = run_plan(trip(load=42_000, interval=25), make_providers(weather=weather))
        for route in plan["routes"]:
            flagged = [c["mile"] for c in route["checkpoints"] if c["risk_level"] in ("severe", "no_travel")]
            alerted = [alert["mile"] for alert in route["alerts"]]
            self.assertEqual(alerted, flagged)

    def test_load_escalated_alert_explains_the_rule(self):
        weather = FakeWeather(wind_at=lambda coord, hour: 47.0)
        plan = run_plan(trip(load=42_000), make_providers(weather=weather))
        alert = plan["routes"][0]["alerts"][0]
        self.assertEqual(alert["risk_level"], "no_travel")
        self.assertTrue(alert["load_escalated"])
        self.assertIn("with a 42,000 lb load", alert["message"])
        self.assertIn("At or under 30,000 lb this wind is Severe", alert["message"])

    def test_calm_routes_have_no_alerts(self):
        plan = run_plan(trip(), make_providers())
        for route in plan["routes"]:
            self.assertEqual(route["alerts"], [])
