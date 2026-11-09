"""Finds three distinct drivable routes: OSRM alternatives first, lateral waypoints for any shortfall."""
import logging
from dataclasses import dataclass

from .contracts import Place, RouteCandidate, RoutingProvider
from .errors import NoRouteError, RoutingError
from .geometry import Polyline, Side, corridor_overlap_ratio, lateral_waypoint

logger = logging.getLogger(__name__)

TARGET_ROUTE_COUNT = 3
OSRM_ALTERNATIVES = 3
DEFLECTION_RATIOS = (0.15, 0.25, 0.08)
LATERAL_SIDES: tuple[Side, Side] = ("north", "south")
MAX_DETOUR_RATIO = 1.75
DISTINCT_OVERLAP_LIMIT = 0.92

# OSRM's public server only has a car profile. Heavy trucks run slower on grades and ramps, so
# every duration is stretched by 12 percent before ETAs are computed.
HEAVY_TRUCK_DURATION_FACTOR = 1.12


@dataclass(frozen=True)
class RouteOption:
    id: str
    name: str
    source: str
    polyline: Polyline
    base_duration_seconds: float

    @property
    def distance_miles(self) -> float:
        return self.polyline.total_miles

    @property
    def duration_seconds(self) -> float:
        return self.base_duration_seconds * HEAVY_TRUCK_DURATION_FACTOR


@dataclass(frozen=True)
class RouteDiscoveryResult:
    options: list[RouteOption]
    warnings: list[str]


def overlap_tolerance_miles(shortest_route_miles: float) -> float:
    """0.5 percent of the shorter route, kept between 0.25 and 3 miles."""
    tolerance = shortest_route_miles * 0.005
    return max(0.25, min(3.0, tolerance))


class RouteDiscovery:
    def __init__(self, router: RoutingProvider) -> None:
        self._router = router

    def find_routes(self, origin: Place, destination: Place) -> RouteDiscoveryResult:
        """Up to three distinct routes, plus a warning if fewer than three could be found.

        1. Ask OSRM for alternatives and keep the distinct ones.
        2. If that leaves fewer than three, route through a waypoint pushed sideways off the
           straight line, alternating north and south and trying a wider push each round.
        3. A candidate is rejected when it is more than 1.75x the shortest route, or when 92
           percent or more of it runs along a route already kept.
        """
        options: list[RouteOption] = []
        start = origin.coord
        end = destination.coord

        for candidate in self._router.routes([start, end], alternatives=OSRM_ALTERNATIVES):
            if len(options) >= TARGET_ROUTE_COUNT:
                break
            self._add_if_distinct(options, candidate, "osrm")

        if not options:
            raise NoRouteError("No drivable route exists between the origin and destination")

        for ratio in DEFLECTION_RATIOS:
            for side in LATERAL_SIDES:
                if len(options) >= TARGET_ROUTE_COUNT:
                    break
                waypoint = lateral_waypoint(start, end, side, ratio)
                try:
                    via_routes = self._router.routes([start, waypoint, end])
                except RoutingError as exc:
                    logger.warning("Lateral %s routing at ratio %.2f failed: %s", side, ratio, exc)
                    continue
                if via_routes:
                    self._add_if_distinct(options, via_routes[0], f"lateral-{side}")

        warnings: list[str] = []
        if len(options) < TARGET_ROUTE_COUNT:
            warnings.append(
                f"Only {len(options)} of {TARGET_ROUTE_COUNT} distinct drivable routes "
                "were found for this corridor"
            )
        return RouteDiscoveryResult(options=options, warnings=warnings)

    def _add_if_distinct(self, options: list[RouteOption], candidate: RouteCandidate, source: str) -> bool:
        if len(candidate.coordinates) < 2:
            return False
        polyline = Polyline(candidate.coordinates)
        if polyline.total_miles <= 0:
            return False
        if self._is_detour(polyline, options) or self._duplicates_a_kept_route(polyline, options):
            return False

        number = len(options) + 1
        options.append(
            RouteOption(
                id=f"route-{number}",
                name=candidate.summary or f"Route {number}",
                source=source,
                polyline=polyline,
                base_duration_seconds=candidate.duration_seconds,
            )
        )
        return True

    @staticmethod
    def _shortest_miles(options: list[RouteOption]) -> float:
        shortest = options[0].distance_miles
        for option in options[1:]:
            shortest = min(shortest, option.distance_miles)
        return shortest

    def _is_detour(self, polyline: Polyline, options: list[RouteOption]) -> bool:
        if not options:
            return False
        return polyline.total_miles > self._shortest_miles(options) * MAX_DETOUR_RATIO

    def _duplicates_a_kept_route(self, polyline: Polyline, options: list[RouteOption]) -> bool:
        if not options:
            return False
        shorter_miles = min(self._shortest_miles(options), polyline.total_miles)
        tolerance = overlap_tolerance_miles(shorter_miles)
        for option in options:
            overlap = corridor_overlap_ratio(polyline, option.polyline, tolerance)
            if overlap >= DISTINCT_OVERLAP_LIMIT:
                return True
        return False
