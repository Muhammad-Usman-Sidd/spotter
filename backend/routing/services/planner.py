"""Application service for POST /api/plan/: geocode, find routes, sample weather, score, rank."""
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .contracts import Place, Providers, WeatherFetch
from .demo_storm import STORM_PEAK_SNOW_IN_HR, STORM_PEAK_WIND_MPH, DemoStorm, apply_storm, plan_storm
from .dtos import (
    CheckpointDto,
    DemoStormDto,
    HeatmapDto,
    HeatmapPointDto,
    PlaceDto,
    PlanMetaDto,
    RiskSummaryDto,
    RouteAlertDto,
    RouteDto,
    TripPlanDto,
    TripRequest,
)
from .errors import PlanningError
from .geometry import (
    GridKey,
    RouteSample,
    checkpoint_eta,
    grid_to_coord,
    haversine_miles,
    simplify_polyline,
    snap_to_grid,
)
from .ranking import RouteRisk, explain_ranking, rank_routes, summarize_route
from .risk_engine import RiskLevel, assess_conditions, describe_assessment
from .route_discovery import HEAVY_TRUCK_DURATION_FACTOR, RouteDiscovery, RouteOption

MIN_TRIP_MILES = 1.0
HEATMAP_HOURS = 48
HEATMAP_MIN_SPACING_MILES = 20.0
HEATMAP_MAX_POINTS_PER_ROUTE = 45
HEATMAP_RADIUS_FACTOR = 0.9
GEOMETRY_TOLERANCE_DEGREES = 0.0004


@dataclass(frozen=True)
class EvaluatedRoute:
    option: RouteOption
    checkpoints: list[CheckpointDto]
    alerts: list[RouteAlertDto]
    risk: RouteRisk
    checkpoints_outside_forecast: int


def unique_grid_keys(sample_lists: Sequence[Sequence[RouteSample]]) -> list[GridKey]:
    """Weather grid cells for every sample, first-seen order, each cell once."""
    keys: list[GridKey] = []
    seen: set[GridKey] = set()
    for samples in sample_lists:
        for sample in samples:
            key = snap_to_grid(sample.lat, sample.lon)
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def heatmap_spacing_miles(distance_miles: float) -> float:
    """At most 45 heatmap points per route, never closer than 20 miles apart."""
    return max(HEATMAP_MIN_SPACING_MILES, distance_miles / HEATMAP_MAX_POINTS_PER_ROUTE)


def evaluate_route(
    option: RouteOption,
    samples: Sequence[RouteSample],
    departure: datetime,
    load_weight_lbs: int,
    forecast: WeatherFetch,
) -> EvaluatedRoute:
    """Scores every checkpoint against the forecast hour the truck actually arrives there."""
    checkpoints: list[CheckpointDto] = []
    alerts: list[RouteAlertDto] = []
    levels: list[RiskLevel] = []
    outside_forecast = 0

    for sample in samples:
        series = forecast.series[snap_to_grid(sample.lat, sample.lon)]
        eta = checkpoint_eta(departure, sample.mile, option.distance_miles, option.duration_seconds)
        if not series.covers(eta):
            outside_forecast += 1

        conditions = series.at(eta)
        assessment = assess_conditions(conditions, load_weight_lbs)
        levels.append(assessment.level)

        eta_text = eta.replace(microsecond=0).isoformat()
        mile = round(sample.mile, 1)
        load_rule_text = None
        if assessment.load_rule is not None:
            load_rule_text = assessment.load_rule.description
        temperature = None
        if conditions.temperature_f is not None:
            temperature = round(conditions.temperature_f)

        checkpoints.append(
            CheckpointDto(
                mile=mile,
                lat=round(sample.lat, 5),
                lon=round(sample.lon, 5),
                eta=eta_text,
                wind_mph=round(conditions.wind_mph, 1),
                rain_in_hr=round(conditions.rain_in_hr, 2),
                snow_in_hr=round(conditions.snow_in_hr, 2),
                temperature_f=temperature,
                risk_level=assessment.level.key,
                risk_score=int(assessment.level),
                load_escalated=assessment.load_escalated,
                load_rule=load_rule_text,
            )
        )

        if assessment.level >= RiskLevel.SEVERE:
            alerts.append(
                RouteAlertDto(
                    mile=mile,
                    eta=eta_text,
                    risk_level=assessment.level.key,
                    load_escalated=assessment.load_escalated,
                    message=describe_assessment(conditions, assessment, load_weight_lbs),
                )
            )

    sample_miles = [sample.mile for sample in samples]
    risk = summarize_route(sample_miles, levels, option.distance_miles, option.duration_seconds / 60.0)
    return EvaluatedRoute(option, checkpoints, alerts, risk, outside_forecast)


