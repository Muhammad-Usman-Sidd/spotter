"""Checkpoint risk rules from the assessment: weather thresholds and load-weight wind rules.

Pure functions only, so every threshold can be unit tested on both sides of its boundary.
"""
from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    """Ordered risk levels. The integer value is the score averaged along a route."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def label(self) -> str:
        if self is RiskLevel.NO_TRAVEL:
            return "No Travel"
        return self.name.capitalize()


# Wind in mph. Each band starts at its lower number: 25.0 is Moderate, 55.0 is No Travel.
WIND_MODERATE_FROM_MPH = 25.0
WIND_HIGH_FROM_MPH = 35.0
WIND_SEVERE_FROM_MPH = 45.0
WIND_NO_TRAVEL_FROM_MPH = 55.0


@dataclass(frozen=True)
class PrecipitationBands:
    """Rain or snow thresholds in inches per hour.

    Same convention as wind: each band starts at its lower number, so a reading exactly on a
    boundary goes to the higher-risk band. The one exception is written in the table itself:
    No Travel is "> no_travel_above", so a reading exactly on that value is still Severe.
    """

    moderate_from: float
    high_from: float
    severe_from: float
    no_travel_above: float


RAIN_BANDS = PrecipitationBands(moderate_from=0.10, high_from=0.25, severe_from=0.50, no_travel_above=1.00)
SNOW_BANDS = PrecipitationBands(moderate_from=0.5, high_from=1.0, severe_from=2.0, no_travel_above=3.0)


@dataclass(frozen=True)
class LoadRule:
    """A heavier trailer turns the same crosswind into a higher risk level.

    The load limit is strict ("over 30,000 lb"), exactly as the assessment writes it.
    """

    description: str
    wind_from_mph: float
    wind_below_mph: float
    load_over_lbs: int
    level: RiskLevel

    def applies(self, wind_mph: float, load_weight_lbs: int) -> bool:
        wind_in_band = self.wind_from_mph <= wind_mph < self.wind_below_mph
        load_over_limit = load_weight_lbs > self.load_over_lbs
        return wind_in_band and load_over_limit


NO_TRAVEL_LOAD_RULE = LoadRule(
    description="45-54 mph wind with a load over 30,000 lb is No Travel",
    wind_from_mph=WIND_SEVERE_FROM_MPH,
    wind_below_mph=WIND_NO_TRAVEL_FROM_MPH,
    load_over_lbs=30_000,
    level=RiskLevel.NO_TRAVEL,
)

SEVERE_LOAD_RULE = LoadRule(
    description="35-44 mph wind with a load over 40,000 lb is Severe",
    wind_from_mph=WIND_HIGH_FROM_MPH,
    wind_below_mph=WIND_SEVERE_FROM_MPH,
    load_over_lbs=40_000,
    level=RiskLevel.SEVERE,
)


@dataclass(frozen=True)
class WeatherConditions:
    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float
    temperature_f: float | None = None


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    wind_level: RiskLevel
    unloaded_wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_rule: LoadRule | None

    @property
    def load_escalated(self) -> bool:
        return self.load_rule is not None


def classify_wind(wind_mph: float) -> RiskLevel:
    """Low < 25, Moderate 25-34, High 35-44, Severe 45-54, No Travel >= 55 for any load."""
    if wind_mph >= WIND_NO_TRAVEL_FROM_MPH:
        return RiskLevel.NO_TRAVEL
    if wind_mph >= WIND_SEVERE_FROM_MPH:
        return RiskLevel.SEVERE
    if wind_mph >= WIND_HIGH_FROM_MPH:
        return RiskLevel.HIGH
    if wind_mph >= WIND_MODERATE_FROM_MPH:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_precipitation(rate_in_hr: float, bands: PrecipitationBands) -> RiskLevel:
    if rate_in_hr > bands.no_travel_above:
        return RiskLevel.NO_TRAVEL
    if rate_in_hr >= bands.severe_from:
        return RiskLevel.SEVERE
    if rate_in_hr >= bands.high_from:
        return RiskLevel.HIGH
    if rate_in_hr >= bands.moderate_from:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_rain(rain_in_hr: float) -> RiskLevel:
    """Low < 0.10, Moderate 0.10-0.25, High 0.25-0.50, Severe 0.50-1.00, No Travel > 1.00."""
    return classify_precipitation(rain_in_hr, RAIN_BANDS)


def classify_snow(snow_in_hr: float) -> RiskLevel:
    """Low < 0.5, Moderate 0.5-1.0, High 1.0-2.0, Severe 2.0-3.0, No Travel > 3.0."""
    return classify_precipitation(snow_in_hr, SNOW_BANDS)


def find_load_rule(wind_mph: float, load_weight_lbs: int) -> LoadRule | None:
    """The load rule that raises this wind reading, if any.

    Wind of 55 mph or more is already No Travel from classify_wind, for every load, so it is not
    counted as a load escalation.
    """
    if NO_TRAVEL_LOAD_RULE.applies(wind_mph, load_weight_lbs):
        return NO_TRAVEL_LOAD_RULE
    if SEVERE_LOAD_RULE.applies(wind_mph, load_weight_lbs):
        return SEVERE_LOAD_RULE
    return None


def assess_conditions(conditions: WeatherConditions, load_weight_lbs: int) -> RiskAssessment:
    """Checkpoint level = the worst of wind (after load rules), rain and snow."""
    unloaded_wind_level = classify_wind(conditions.wind_mph)
    load_rule = find_load_rule(conditions.wind_mph, load_weight_lbs)
    if load_rule is None:
        wind_level = unloaded_wind_level
    else:
        wind_level = load_rule.level

    rain_level = classify_rain(conditions.rain_in_hr)
    snow_level = classify_snow(conditions.snow_in_hr)
    overall_level = max(wind_level, rain_level, snow_level)

    return RiskAssessment(
        level=overall_level,
        wind_level=wind_level,
        unloaded_wind_level=unloaded_wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_rule=load_rule,
    )


def describe_assessment(
    conditions: WeatherConditions, assessment: RiskAssessment, load_weight_lbs: int
) -> str:
    """Why a checkpoint sits at its level, in words a dispatcher can act on.

    Every factor that reaches the final level is listed, so nothing that contributed is hidden.
    """
    causes: list[str] = []
    if assessment.wind_level == assessment.level:
        causes.append(_describe_wind(conditions.wind_mph, assessment, load_weight_lbs))
    if assessment.snow_level == assessment.level:
        causes.append(f"Snow {conditions.snow_in_hr:.2f} in/hr")
    if assessment.rain_level == assessment.level:
        causes.append(f"Rain {conditions.rain_in_hr:.2f} in/hr")
    return ". ".join(causes) + "."


def _describe_wind(wind_mph: float, assessment: RiskAssessment, load_weight_lbs: int) -> str:
    if assessment.load_rule is not None:
        return (
            f"Wind {wind_mph:.1f} mph with a {load_weight_lbs:,} lb load "
            f"({assessment.load_rule.description}). "
            f"At or under {assessment.load_rule.load_over_lbs:,} lb this wind is "
            f"{assessment.unloaded_wind_level.label}"
        )
    if assessment.wind_level == RiskLevel.NO_TRAVEL:
        return f"Wind {wind_mph:.1f} mph (55 mph or more is No Travel for any load)"
    return f"Wind {wind_mph:.1f} mph"
