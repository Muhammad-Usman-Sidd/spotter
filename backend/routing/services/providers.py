"""HTTP clients for geocoding (Nominatim, Open-Meteo), routing (OSRM) and hourly forecasts (Open-Meteo).

Each client implements one Protocol from contracts.py. None of these services needs an API key.
"""
import hashlib
import logging
import math
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

import httpx
from django.core.cache import cache

from .contracts import HourlySeries, Place, Providers, RouteCandidate, WeatherFetch
from .errors import GeocodingError, NoRouteError, RoutingError, WeatherError
from .geometry import Coord, GridKey, grid_to_coord

logger = logging.getLogger(__name__)

USER_AGENT = "SpotterWeatherRouting/1.0 (route risk assessment service)"
CM_PER_INCH = 2.54
COORDINATE_PATTERN = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

_shared_client: httpx.Client | None = None


def shared_client() -> httpx.Client:
    """One pooled HTTP client for every service, created on first use, so connections stay warm."""
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.Client(
            timeout=httpx.Timeout(25.0, connect=8.0),
            headers={"User-Agent": USER_AGENT},
            transport=httpx.HTTPTransport(retries=2),
        )
    return _shared_client


def _get(client: httpx.Client, url: str, error_type: type[Exception], service: str) -> httpx.Response:
    try:
        return client.get(url)
    except httpx.TimeoutException as exc:
        raise error_type(f"{service} timed out") from exc
    except httpx.HTTPError as exc:
        raise error_type(f"{service} is unreachable") from exc


def _number(value: Any) -> float:
    """Open-Meteo sends null for missing hours; treat them as zero."""
    if value is None:
        return 0.0
    return float(value)


def _chunk(items: Sequence[GridKey], size: int) -> list[list[GridKey]]:
    chunks: list[list[GridKey]] = []
    for start in range(0, len(items), size):
        chunks.append(list(items[start : start + size]))
    return chunks


def parse_coordinate_pair(text: str) -> Coord | None:
    """Accepts "35.5, -97.25" style input so a dispatcher can skip geocoding entirely."""
    match = COORDINATE_PATTERN.match(text)
    if not match:
        return None
    lat = float(match.group(1))
    lon = float(match.group(2))
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return (lat, lon)