def build_heatmap(
    keys: Sequence[GridKey],
    forecast: WeatherFetch,
    departure: datetime,
    load_weight_lbs: int,
    radius_miles: float,
) -> HeatmapDto:
    """Risk and raw weather for hours 0..48 after departure, so the slider never calls the API."""
    points: list[HeatmapPointDto] = []
    for key in keys:
        series = forecast.series[key]
        risk: list[int] = []
        wind: list[float] = []
        rain: list[float] = []
        snow: list[float] = []
        for hour in range(HEATMAP_HOURS + 1):
            conditions = series.at(departure + timedelta(hours=hour))
            assessment = assess_conditions(conditions, load_weight_lbs)
            risk.append(int(assessment.level))
            wind.append(round(conditions.wind_mph, 1))
            rain.append(round(conditions.rain_in_hr, 2))
            snow.append(round(conditions.snow_in_hr, 2))
        lat, lon = grid_to_coord(key)
        points.append(HeatmapPointDto(lat=lat, lon=lon, risk=risk, wind=wind, rain=rain, snow=snow))

    return HeatmapDto(
        start=departure.isoformat(),
        max_offset_hours=HEATMAP_HOURS,
        radius_miles=round(radius_miles, 1),
        points=points,
    )


def to_place_dto(place: Place) -> PlaceDto:
    return PlaceDto(query=place.query, label=place.label, lat=place.lat, lon=place.lon)


def to_risk_summary_dto(risk: RouteRisk) -> RiskSummaryDto:
    return RiskSummaryDto(
        no_travel_miles=round(risk.no_travel_miles, 1),
        severe_miles=round(risk.severe_miles, 1),
        high_miles=round(risk.high_miles, 1),
        moderate_miles=round(risk.moderate_miles, 1),
        low_miles=round(risk.low_miles, 1),
        average_risk_score=round(risk.average_risk_score, 2),
    )


def to_route_dto(evaluated: EvaluatedRoute, rank: int, reason: str) -> RouteDto:
    option = evaluated.option
    simplified = simplify_polyline(option.polyline.coords, GEOMETRY_TOLERANCE_DEGREES)
    geometry: list[list[float]] = []
    for lat, lon in simplified:
        geometry.append([round(lat, 5), round(lon, 5)])

    return RouteDto(
        id=option.id,
        name=option.name,
        source=option.source,
        rank=rank,
        recommended=rank == 1,
        distance_miles=round(option.distance_miles, 1),
        duration_minutes=round(option.duration_seconds / 60.0, 1),
        base_duration_minutes=round(option.base_duration_seconds / 60.0, 1),
        summary=to_risk_summary_dto(evaluated.risk),
        recommendation_reason=reason,
        geometry=geometry,
        checkpoints=evaluated.checkpoints,
        alerts=evaluated.alerts,
    )


def to_demo_storm_dto(storm: DemoStorm, target: RouteOption, departure: datetime) -> DemoStormDto:
    offset_hours = max((storm.peak_time - departure).total_seconds() / 3600.0, 0.0)
    description = (
        f"Synthetic winter front: peak wind {STORM_PEAK_WIND_MPH:.0f} mph and snowfall up to "
        f"{STORM_PEAK_SNOW_IN_HR:.1f} in/hr, stalled over {target.name} and peaking when the "
        "truck arrives. Weather away from the front is live forecast data."
    )
    return DemoStormDto(
        active=True,
        route_id=target.id,
        route_name=target.name,
        center_lat=round(storm.center[0], 5),
        center_lon=round(storm.center[1], 5),
        center_mile=round(storm.center_mile, 1),
        radius_miles=round(storm.sigma_miles, 1),
        peak_time=storm.peak_time.isoformat(),
        peak_offset_hours=round(offset_hours, 2),
        peak_wind_mph=STORM_PEAK_WIND_MPH,
        peak_snow_in_hr=STORM_PEAK_SNOW_IN_HR,
        description=description,
    )


