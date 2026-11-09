"""Haversine distance, checkpoint sampling, ETAs, the weather grid and route-shaping helpers."""
import math
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from routing.services.geometry import (
    MILES_PER_DEGREE_LAT,
    Polyline,
    checkpoint_eta,
    corridor_overlap_ratio,
    grid_to_coord,
    haversine_miles,
    lateral_waypoint,
    simplify_polyline,
    snap_to_grid,
)

from .fakes import east_west

UTC = timezone.utc


class HaversineTests(SimpleTestCase):
    def test_known_distances(self):
        self.assertAlmostEqual(haversine_miles((0.0, 0.0), (1.0, 0.0)), MILES_PER_DEGREE_LAT, places=6)
        new_york = (40.7128, -74.0060)
        los_angeles = (34.0522, -118.2437)
        self.assertAlmostEqual(haversine_miles(new_york, los_angeles), 2445.0, delta=10.0)

    def test_zero_and_symmetry(self):
        a, b = (35.0, -100.0), (36.2, -97.4)
        self.assertEqual(haversine_miles(a, a), 0.0)
        self.assertAlmostEqual(haversine_miles(a, b), haversine_miles(b, a))


class SamplingTests(SimpleTestCase):
    def test_polyline_requires_two_vertices(self):
        with self.assertRaises(ValueError):
            Polyline([(0.0, 0.0)])

    def test_samples_land_on_interval_multiples_and_end_at_the_destination(self):
        line = Polyline([(0.0, 0.0), (0.4, 0.0), (1.0, 0.0)])
        samples = line.sample(10)
        self.assertEqual([sample.mile for sample in samples[:-1]], [0, 10, 20, 30, 40, 50, 60])
        self.assertAlmostEqual(samples[-1].mile, MILES_PER_DEGREE_LAT)
        self.assertEqual((samples[-1].lat, samples[-1].lon), (1.0, 0.0))
        self.assertAlmostEqual(samples[3].lat, 30 / MILES_PER_DEGREE_LAT, places=9)

    def test_every_supported_interval(self):
        line = Polyline(east_west(35.0, -100.0, -97.0))
        for interval in (10, 25, 50):
            with self.subTest(interval=interval):
                miles = [sample.mile for sample in line.sample(interval)]
                gaps = [miles[index + 1] - miles[index] for index in range(len(miles) - 2)]
                self.assertTrue(all(gap == interval for gap in gaps))
                self.assertLessEqual(miles[-1] - miles[-2], interval)

    def test_interval_dividing_the_route_evenly_adds_no_duplicate_endpoint(self):
        line = Polyline([(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)])
        samples = line.sample(line.total_miles / 4)
        self.assertEqual(len(samples), 5)
        self.assertAlmostEqual(samples[-1].mile, line.total_miles)

    def test_interval_longer_than_route_yields_origin_and_destination(self):
        line = Polyline([(0.0, 0.0), (0.1, 0.0)])
        samples = line.sample(50)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].mile, 0.0)

    def test_samples_follow_corners(self):
        line = Polyline([(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)])
        first_leg = haversine_miles((0.0, 0.0), (0.0, 1.0))
        sample = line.sample(100)[1]
        self.assertAlmostEqual(sample.lon, 1.0, places=9)
        self.assertAlmostEqual(sample.lat, (100 - first_leg) / MILES_PER_DEGREE_LAT, places=6)

    def test_non_positive_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            Polyline([(0.0, 0.0), (1.0, 0.0)]).sample(0)


class PointAtTests(SimpleTestCase):
    line = Polyline([(0.0, 0.0), (0.4, 0.0), (1.0, 0.0)])

    def test_interpolates_and_clamps_to_the_route_ends(self):
        self.assertEqual(self.line.point_at(0).coord, (0.0, 0.0))
        middle = self.line.point_at(30)
        self.assertEqual(middle.mile, 30)
        self.assertAlmostEqual(middle.lat, 30 / MILES_PER_DEGREE_LAT, places=9)
        self.assertEqual(self.line.point_at(-5).mile, 0.0)
        end = self.line.point_at(1e6)
        self.assertAlmostEqual(end.mile, self.line.total_miles)
        self.assertAlmostEqual(end.lat, 1.0, places=9)

    def test_agrees_with_sampling(self):
        for sample in self.line.sample(10):
            point = self.line.point_at(sample.mile)
            self.assertAlmostEqual(point.lat, sample.lat, places=9)
            self.assertAlmostEqual(point.lon, sample.lon, places=9)


class EtaTests(SimpleTestCase):
    departure = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)

    def test_eta_is_proportional_to_distance_travelled(self):
        eta = checkpoint_eta(self.departure, 150, 600, 36_000)
        self.assertEqual(eta, datetime(2026, 3, 10, 10, 30, tzinfo=UTC))

    def test_eta_endpoints_and_clamping(self):
        ten_hours_later = self.departure + timedelta(hours=10)
        self.assertEqual(checkpoint_eta(self.departure, 0, 600, 36_000), self.departure)
        self.assertEqual(checkpoint_eta(self.departure, 600, 600, 36_000), ten_hours_later)
        self.assertEqual(checkpoint_eta(self.departure, 700, 600, 36_000), ten_hours_later)
        self.assertEqual(checkpoint_eta(self.departure, 10, 0, 36_000), self.departure)


