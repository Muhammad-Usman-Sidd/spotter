"""The synthetic storm used to demonstrate the load rules on a calm forecast day."""
import math
from datetime import datetime, timezone

from django.test import SimpleTestCase

from routing.services.demo_storm import DemoStorm, apply_storm, plan_storm, sigma_for_interval, storm_intensity
from routing.services.geometry import MILES_PER_DEGREE_LAT, Polyline, snap_to_grid
from routing.services.risk_engine import RiskLevel, assess_conditions

from .fakes import CachingFakeWeather, calm_series, east_west, make_providers, run_plan, trip

UTC = timezone.utc
STORM = DemoStorm(
    center=(35.0, -97.0),
    center_mile=175.0,
    sigma_miles=70.0,
    peak_time=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
)
PEAK_INDEX = 12


def cell_north_of_center(miles):
    return snap_to_grid(STORM.center[0] + miles / MILES_PER_DEGREE_LAT, STORM.center[1])


def stormed_conditions(key, series=None):
    stormed = apply_storm({key: series or calm_series()}, STORM)[key]
    return stormed.at(STORM.peak_time)


class DemoStormModelTests(SimpleTestCase):
    def test_core_is_no_travel_for_every_load(self):
        conditions = stormed_conditions(snap_to_grid(*STORM.center))
        self.assertEqual(conditions.wind_mph, 57.0)
        self.assertEqual(conditions.snow_in_hr, 2.6)
        for load in (0, 28_000, 45_000):
            with self.subTest(load_lbs=load):
                result = assess_conditions(conditions, load)
                self.assertEqual(result.level, RiskLevel.NO_TRAVEL)
                self.assertFalse(result.load_escalated)

    def test_shoulder_in_the_45_to_54_band_depends_on_load(self):
        conditions = stormed_conditions(cell_north_of_center(25))
        self.assertGreaterEqual(conditions.wind_mph, 45.0)
        self.assertLess(conditions.wind_mph, 55.0)
        at_limit = assess_conditions(conditions, 30_000)
        over_limit = assess_conditions(conditions, 30_001)
        self.assertEqual((at_limit.level, at_limit.load_escalated), (RiskLevel.SEVERE, False))
        self.assertEqual((over_limit.level, over_limit.load_escalated), (RiskLevel.NO_TRAVEL, True))

    def test_outer_shoulder_in_the_35_to_44_band_escalates_only_above_40000_lb(self):
        conditions = stormed_conditions(cell_north_of_center(50))
        self.assertGreaterEqual(conditions.wind_mph, 35.0)
        self.assertLess(conditions.wind_mph, 45.0)
        at_limit = assess_conditions(conditions, 40_000)
        over_limit = assess_conditions(conditions, 40_001)
        self.assertEqual((at_limit.level, at_limit.load_escalated), (RiskLevel.HIGH, False))
        self.assertEqual((over_limit.level, over_limit.load_escalated), (RiskLevel.SEVERE, True))

    def test_cells_far_from_the_front_are_returned_untouched(self):
        far = snap_to_grid(STORM.center[0] + 500 / MILES_PER_DEGREE_LAT, STORM.center[1])
        series = calm_series()
        self.assertIs(apply_storm({far: series}, STORM)[far], series)

    def test_front_never_weakens_existing_weather(self):
        conditions = stormed_conditions(snap_to_grid(*STORM.center), calm_series(wind=70.0, snow=4.0))
        self.assertEqual(conditions.wind_mph, 70.0)
        self.assertEqual(conditions.snow_in_hr, 4.0)

    def test_intensity_fades_away_from_the_peak_hour(self):
        self.assertEqual(storm_intensity(0.0, 0.0, 70.0), 1.0)
        self.assertAlmostEqual(storm_intensity(0.0, 12.0, 70.0), math.exp(-1))
        self.assertAlmostEqual(storm_intensity(70.0, 0.0, 70.0), math.exp(-1))
        key = snap_to_grid(*STORM.center)
        stormed = apply_storm({key: calm_series()}, STORM)[key]
        self.assertAlmostEqual(stormed.wind_mph[PEAK_INDEX - 12], 6.0 + 51.0 * math.exp(-1), places=6)
        self.assertGreater(stormed.wind_mph[PEAK_INDEX], stormed.wind_mph[PEAK_INDEX + 6])

    def test_temperature_drops_to_freezing_range_but_never_warms(self):
        key = snap_to_grid(*STORM.center)
        self.assertEqual(stormed_conditions(key).temperature_f, 22.0)
        self.assertEqual(stormed_conditions(key, calm_series(temperature=10.0)).temperature_f, 10.0)

    def test_input_series_are_not_mutated(self):
        key = snap_to_grid(*STORM.center)
        original = calm_series()
        source = {key: original}
        apply_storm(source, STORM)
        self.assertIs(source[key], original)
        self.assertEqual(max(original.wind_mph), 5.0)
        self.assertEqual(max(original.snow_in_hr), 0.0)

    def test_scale_widens_with_checkpoint_spacing(self):
        self.assertEqual(sigma_for_interval(10), 70.0)
        self.assertEqual(sigma_for_interval(25), 70.0)
        self.assertAlmostEqual(sigma_for_interval(50), 110.0)

    def test_centre_snaps_to_a_checkpoint_and_peaks_at_the_hour_of_arrival(self):
        route = Polyline(east_west(35.0, -100.0, -94.0))
        departure = datetime(2026, 3, 10, 6, 0, tzinfo=UTC)
        storm = plan_storm(route, 6 * 3600, 25, departure)
        self.assertEqual(storm.center_mile, 175.0)
        self.assertEqual(storm.peak_time, datetime(2026, 3, 10, 9, 0, tzinfo=UTC))
        self.assertEqual(plan_storm(route, 6 * 3600, 50, departure).center_mile, 150.0)

    def test_route_shorter_than_two_intervals_centres_on_its_midpoint(self):
        route = Polyline(east_west(35.0, -100.0, -99.47, segments=20))
        storm = plan_storm(route, 3600, 50, datetime(2026, 3, 10, 6, 0, tzinfo=UTC))
        self.assertAlmostEqual(storm.center_mile, route.total_miles / 2)


