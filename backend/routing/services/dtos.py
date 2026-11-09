"""Typed request and response contracts for POST /api/plan/.

The view returns ``TripPlanDto.to_dict()``, so the field names below are exactly the JSON keys the
frontend reads in frontend/src/types/routing.ts. Change one side, change the other.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TripRequest:
    origin: str
    destination: str
    departure: datetime
    load_weight_lbs: int
    interval_miles: int
    demo_storm: bool = False


@dataclass(frozen=True)
class PlaceDto:
    query: str
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class CheckpointDto:
    mile: float
    lat: float
    lon: float
    eta: str
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float
    temperature_f: float | None
    risk_level: str
    risk_score: int
    load_escalated: bool
    load_rule: str | None


@dataclass(frozen=True)
class RouteAlertDto:
    """A Severe or No Travel checkpoint, listed explicitly so the dispatcher never has to hunt for it."""

    mile: float
    eta: str
    risk_level: str
    load_escalated: bool
    message: str


@dataclass(frozen=True)
class RiskSummaryDto:
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    moderate_miles: float
    low_miles: float
    average_risk_score: float


@dataclass(frozen=True)
class RouteDto:
    id: str
    name: str
    source: str
    rank: int
    recommended: bool
    distance_miles: float
    duration_minutes: float
    base_duration_minutes: float
    summary: RiskSummaryDto
    recommendation_reason: str
    geometry: list[list[float]]
    checkpoints: list[CheckpointDto]
    alerts: list[RouteAlertDto]


@dataclass(frozen=True)
class HeatmapPointDto:
    """One corridor point with 49 hourly values (hour 0 to hour 48 after departure)."""

    lat: float
    lon: float
    risk: list[int]
    wind: list[float]
    rain: list[float]
    snow: list[float]


@dataclass(frozen=True)
class HeatmapDto:
    start: str
    max_offset_hours: int
    radius_miles: float
    points: list[HeatmapPointDto]


@dataclass(frozen=True)
class DemoStormDto:
    active: bool
    route_id: str
    route_name: str
    center_lat: float
    center_lon: float
    center_mile: float
    radius_miles: float
    peak_time: str
    peak_offset_hours: float
    peak_wind_mph: float
    peak_snow_in_hr: float
    description: str


@dataclass(frozen=True)
class PlanMetaDto:
    elapsed_ms: int
    weather_points: int
    weather_requests: int
    cache_hits: int
    heavy_truck_factor: float
    warnings: list[str]
    demo_storm: DemoStormDto | None


@dataclass(frozen=True)
class TripPlanDto:
    origin: PlaceDto
    destination: PlaceDto
    departure_time: str
    load_weight_lbs: int
    interval_miles: int
    routes: list[RouteDto]
    heatmap: HeatmapDto
    meta: PlanMetaDto

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