class GridTests(SimpleTestCase):
    def test_grid_snapping_collapses_nearby_points(self):
        self.assertEqual(snap_to_grid(40.2849, -97.2551), (4028, -9726))
        self.assertEqual(grid_to_coord((4028, -9726)), (40.28, -97.26))
        self.assertEqual(snap_to_grid(35.001, -100.001), snap_to_grid(35.004, -100.004))
        self.assertNotEqual(snap_to_grid(35.001, -100.001), snap_to_grid(35.006, -100.001))


class LateralWaypointTests(SimpleTestCase):
    def test_deflection_is_perpendicular_to_an_eastbound_route(self):
        origin, destination = (35.0, -100.0), (35.0, -90.0)
        north = lateral_waypoint(origin, destination, "north", 0.1)
        south = lateral_waypoint(origin, destination, "south", 0.1)
        self.assertGreater(north[0], 35.0)
        self.assertLess(south[0], 35.0)
        self.assertAlmostEqual(north[1], -95.0, places=6)
        self.assertAlmostEqual(south[1], -95.0, places=6)
        expected = 0.1 * haversine_miles(origin, destination)
        self.assertAlmostEqual(haversine_miles((35.0, -95.0), north), expected, delta=0.5)

    def test_deflection_is_orthogonal_on_a_diagonal_route(self):
        origin, destination = (30.0, -100.0), (40.0, -85.0)
        waypoint = lateral_waypoint(origin, destination, "north", 0.1)
        mid_lat, mid_lon = 35.0, -92.5
        scale = math.cos(math.radians(mid_lat))
        route = ((destination[1] - origin[1]) * scale, destination[0] - origin[0])
        offset = ((waypoint[1] - mid_lon) * scale, waypoint[0] - mid_lat)
        dot_product = route[0] * offset[0] + route[1] * offset[1]
        self.assertAlmostEqual(dot_product, 0.0, places=9)

    def test_north_and_south_are_mirror_images(self):
        origin, destination = (30.0, -100.0), (40.0, -85.0)
        north = lateral_waypoint(origin, destination, "north", 0.1)
        south = lateral_waypoint(origin, destination, "south", 0.1)
        self.assertAlmostEqual(north[0] - 35.0, 35.0 - south[0], places=9)
        self.assertAlmostEqual(north[1] + 92.5, -92.5 - south[1], places=9)

    def test_westbound_route_still_maps_north_to_higher_latitude(self):
        north = lateral_waypoint((35.0, -90.0), (35.0, -100.0), "north", 0.1)
        self.assertGreater(north[0], 35.0)

    def test_due_north_route_breaks_the_tie_toward_east(self):
        north = lateral_waypoint((30.0, -95.0), (40.0, -95.0), "north", 0.1)
        south = lateral_waypoint((30.0, -95.0), (40.0, -95.0), "south", 0.1)
        self.assertGreater(north[1], -95.0)
        self.assertLess(south[1], -95.0)

    def test_offset_is_clamped(self):
        origin, destination = (35.0, -100.0), (35.0, -90.0)
        far = lateral_waypoint(origin, destination, "north", 1.0)
        self.assertAlmostEqual(haversine_miles((35.0, -95.0), far), 150.0, delta=0.5)
        near = lateral_waypoint((35.0, -100.0), (35.0, -99.9), "north", 0.1)
        self.assertAlmostEqual(haversine_miles((35.0, -99.95), near), 5.0, delta=0.1)

    def test_identical_endpoints_are_rejected(self):
        with self.assertRaises(ValueError):
            lateral_waypoint((35.0, -100.0), (35.0, -100.0), "north", 0.1)


class PolylineToolsTests(SimpleTestCase):
    def test_simplify_drops_collinear_vertices_and_keeps_corners(self):
        coords = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (1.0, 2.0)]
        self.assertEqual(simplify_polyline(coords, 0.01), [(0.0, 0.0), (0.0, 2.0), (1.0, 2.0)])

    def test_simplify_with_large_tolerance_keeps_only_endpoints(self):
        coords = [(0.0, 0.0), (0.2, 1.0), (-0.2, 2.0), (0.0, 3.0)]
        self.assertEqual(simplify_polyline(coords, 5.0), [(0.0, 0.0), (0.0, 3.0)])

    def test_simplify_handles_short_input_and_long_straight_lines(self):
        self.assertEqual(simplify_polyline([(1.0, 1.0), (2.0, 2.0)], 0.1), [(1.0, 1.0), (2.0, 2.0)])
        long_line = east_west(35.0, -100.0, -90.0, segments=5000)
        self.assertEqual(len(simplify_polyline(long_line, 0.0004)), 2)

    def test_identical_corridors_fully_overlap(self):
        route = Polyline(east_west(35.0, -100.0, -95.0))
        self.assertAlmostEqual(corridor_overlap_ratio(route, route, 2.0), 1.0)

    def test_parallel_corridors_do_not_overlap(self):
        a = Polyline(east_west(35.0, -100.0, -95.0))
        b = Polyline(east_west(35.5, -100.0, -95.0))
        self.assertEqual(corridor_overlap_ratio(b, a, 3.0), 0.0)

    def test_shared_first_half_overlaps_about_half(self):
        reference = Polyline(east_west(35.0, -100.0, -95.0))
        diverging = east_west(35.0, -100.0, -97.5, 100)
        for step in range(1, 101):
            diverging.append((35.0 + step / 100, -97.5 + 2.5 * step / 100))
        ratio = corridor_overlap_ratio(Polyline(diverging), reference, 3.0)
        self.assertGreater(ratio, 0.4)
        self.assertLess(ratio, 0.65)
