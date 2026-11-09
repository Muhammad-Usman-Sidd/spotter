"""Distance, sampling and ETA math on route polylines.

Coordinates are (latitude, longitude) tuples in decimal degrees and distances are statute miles.
Everything here is pure math with no I/O, so it is unit tested directly.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Sequence

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_DEGREE_LAT = EARTH_RADIUS_MILES * math.pi / 180.0
GRID_CELLS_PER_DEGREE = 100
MILE_EPSILON = 1e-6
MIN_COS_LATITUDE = 0.05
MAX_WAYPOINT_LATITUDE = 85.0

Coord = tuple[float, float]
GridKey = tuple[int, int]
Side = Literal["north", "south"]


@dataclass(frozen=True)
class RouteSample:
    mile: float
    lat: float
    lon: float

    @property
    def coord(self) -> Coord:
        return (self.lat, self.lon)


def haversine_miles(start: Coord, end: Coord) -> float:
    """Great-circle distance between two points.

    a = sin^2(delta_lat / 2) + cos(lat1) * cos(lat2) * sin^2(delta_lon / 2)
    distance = 2 * R * asin(sqrt(a))
    """
    start_lat = math.radians(start[0])
    start_lon = math.radians(start[1])
    end_lat = math.radians(end[0])
    end_lon = math.radians(end[1])
    delta_lat = end_lat - start_lat
    delta_lon = end_lon - start_lon

    a = math.sin(delta_lat / 2.0) ** 2 + math.cos(start_lat) * math.cos(end_lat) * math.sin(delta_lon / 2.0) ** 2
    a = min(a, 1.0)  # rounding can push it a hair above 1.0 for near-antipodal points
    central_angle = 2.0 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_MILES * central_angle


def cumulative_miles(coords: Sequence[Coord]) -> list[float]:
    """Running distance from the first vertex to every vertex, starting at 0.0."""
    totals = [0.0]
    for index in range(1, len(coords)):
        segment_miles = haversine_miles(coords[index - 1], coords[index])
        totals.append(totals[-1] + segment_miles)
    return totals


class Polyline:
    """A route geometry with its cumulative distances computed once."""

    def __init__(self, coords: Sequence[Coord]) -> None:
        if len(coords) < 2:
            raise ValueError("a polyline needs at least two vertices")
        self.coords: list[Coord] = list(coords)
        self.cumulative: list[float] = cumulative_miles(self.coords)

    @property
    def total_miles(self) -> float:
        return self.cumulative[-1]

    def point_at(self, mile: float) -> RouteSample:
        """Position at ``mile`` along the route, clamped to the route ends."""
        clamped_mile = min(max(mile, 0.0), self.total_miles)
        segment = self._segment_containing(clamped_mile, search_from=0)
        return self._interpolate(segment, clamped_mile)

    def sample(self, interval_miles: float) -> list[RouteSample]:
        """Checkpoints at mile 0, at every multiple of ``interval_miles``, and at the destination.

        Each target mile is computed as ``step * interval`` instead of by repeated addition, so
        float error does not build up over a 3,000 mile route.
        """
        if interval_miles <= 0:
            raise ValueError("interval_miles must be positive")

        origin_lat, origin_lon = self.coords[0]
        samples = [RouteSample(0.0, origin_lat, origin_lon)]
        total = self.total_miles
        if total <= 0:
            return samples

        segment = 0
        step = 1
        while step * interval_miles < total - MILE_EPSILON:
            target_mile = step * interval_miles
            segment = self._segment_containing(target_mile, search_from=segment)
            samples.append(self._interpolate(segment, target_mile))
            step += 1

        destination_lat, destination_lon = self.coords[-1]
        samples.append(RouteSample(total, destination_lat, destination_lon))
        return samples

    def _segment_containing(self, mile: float, search_from: int) -> int:
        """Index ``i`` of the segment coords[i] -> coords[i + 1] whose mile range contains ``mile``."""
        last_segment = len(self.coords) - 2
        segment = search_from
        while segment < last_segment and self.cumulative[segment + 1] < mile:
            segment += 1
        return segment

    def _interpolate(self, segment: int, mile: float) -> RouteSample:
        """Linear interpolation inside one segment.

        OSRM segments are a few hundred metres long, so a straight line between two vertices is
        indistinguishable from the great-circle path.
        """
        segment_start_mile = self.cumulative[segment]
        segment_length = self.cumulative[segment + 1] - segment_start_mile
        if segment_length > 0:
            fraction = (mile - segment_start_mile) / segment_length
        else:
            fraction = 0.0

        start_lat, start_lon = self.coords[segment]
        end_lat, end_lon = self.coords[segment + 1]
        lat = start_lat + (end_lat - start_lat) * fraction
        lon = start_lon + (end_lon - start_lon) * fraction
        return RouteSample(mile, lat, lon)


def checkpoint_eta(
    departure: datetime, mile: float, total_miles: float, total_duration_seconds: float
) -> datetime:
    """Arrival time at ``mile`` assuming a constant average speed.

    ETA = departure + (mile / total_miles) * total_duration
    """
    if total_miles <= 0:
        return departure
    share_of_route = mile / total_miles
    share_of_route = min(max(share_of_route, 0.0), 1.0)
    seconds_after_departure = share_of_route * total_duration_seconds
    return departure + timedelta(seconds=seconds_after_departure)


def snap_to_grid(lat: float, lon: float) -> GridKey:
    """Nearest cell of the 0.01 degree weather grid, as integers so dictionary keys never drift."""
    row = math.floor(lat * GRID_CELLS_PER_DEGREE + 0.5)
    column = math.floor(lon * GRID_CELLS_PER_DEGREE + 0.5)
    return (row, column)


def grid_to_coord(key: GridKey) -> Coord:
    lat = round(key[0] / GRID_CELLS_PER_DEGREE, 6)
    lon = round(key[1] / GRID_CELLS_PER_DEGREE, 6)
    return (lat, lon)


def lateral_waypoint(
    origin: Coord,
    destination: Coord,
    side: Side,
    offset_ratio: float,
    min_offset_miles: float = 5.0,
    max_offset_miles: float = 150.0,
) -> Coord:
    """A waypoint beside the straight origin-destination line, used to force a different corridor.

    1. Take the midpoint of origin and destination.
    2. Write the travel direction in a local flat plane where one unit east and one unit north are
       the same distance (longitude differences are scaled by cos(mid latitude)).
    3. Rotate that direction 90 degrees to get the unit normal, and flip it to point north (east
       for a due north-south trip), so "north" and "south" mean the same thing on any heading.
    4. Move ``offset_ratio * straight-line distance`` along the normal, clamped to
       [min_offset_miles, max_offset_miles], and convert that offset from miles back to degrees.
    """
    straight_line_miles = haversine_miles(origin, destination)
    if straight_line_miles <= 0:
        raise ValueError("origin and destination must differ")

    mid_lat = (origin[0] + destination[0]) / 2.0
    mid_lon = (origin[1] + destination[1]) / 2.0
    cos_mid_lat = max(math.cos(math.radians(mid_lat)), MIN_COS_LATITUDE)

    travel_east = (destination[1] - origin[1]) * cos_mid_lat
    travel_north = destination[0] - origin[0]
    travel_length = math.hypot(travel_east, travel_north)

    normal_east = -travel_north / travel_length
    normal_north = travel_east / travel_length
    normal_points_south = normal_north < 0
    normal_points_west_on_meridian = normal_north == 0 and normal_east < 0
    if normal_points_south or normal_points_west_on_meridian:
        normal_east = -normal_east
        normal_north = -normal_north

    if side == "north":
        direction = 1.0
    else:
        direction = -1.0

    offset_miles = straight_line_miles * offset_ratio
    offset_miles = min(max(offset_miles, min_offset_miles), max_offset_miles)
    offset_degrees = offset_miles / MILES_PER_DEGREE_LAT

    waypoint_lat = mid_lat + direction * normal_north * offset_degrees
    waypoint_lon = mid_lon + direction * normal_east * offset_degrees / cos_mid_lat
    waypoint_lat = min(max(waypoint_lat, -MAX_WAYPOINT_LATITUDE), MAX_WAYPOINT_LATITUDE)
    return (waypoint_lat, waypoint_lon)


def simplify_polyline(coords: Sequence[Coord], tolerance_degrees: float) -> list[Coord]:
    """Douglas-Peucker simplification in an equirectangular plane. Endpoints are always kept.

    Uses an explicit stack instead of recursion, so a 20,000 vertex interstate geometry cannot hit
    Python's recursion limit.
    """
    count = len(coords)
    if count < 3:
        return list(coords)

    latitude_sum = 0.0
    for lat, _ in coords:
        latitude_sum += lat
    lon_scale = math.cos(math.radians(latitude_sum / count))

    plane: list[tuple[float, float]] = []
    for lat, lon in coords:
        plane.append((lon * lon_scale, lat))

    keep = [False] * count
    keep[0] = True
    keep[-1] = True

    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        first_x, first_y = plane[first]
        last_x, last_y = plane[last]
        dx = last_x - first_x
        dy = last_y - first_y
        baseline = math.hypot(dx, dy)

        farthest_distance = -1.0
        farthest_index = -1
        for index in range(first + 1, last):
            point_x, point_y = plane[index]
            if baseline == 0:
                distance = math.hypot(point_x - first_x, point_y - first_y)
            else:
                distance = abs(dy * (point_x - first_x) - dx * (point_y - first_y)) / baseline
            if distance > farthest_distance:
                farthest_distance = distance
                farthest_index = index

        if farthest_distance > tolerance_degrees:
            keep[farthest_index] = True
            stack.append((first, farthest_index))
            stack.append((farthest_index, last))

    simplified: list[Coord] = []
    for index in range(count):
        if keep[index]:
            simplified.append(coords[index])
    return simplified


def corridor_overlap_ratio(candidate: Polyline, reference: Polyline, tolerance_miles: float) -> float:
    """Share of ``candidate`` that runs within ``tolerance_miles`` of ``reference``.

    1.0 means the same corridor and 0.0 means fully separate. Both lines are resampled at half the
    tolerance, and the reference samples are bucketed into a grid whose cell edge equals the
    tolerance, so each candidate sample only checks the 3x3 cells around it.
    """
    step_miles = tolerance_miles / 2.0
    candidate_samples = candidate.sample(step_miles)
    reference_samples = reference.sample(step_miles)

    latitude_sum = 0.0
    for sample in reference_samples:
        latitude_sum += sample.lat
    mean_lat = latitude_sum / len(reference_samples)
    cell_lat_degrees = tolerance_miles / MILES_PER_DEGREE_LAT
    cell_lon_degrees = cell_lat_degrees / max(math.cos(math.radians(mean_lat)), MIN_COS_LATITUDE)

    buckets: dict[GridKey, list[Coord]] = {}
    for sample in reference_samples:
        cell = (math.floor(sample.lat / cell_lat_degrees), math.floor(sample.lon / cell_lon_degrees))
        buckets.setdefault(cell, []).append(sample.coord)

    near_count = 0
    for sample in candidate_samples:
        row = math.floor(sample.lat / cell_lat_degrees)
        column = math.floor(sample.lon / cell_lon_degrees)
        if _has_point_within(sample.coord, buckets, row, column, tolerance_miles):
            near_count += 1
    return near_count / len(candidate_samples)


def _has_point_within(
    point: Coord, buckets: dict[GridKey, list[Coord]], row: int, column: int, tolerance_miles: float
) -> bool:
    for row_offset in (-1, 0, 1):
        for column_offset in (-1, 0, 1):
            neighbours = buckets.get((row + row_offset, column + column_offset), [])
            for neighbour in neighbours:
                if haversine_miles(point, neighbour) <= tolerance_miles:
                    return True
    return False