class GeocodingClient:
    """Nominatim first, Open-Meteo geocoding as a fallback. Results are cached for 24 hours."""

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    CACHE_TTL_SECONDS = 24 * 3600

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or shared_client()

    def geocode(self, query: str) -> Place:
        text = " ".join(query.split())
        pair = parse_coordinate_pair(text)
        if pair is not None:
            return Place(text, f"{pair[0]:.4f}, {pair[1]:.4f}", pair[0], pair[1])

        cache_key = "geocode:" + hashlib.sha1(text.lower().encode("utf-8")).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        place = self._nominatim(text)
        if place is None:
            place = self._open_meteo(text)
        if place is None:
            raise GeocodingError(f"No location found for '{text}'")

        cache.set(cache_key, place, self.CACHE_TTL_SECONDS)
        return place

    def _nominatim(self, text: str) -> Place | None:
        try:
            response = self._client.get(
                self.NOMINATIM_URL, params={"q": text, "format": "jsonv2", "limit": "1"}
            )
            response.raise_for_status()
            results = response.json()
            if not results:
                return None
            top = results[0]
            return Place(text, str(top["display_name"]), float(top["lat"]), float(top["lon"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Nominatim lookup failed for %r: %s", text, exc)
            return None

    def _open_meteo(self, text: str) -> Place | None:
        name = text.split(",")[0].strip()
        try:
            response = self._client.get(
                self.OPEN_METEO_URL,
                params={"name": name, "count": "1", "language": "en", "format": "json"},
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if not results:
                return None
            top = results[0]
            label_parts: list[str] = []
            for part in (top.get("name"), top.get("admin1"), top.get("country")):
                if part:
                    label_parts.append(str(part))
            return Place(text, ", ".join(label_parts), float(top["latitude"]), float(top["longitude"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Open-Meteo geocoding failed for %r: %s", text, exc)
            return None


def _route_name(route: dict[str, Any]) -> str:
    """Up to three unique road names from the OSRM leg summaries, e.g. "I-40, I-27, US-87"."""
    names: list[str] = []
    for leg in route.get("legs", []):
        summary = str(leg.get("summary", "")).replace(";", ",")
        for part in summary.split(","):
            name = part.strip()
            if name and name not in names:
                names.append(name)
    return ", ".join(names[:3])


def _parse_osrm_route(route: dict[str, Any]) -> RouteCandidate:
    coordinates: list[Coord] = []
    for point in route["geometry"]["coordinates"]:
        lon = float(point[0])  # GeoJSON order is (lon, lat)
        lat = float(point[1])
        coordinates.append((lat, lon))
    return RouteCandidate(
        coordinates=coordinates,
        duration_seconds=float(route["duration"]),
        distance_meters=float(route["distance"]),
        summary=_route_name(route),
    )


def parse_osrm_routes(payload: dict[str, Any]) -> list[RouteCandidate]:
    code = payload.get("code")
    if code == "NoRoute":
        raise NoRouteError("No drivable route exists between the origin and destination")
    if code != "Ok":
        raise RoutingError(str(payload.get("message") or f"Routing service error: {code}"))
    try:
        candidates: list[RouteCandidate] = []
        for route in payload["routes"]:
            candidates.append(_parse_osrm_route(route))
        return candidates
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise RoutingError("Routing service returned a malformed response") from exc


class OsrmClient:
    """The public OSRM demo server. ``alternatives`` asks OSRM for up to that many extra routes."""

    BASE_URL = "https://router.project-osrm.org/route/v1/driving/"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or shared_client()

    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RouteCandidate]:
        path_parts: list[str] = []
        for lat, lon in waypoints:
            path_parts.append(f"{lon:.6f},{lat:.6f}")
        path = ";".join(path_parts)

        alternatives_flag = str(alternatives) if alternatives else "false"
        url = (
            f"{self.BASE_URL}{path}?alternatives={alternatives_flag}"
            "&overview=full&geometries=geojson&steps=true"
        )
        response = _get(self._client, url, RoutingError, "Routing service")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RoutingError(f"Routing service returned HTTP {response.status_code}") from exc
        if not isinstance(payload, dict):
            raise RoutingError("Routing service returned a malformed response")
        return parse_osrm_routes(payload)


def _series_from_location(location: dict[str, Any]) -> HourlySeries:
    hourly = location["hourly"]
    units = location.get("hourly_units") or {}
    snowfall_in_cm = str(units.get("snowfall", "")).lower() == "cm"

    wind: list[float] = []
    rain: list[float] = []
    snow: list[float] = []
    temperature: list[float] = []
    for index in range(len(hourly["time"])):
        wind.append(_number(hourly["wind_speed_10m"][index]))
        rain_total = _number(hourly["rain"][index]) + _number(hourly["showers"][index])
        rain.append(round(rain_total, 4))
        snowfall = _number(hourly["snowfall"][index])
        if snowfall_in_cm:
            snowfall = snowfall / CM_PER_INCH
        snow.append(round(snowfall, 4))
        temperature.append(_number(hourly["temperature_2m"][index]))

    start = datetime.fromisoformat(hourly["time"][0]).replace(tzinfo=timezone.utc)
    return HourlySeries(
        start=start,
        wind_mph=tuple(wind),
        rain_in_hr=tuple(rain),
        snow_in_hr=tuple(snow),
        temperature_f=tuple(temperature),
    )


def parse_forecast_payload(payload: Any, expected: int) -> list[HourlySeries]:
    """Open-Meteo answers a multi-coordinate request with a list and a single one with an object."""
    if isinstance(payload, list):
        locations = payload
    else:
        locations = [payload]
    if len(locations) != expected:
        raise WeatherError(f"Forecast service returned {len(locations)} locations, expected {expected}")

    series: list[HourlySeries] = []
    try:
        for location in locations:
            series.append(_series_from_location(location))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("Forecast service returned a malformed response") from exc

    for entry in series:
        if entry.hour_count == 0:
            raise WeatherError("Forecast service returned an empty hourly series")
    return series


class OpenMeteoClient:
    """Hourly wind, rain, snow and temperature for many grid cells in a few batched requests."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    HOURLY_VARIABLES = "temperature_2m,wind_speed_10m,rain,showers,snowfall"
    BATCH_SIZE = 45
    MAX_WORKERS = 4
    WINDOW_DAYS = 5
    CACHE_TTL_SECONDS = 30 * 60

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or shared_client()

    def fetch(self, keys: Sequence[GridKey], start_date: date) -> WeatherFetch:
        """Forecast series for every grid cell, served from cache where possible.

        Cache misses are split into batches of up to 45 coordinates and up to 4 batches are in
        flight at once, so hundreds of checkpoints cost a handful of HTTP calls.
        """
        series: dict[GridKey, HourlySeries] = {}
        missing: list[GridKey] = []
        seen: set[GridKey] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            cached = cache.get(self._cache_key(key, start_date))
            if cached is None:
                missing.append(key)
            else:
                series[key] = cached
        cache_hits = len(series)

        batches = _chunk(missing, self.BATCH_SIZE)
        if batches:
            worker_count = min(self.MAX_WORKERS, len(batches))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures: list[Future[list[HourlySeries]]] = []
                for batch in batches:
                    futures.append(pool.submit(self._fetch_batch, batch, start_date))

                for batch, future in zip(batches, futures):
                    batch_series = future.result()
                    fresh: dict[str, HourlySeries] = {}
                    for key, value in zip(batch, batch_series):
                        series[key] = value
                        fresh[self._cache_key(key, start_date)] = value
                    cache.set_many(fresh, self.CACHE_TTL_SECONDS)

        return WeatherFetch(series=series, cache_hits=cache_hits, http_requests=len(batches))

    @staticmethod
    def _cache_key(key: GridKey, start_date: date) -> str:
        return f"weather:{key[0]}:{key[1]}:{start_date.isoformat()}"

    def _fetch_batch(self, batch: Sequence[GridKey], start_date: date) -> list[HourlySeries]:
        latitudes: list[str] = []
        longitudes: list[str] = []
        for key in batch:
            lat, lon = grid_to_coord(key)
            latitudes.append(f"{lat:.2f}")
            longitudes.append(f"{lon:.2f}")
        end_date = start_date + timedelta(days=self.WINDOW_DAYS - 1)

        query = "&".join(
            [
                "latitude=" + ",".join(latitudes),
                "longitude=" + ",".join(longitudes),
                f"hourly={self.HOURLY_VARIABLES}",
                "wind_speed_unit=mph",
                "precipitation_unit=inch",
                "temperature_unit=fahrenheit",
                "timezone=GMT",
                f"start_date={start_date.isoformat()}",
                f"end_date={end_date.isoformat()}",
            ]
        )
        response = _get(self._client, f"{self.BASE_URL}?{query}", WeatherError, "Forecast service")
        if response.status_code >= 400:
            raise WeatherError(self._failure_reason(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherError("Forecast service returned a malformed response") from exc
        return parse_forecast_payload(payload, len(batch))

    @staticmethod
    def _failure_reason(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("reason"):
                return f"Forecast service rejected the request: {body['reason']}"
        except ValueError:
            pass
        return f"Forecast service returned HTTP {response.status_code}"


def build_default_providers() -> Providers:
    """Composition root: the real HTTP clients, wired into the planner by the view."""
    return Providers(geocoder=GeocodingClient(), router=OsrmClient(), weather=OpenMeteoClient())
