"""Interfaces for the external services, and the value objects that cross them.

The planner depends only on these Protocols, never on a concrete HTTP client. providers.py holds
the real implementations (Nominatim, OSRM, Open-Meteo); the unit tests pass in-memory fakes that
have the same methods.
"""
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, Sequence

from .geometry import Coord, GridKey
from .risk_engine import WeatherConditions


@dataclass(frozen=True)
class Place:
    query: str
    label: str
    lat: float
    lon: float

    @property
    def coord(self) -> Coord:
        return (self.lat, self.lon)


@dataclass(frozen=True)
class RouteCandidate:
    coordinates: list[Coord]
    duration_seconds: float
    distance_meters: float
    summary: str


@dataclass(frozen=True)
class HourlySeries:
    """Hourly forecast for one grid cell. ``start`` is the UTC instant of the first entry."""

    start: datetime
    wind_mph: tuple[float, ...]
    rain_in_hr: tuple[float, ...]
    snow_in_hr: tuple[float, ...]
    temperature_f: tuple[float, ...]

    @property
    def hour_count(self) -> int:
        return len(self.wind_mph)

    def hours_after_start(self, when: datetime) -> float:
        return (when - self.start).total_seconds() / 3600.0

    def index_for(self, when: datetime) -> int:
        """Index of the forecast hour that contains ``when``, clamped to the available window.

        A truck arriving at 14:40 reads the 14:00 forecast hour.
        """
        index = math.floor(self.hours_after_start(when))
        if index < 0:
            return 0
        if index >= self.hour_count:
            return self.hour_count - 1
        return index

    def covers(self, when: datetime) -> bool:
        hours = self.hours_after_start(when)
        return 0.0 <= hours < self.hour_count

    def at(self, when: datetime) -> WeatherConditions:
        index = self.index_for(when)
        return WeatherConditions(
            wind_mph=self.wind_mph[index],
            rain_in_hr=self.rain_in_hr[index],
            snow_in_hr=self.snow_in_hr[index],
            temperature_f=self.temperature_f[index],
        )


@dataclass(frozen=True)
class WeatherFetch:
    series: dict[GridKey, HourlySeries]
    cache_hits: int
    http_requests: int


class GeocodingProvider(Protocol):
    def geocode(self, query: str) -> Place: ...


class RoutingProvider(Protocol):
    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]: ...


class WeatherProvider(Protocol):
    def fetch(self, keys: Sequence[GridKey], start_date: date) -> WeatherFetch: ...


@dataclass(frozen=True)
class Providers:
    """The three dependencies the planner needs, injected through its constructor."""

    geocoder: GeocodingProvider
    router: RoutingProvider
    weather: WeatherProvider
