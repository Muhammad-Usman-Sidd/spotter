"""Synthetic winter wind and snow front, used to exercise the risk rules when real weather is calm.

Off by default. When the dispatcher turns it on, the UI labels every result as synthetic.
"""
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping

from .contracts import HourlySeries
from .geometry import Coord, GridKey, Polyline, checkpoint_eta, grid_to_coord, haversine_miles

STORM_PEAK_WIND_MPH = 57.0
STORM_BASE_WIND_MPH = 6.0
STORM_PEAK_SNOW_IN_HR = 2.6
STORM_COLD_TEMPERATURE_F = 22.0
STORM_TIME_SCALE_HOURS = 12.0
STORM_MIN_SIGMA_MILES = 70.0
STORM_SIGMA_PER_INTERVAL = 2.2
STORM_CENTER_FRACTION = 0.5
STORM_MIN_SPATIAL_FACTOR = 0.005


@dataclass(frozen=True)
class DemoStorm:
    center: Coord
    center_mile: float
    sigma_miles: float
    peak_time: datetime


def sigma_for_interval(interval_miles: float) -> float:
    """Spatial scale of the front, widened when checkpoints are far apart.

    The first checkpoint either side of the centre must still land in the 45-54 mph band, where
    the 30,000 lb load rule applies. At one interval from the centre the intensity is at least
    exp(-1 / 2.2^2), about 0.81, which is 47 mph.
    """
    return max(STORM_MIN_SIGMA_MILES, STORM_SIGMA_PER_INTERVAL * interval_miles)


def storm_intensity(distance_miles: float, hours_from_peak: float, sigma_miles: float) -> float:
    """Gaussian falloff in distance from the centre and in time from the peak; 1.0 at the core."""
    spatial = (distance_miles / sigma_miles) ** 2
    temporal = (hours_from_peak / STORM_TIME_SCALE_HOURS) ** 2
    return math.exp(-spatial - temporal)


def plan_storm(
    route: Polyline, duration_seconds: float, interval_miles: float, departure: datetime
) -> DemoStorm:
    """Stalls the front over the middle of ``route``, timed to peak when the truck gets there.

    The centre snaps to a checkpoint mile marker so a checkpoint always sits in the 57 mph core,
    and the peak is floored to the forecast hour that checkpoint reads, so the core intensity is
    exactly 1.
    """
    total = route.total_miles
    middle_mile = total * STORM_CENTER_FRACTION
    center_mile = round(middle_mile / interval_miles) * interval_miles
    if not 0 < center_mile < total:
        center_mile = middle_mile

    center = route.point_at(center_mile)
    eta = checkpoint_eta(departure, center.mile, total, duration_seconds)
    return DemoStorm(
        center=center.coord,
        center_mile=center.mile,
        sigma_miles=sigma_for_interval(interval_miles),
        peak_time=eta.replace(minute=0, second=0, microsecond=0),
    )


def apply_storm(
    series_by_key: Mapping[GridKey, HourlySeries], storm: DemoStorm
) -> dict[GridKey, HourlySeries]:
    """A new mapping with the front overlaid. The input series, and so the cache, are not changed."""
    stormed: dict[GridKey, HourlySeries] = {}
    for key, series in series_by_key.items():
        stormed[key] = _overlay(series, grid_to_coord(key), storm)
    return stormed


def _overlay(series: HourlySeries, coord: Coord, storm: DemoStorm) -> HourlySeries:
    distance = haversine_miles(coord, storm.center)
    if math.exp(-((distance / storm.sigma_miles) ** 2)) < STORM_MIN_SPATIAL_FACTOR:
        return series

    wind: list[float] = []
    snow: list[float] = []
    temperature: list[float] = []
    for index in range(series.hour_count):
        hour_time = series.start + timedelta(hours=index)
        hours_from_peak = (hour_time - storm.peak_time).total_seconds() / 3600.0
        intensity = storm_intensity(distance, hours_from_peak, storm.sigma_miles)

        front_wind = STORM_BASE_WIND_MPH + (STORM_PEAK_WIND_MPH - STORM_BASE_WIND_MPH) * intensity
        wind.append(max(series.wind_mph[index], front_wind))

        front_snow = STORM_PEAK_SNOW_IN_HR * intensity
        snow.append(max(series.snow_in_hr[index], front_snow))

        original_temperature = series.temperature_f[index]
        chill = min(1.0, intensity * 1.5)
        degrees_above_cold = max(original_temperature - STORM_COLD_TEMPERATURE_F, 0.0)
        temperature.append(original_temperature - degrees_above_cold * chill)

    return replace(
        series,
        wind_mph=tuple(wind),
        snow_in_hr=tuple(snow),
        temperature_f=tuple(temperature),
    )