class TripPlanner:
    """The use case behind POST /api/plan/. Providers are injected, so tests run with fakes."""

    def __init__(self, providers: Providers) -> None:
        self._geocoder = providers.geocoder
        self._weather = providers.weather
        self._route_discovery = RouteDiscovery(providers.router)

    def plan(self, request: TripRequest) -> TripPlanDto:
        started = time.perf_counter()

        origin = self._geocoder.geocode(request.origin)
        destination = self._geocoder.geocode(request.destination)
        if haversine_miles(origin.coord, destination.coord) < MIN_TRIP_MILES:
            raise PlanningError("Origin and destination resolve to the same location")

        discovery = self._route_discovery.find_routes(origin, destination)
        options = discovery.options
        warnings = list(discovery.warnings)
        departure = request.departure.astimezone(timezone.utc)

        checkpoint_samples: list[list[RouteSample]] = []
        heatmap_samples: list[list[RouteSample]] = []
        heatmap_spacings: list[float] = []
        for option in options:
            checkpoint_samples.append(option.polyline.sample(request.interval_miles))
            spacing = heatmap_spacing_miles(option.distance_miles)
            heatmap_spacings.append(spacing)
            heatmap_samples.append(option.polyline.sample(spacing))

        heatmap_keys = unique_grid_keys(heatmap_samples)
        all_keys = unique_grid_keys([*checkpoint_samples, *heatmap_samples])
        forecast = self._weather.fetch(all_keys, departure.date())

        storm_dto: DemoStormDto | None = None
        if request.demo_storm:
            forecast, storm_dto = self._inject_demo_storm(
                options, checkpoint_samples, departure, request, forecast
            )

        evaluated = self._evaluate_all(options, checkpoint_samples, departure, request.load_weight_lbs, forecast)
        risks = [route.risk for route in evaluated]
        order = rank_routes(risks)
        reasons = explain_ranking(risks, order)

        outside_forecast = 0
        for route in evaluated:
            outside_forecast += route.checkpoints_outside_forecast
        if outside_forecast:
            warnings.append(
                f"{outside_forecast} checkpoint ETAs fall outside the forecast window; "
                "the nearest available hour was used"
            )

        routes: list[RouteDto] = []
        for rank, index in enumerate(order, start=1):
            routes.append(to_route_dto(evaluated[index], rank, reasons[index]))

        radius_miles = max(heatmap_spacings) * HEATMAP_RADIUS_FACTOR
        heatmap = build_heatmap(heatmap_keys, forecast, departure, request.load_weight_lbs, radius_miles)

        meta = PlanMetaDto(
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            weather_points=len(all_keys),
            weather_requests=forecast.http_requests,
            cache_hits=forecast.cache_hits,
            heavy_truck_factor=HEAVY_TRUCK_DURATION_FACTOR,
            warnings=warnings,
            demo_storm=storm_dto,
        )
        return TripPlanDto(
            origin=to_place_dto(origin),
            destination=to_place_dto(destination),
            departure_time=departure.isoformat(),
            load_weight_lbs=request.load_weight_lbs,
            interval_miles=request.interval_miles,
            routes=routes,
            heatmap=heatmap,
            meta=meta,
        )

    @staticmethod
    def _evaluate_all(
        options: Sequence[RouteOption],
        checkpoint_samples: Sequence[Sequence[RouteSample]],
        departure: datetime,
        load_weight_lbs: int,
        forecast: WeatherFetch,
    ) -> list[EvaluatedRoute]:
        evaluated: list[EvaluatedRoute] = []
        for option, samples in zip(options, checkpoint_samples):
            evaluated.append(evaluate_route(option, samples, departure, load_weight_lbs, forecast))
        return evaluated

    def _inject_demo_storm(
        self,
        options: Sequence[RouteOption],
        checkpoint_samples: Sequence[Sequence[RouteSample]],
        departure: datetime,
        request: TripRequest,
        forecast: WeatherFetch,
    ) -> tuple[WeatherFetch, DemoStormDto]:
        """Puts the synthetic front on the route that real weather would have recommended."""
        baseline = self._evaluate_all(options, checkpoint_samples, departure, request.load_weight_lbs, forecast)
        baseline_risks = [route.risk for route in baseline]
        target = options[rank_routes(baseline_risks)[0]]

        storm = plan_storm(target.polyline, target.duration_seconds, request.interval_miles, departure)
        stormed_forecast = replace(forecast, series=apply_storm(forecast.series, storm))
        return stormed_forecast, to_demo_storm_dto(storm, target, departure)