class DemoStormPlanningTests(SimpleTestCase):
    def plan(self, load=42_000, interval=25, storm=True, weather=None):
        return run_plan(trip(load=load, interval=interval, demo_storm=storm), make_providers(weather=weather))

    def stormed_route(self, plan):
        route_id = plan["meta"]["demo_storm"]["route_id"]
        for route in plan["routes"]:
            if route["id"] == route_id:
                return route
        raise AssertionError("stormed route missing from the plan")

    def checkpoint_at(self, route, mile):
        for checkpoint in route["checkpoints"]:
            if checkpoint["mile"] == mile:
                return checkpoint
        raise AssertionError(f"no checkpoint at mile {mile}")

    def test_off_by_default(self):
        plan = self.plan(storm=False)
        self.assertIsNone(plan["meta"]["demo_storm"])
        self.assertEqual(max(max(point["wind"]) for point in plan["heatmap"]["points"]), 5.0)

    def test_storm_hits_the_route_that_would_have_been_recommended(self):
        calm = self.plan(storm=False)
        stormy = self.plan()
        info = stormy["meta"]["demo_storm"]
        hit = self.stormed_route(stormy)

        self.assertEqual(info["route_id"], calm["routes"][0]["id"])
        self.assertNotEqual(stormy["routes"][0]["id"], info["route_id"])
        self.assertEqual(hit["rank"], 3)
        self.assertGreater(hit["summary"]["no_travel_miles"], 0.0)
        self.assertTrue(hit["recommendation_reason"].startswith("Avoided:"))
        self.assertIn("No-Travel miles", hit["recommendation_reason"])
        self.assertTrue(stormy["routes"][0]["recommendation_reason"].startswith("Recommended:"))

    def test_neighbouring_routes_feel_the_edge_of_the_front_but_stay_passable(self):
        plan = self.plan()
        hit_id = plan["meta"]["demo_storm"]["route_id"]
        for route in plan["routes"]:
            if route["id"] == hit_id:
                continue
            with self.subTest(route=route["id"]):
                self.assertEqual(route["summary"]["no_travel_miles"], 0.0)
                self.assertGreater(route["summary"]["average_risk_score"], 1.0)

    def test_recommendation_is_the_best_neighbour_by_tie_breaker_order(self):
        plan = self.plan()
        hit_id = plan["meta"]["demo_storm"]["route_id"]
        others = [route for route in plan["routes"] if route["id"] != hit_id]

        def tie_breakers(route):
            summary = route["summary"]
            return (
                summary["no_travel_miles"],
                summary["severe_miles"],
                summary["high_miles"],
                summary["average_risk_score"],
                route["duration_minutes"],
            )

        best = min(others, key=tie_breakers)
        self.assertEqual(plan["routes"][0]["id"], best["id"])

    def test_core_checkpoint_is_no_travel_for_every_load(self):
        for load in (10_000, 28_000, 45_000):
            with self.subTest(load_lbs=load):
                plan = self.plan(load=load)
                core = self.checkpoint_at(self.stormed_route(plan), plan["meta"]["demo_storm"]["center_mile"])
                self.assertEqual(core["risk_level"], "no_travel")
                self.assertGreaterEqual(core["wind_mph"], 55.0)
                self.assertFalse(core["load_escalated"])

    def test_load_weight_decides_the_checkpoints_beside_the_core(self):
        light = self.plan(load=28_000)
        heavy = self.plan(load=42_000)
        center = light["meta"]["demo_storm"]["center_mile"]
        for offset in (-25.0, 25.0):
            with self.subTest(offset_miles=offset):
                beside_light = self.checkpoint_at(self.stormed_route(light), center + offset)
                beside_heavy = self.checkpoint_at(self.stormed_route(heavy), center + offset)
                self.assertGreaterEqual(beside_light["wind_mph"], 45.0)
                self.assertLess(beside_light["wind_mph"], 55.0)
                self.assertEqual((beside_light["risk_level"], beside_light["load_escalated"]), ("severe", False))
                self.assertEqual((beside_heavy["risk_level"], beside_heavy["load_escalated"]), ("no_travel", True))
        self.assertGreater(
            self.stormed_route(heavy)["summary"]["no_travel_miles"],
            self.stormed_route(light)["summary"]["no_travel_miles"],
        )

    def test_works_at_every_checkpoint_interval(self):
        for interval in (10, 25, 50):
            with self.subTest(interval=interval):
                plan = self.plan(interval=interval)
                hit = self.stormed_route(plan)
                self.assertGreater(hit["summary"]["no_travel_miles"], 0.0)
                self.assertNotEqual(plan["routes"][0]["id"], hit["id"])
                escalated = [c for c in hit["checkpoints"] if c["load_escalated"]]
                self.assertTrue(escalated)

    def test_front_is_visible_in_the_heatmap_at_its_peak_hour(self):
        plan = self.plan()
        info = plan["meta"]["demo_storm"]
        hour = round(info["peak_offset_hours"])
        points = plan["heatmap"]["points"]
        self.assertGreaterEqual(max(p["wind"][hour] for p in points), 55.0)
        self.assertEqual(max(p["risk"][hour] for p in points), 5)
        self.assertEqual(max(p["risk"][plan["heatmap"]["max_offset_hours"]] for p in points), 1)

    def test_metadata_describes_the_synthetic_front(self):
        info = self.plan()["meta"]["demo_storm"]
        self.assertTrue(info["active"])
        self.assertEqual((info["peak_wind_mph"], info["peak_snow_in_hr"]), (57.0, 2.6))
        self.assertEqual(info["peak_offset_hours"], 3.0)
        self.assertIn("Synthetic", info["description"])

    def test_cached_forecasts_are_never_modified(self):
        weather = CachingFakeWeather()
        self.plan(weather=weather)
        self.assertTrue(weather.store)
        for series in weather.store.values():
            self.assertEqual(max(series.wind_mph), 5.0)
            self.assertEqual(max(series.snow_in_hr), 0.0)
            self.assertEqual(min(series.temperature_f), 50.0)
