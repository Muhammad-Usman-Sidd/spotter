"""In-memory stand-ins for the geocoder, router and forecast service, plus small test-data builders.

They satisfy the Protocols in routing/services/contracts.py, so the planner runs end to end with
no network access and fully scripted weather.
"""
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Sequence

from routing.services.contracts import HourlySeries, Place, Providers, RouteCandidate, WeatherFetch
from routing.services.dtos import TripRequest
from routing.services.errors import RoutingError
from routing.services.geometry import Coord, GridKey, Polyline, grid_to_coord
from routing.services.planner import TripPlanner

UTC = timezone.utc
FORECAST_HOURS = 120
DEPARTURE = datetime(2026, 3, 10, 6, 0, tzinfo=UTC)

ORIGIN = Place("origin", "Origin", 35.0, -100.0)
DESTINATION = Place("destination", "Destination", 35.0, -94.0)
SAME_AS_ORIGIN = Place("destination", "Destination", 35.0, -100.0)

WindFunction = Callable[[Coord, int], float]


def calm_wind(coord: Coord, hour: int) -> float:
    return 5.0


def east_west(lat: float, start_lon: float, end_lon: float, segments: int = 200) -> list[Coord]:
    points: list[Coord] = []
    for index in range(segments + 1):
        lon = start_lon + (end_lon - start_lon) * index / segments
        points.append((lat, lon))
    return points


def densify(points: Sequence[Coord], steps: int = 40) -> list[Coord]:
    path: list[Coord] = []
    for index in range(len(points) - 1):
        start_lat, start_lon = points[index]
        end_lat, end_lon = points[index + 1]
        for step in range(steps):
            fraction = step / steps
            path.append((start_lat + (end_lat - start_lat) * fraction, start_lon + (end_lon - start_lon) * fraction))
    path.append(points[-1])
    return path


def candidate_through(points: Sequence[Coord], name: str) -> RouteCandidate:
    """A straight-segment route through ``points`` driven at 62 mph."""
    path = densify(points)
    miles = Polyline(path).total_miles
    return RouteCandidate(path, miles / 62.0 * 3600.0, miles * 1609.344, name)


class FakeGeocoder:
    def __init__(self, destination: Place = DESTINATION) -> None:
        self.places = {"origin": ORIGIN, "destination": destination}

    def geocode(self, query: str) -> Place:
        return self.places[query]


class DirectOnlyRouter:
    """Answers every request with one straight route through the waypoints, like a sparse OSRM."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[Coord], int]] = []

    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]:
        self.calls.append((list(waypoints), alternatives))
        name = "I-40" if len(waypoints) == 2 else "US-287"
        return [candidate_through(waypoints, name)]


class ThreeAlternativesRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[list[Coord], int]] = []

    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]:
        self.calls.append((list(waypoints), alternatives))
        start, end = waypoints[0], waypoints[-1]
        return [
            candidate_through([start, end], "I-40"),
            candidate_through([start, (35.9, -97.0), end], "US-412"),
            candidate_through([start, (34.1, -97.0), end], "US-70"),
        ]


class DuplicateOnlyRouter:
    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]:
        return [candidate_through([ORIGIN.coord, DESTINATION.coord], "I-40")]


class ViaFailingRouter:
    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]:
        if len(waypoints) > 2:
            raise RoutingError("via routing unavailable")
        return [candidate_through(waypoints, "I-40")]


class FakeWeather:
    """Scripted forecast: wind comes from ``wind_at(coord, hour)``, rain and snow are zero."""

    def __init__(self, wind_at: WindFunction = calm_wind) -> None:
        self.wind_at = wind_at
        self.calls: list[list[GridKey]] = []

    def fetch(self, keys: Sequence[GridKey], start_date: date) -> WeatherFetch:
        self.calls.append(list(keys))
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        series: dict[GridKey, HourlySeries] = {}
        for key in keys:
            coord = grid_to_coord(key)
            wind = [self.wind_at(coord, hour) for hour in range(FORECAST_HOURS)]
            series[key] = HourlySeries(
                start=start,
                wind_mph=tuple(wind),
                rain_in_hr=(0.0,) * FORECAST_HOURS,
                snow_in_hr=(0.0,) * FORECAST_HOURS,
                temperature_f=(50.0,) * FORECAST_HOURS,
            )
        return WeatherFetch(series=series, cache_hits=0, http_requests=1)


class CachingFakeWeather(FakeWeather):
    """Keeps every series it hands out, the way the real cache does."""

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[GridKey, HourlySeries] = {}

    def fetch(self, keys: Sequence[GridKey], start_date: date) -> WeatherFetch:
        result = super().fetch(keys, start_date)
        self.store.update(result.series)
        return result


class ShortForecastWeather:
    """Only eight forecast hours, so later checkpoints fall outside the forecast window."""

    def fetch(self, keys: Sequence[GridKey], start_date: date) -> WeatherFetch:
        series = calm_series(hours=8)
        return WeatherFetch({key: series for key in keys}, cache_hits=0, http_requests=1)


def calm_series(wind: float = 5.0, snow: float = 0.0, temperature: float = 50.0, hours: int = FORECAST_HOURS) -> HourlySeries:
    return HourlySeries(
        start=datetime(2026, 3, 10, tzinfo=UTC),
        wind_mph=(wind,) * hours,
        rain_in_hr=(0.0,) * hours,
        snow_in_hr=(snow,) * hours,
        temperature_f=(temperature,) * hours,
    )


def trip(load: int = 42_000, interval: int = 50, demo_storm: bool = False) -> TripRequest:
    return TripRequest(
        origin="origin",
        destination="destination",
        departure=DEPARTURE,
        load_weight_lbs=load,
        interval_miles=interval,
        demo_storm=demo_storm,
    )


def make_providers(router: Any = None, weather: Any = None, geocoder: Any = None) -> Providers:
    return Providers(
        geocoder=geocoder or FakeGeocoder(),
        router=router or DirectOnlyRouter(),
        weather=weather or FakeWeather(),
    )


def run_plan(request: TripRequest, providers: Providers) -> dict[str, Any]:
    """Runs the planner and returns the JSON-shaped dict the API would send."""
    return TripPlanner(providers).plan(request).to_dict()
