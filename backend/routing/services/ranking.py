"""Route-level risk: miles per level, the recommendation order, and the reason shown per route."""
from dataclasses import dataclass
from typing import NamedTuple, Sequence

from .risk_engine import RiskLevel


@dataclass(frozen=True)
class RouteRisk:
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    moderate_miles: float
    low_miles: float
    average_risk_score: float
    duration_minutes: float


class RankingKey(NamedTuple):
    """Compared field by field, left to right, like ORDER BY a, b, c. Lower is better."""

    no_travel_miles: float
    severe_miles: float
    high_miles: float
    average_risk_score: float
    duration_minutes: float


def segment_lengths(miles: Sequence[float], total_miles: float) -> list[float]:
    """Route distance each checkpoint stands for.

    A checkpoint owns the stretch from the midpoint with its previous neighbour to the midpoint
    with its next one. The first and last checkpoints extend to the route ends, so the lengths
    always add up to ``total_miles``.
    """
    last_index = len(miles) - 1
    lengths: list[float] = []
    for index in range(len(miles)):
        if index == 0:
            start = 0.0
        else:
            start = (miles[index - 1] + miles[index]) / 2.0

        if index == last_index:
            end = total_miles
        else:
            end = (miles[index] + miles[index + 1]) / 2.0

        lengths.append(max(end - start, 0.0))
    return lengths


def summarize_route(
    miles: Sequence[float], levels: Sequence[RiskLevel], total_miles: float, duration_minutes: float
) -> RouteRisk:
    """Miles at each level and the distance-weighted mean score (1 = Low ... 5 = No Travel)."""
    if len(miles) != len(levels):
        raise ValueError("miles and levels must have the same length")

    lengths = segment_lengths(miles, total_miles)
    miles_by_level: dict[RiskLevel, float] = {}
    for level in RiskLevel:
        miles_by_level[level] = 0.0

    weighted_score = 0.0
    covered_miles = 0.0
    for length, level in zip(lengths, levels):
        miles_by_level[level] += length
        weighted_score += length * int(level)
        covered_miles += length

    if covered_miles > 0:
        average = weighted_score / covered_miles
    else:
        average = float(int(levels[0]))

    return RouteRisk(
        no_travel_miles=miles_by_level[RiskLevel.NO_TRAVEL],
        severe_miles=miles_by_level[RiskLevel.SEVERE],
        high_miles=miles_by_level[RiskLevel.HIGH],
        moderate_miles=miles_by_level[RiskLevel.MODERATE],
        low_miles=miles_by_level[RiskLevel.LOW],
        average_risk_score=average,
        duration_minutes=duration_minutes,
    )


def ranking_key(risk: RouteRisk) -> RankingKey:
    """The assessment's preference order, with No Travel miles counted before Severe miles.

    1. fewest No Travel miles, 2. fewest Severe miles, 3. fewest High miles,
    4. lowest average risk, 5. shortest travel time.

    Values are rounded to the precision the UI shows, so two routes that look identical on screen
    are never separated by floating-point noise.
    """
    return RankingKey(
        no_travel_miles=round(risk.no_travel_miles, 1),
        severe_miles=round(risk.severe_miles, 1),
        high_miles=round(risk.high_miles, 1),
        average_risk_score=round(risk.average_risk_score, 2),
        duration_minutes=round(risk.duration_minutes),
    )


def rank_routes(risks: Sequence[RouteRisk]) -> list[int]:
    """Indices of ``risks`` from best to worst. Python's sort is stable, so full ties keep input order."""
    indices = list(range(len(risks)))
    indices.sort(key=lambda index: ranking_key(risks[index]))
    return indices


def explain_ranking(risks: Sequence[RouteRisk], order: Sequence[int]) -> list[str]:
    """One sentence per route, indexed like ``risks``, saying why it won or lost."""
    best = risks[order[0]]
    others: list[RouteRisk] = []
    for index in order[1:]:
        others.append(risks[index])

    reasons = [""] * len(risks)
    reasons[order[0]] = _winner_reason(best, others)
    for index in order[1:]:
        reasons[index] = _loser_reason(risks[index], best)
    return reasons


def _is_strictly_lowest(value: float, other_values: Sequence[float], digits: int) -> bool:
    if not other_values:
        return False
    rounded_value = round(value, digits)
    for other in other_values:
        if rounded_value >= round(other, digits):
            return False
    return True


def _winner_reason(best: RouteRisk, others: Sequence[RouteRisk]) -> str:
    no_travel = round(best.no_travel_miles, 1)
    severe = round(best.severe_miles, 1)
    other_no_travel = [other.no_travel_miles for other in others]
    other_severe = [other.severe_miles for other in others]
    other_average = [other.average_risk_score for other in others]

    if no_travel == 0 and severe == 0:
        hazard = "Zero Severe or No-Travel miles"
    elif no_travel == 0:
        fewest = " (fewest)" if _is_strictly_lowest(best.severe_miles, other_severe, 1) else ""
        hazard = f"Zero No-Travel miles, {severe:.1f} Severe miles{fewest}"
    else:
        fewest = " (fewest)" if _is_strictly_lowest(best.no_travel_miles, other_no_travel, 1) else ""
        hazard = f"{no_travel:.1f} No-Travel miles{fewest}, {severe:.1f} Severe miles"

    average = best.average_risk_score
    if _is_strictly_lowest(average, other_average, 2):
        risk_clause = f"lowest avg risk ({average:.2f})"
    else:
        risk_clause = f"avg risk {average:.2f}"

    hours = best.duration_minutes / 60.0
    return f"Recommended: {hazard}, {risk_clause}, {hours:.1f}h transit time"


def _loser_reason(risk: RouteRisk, best: RouteRisk) -> str:
    """Names the first ranking criterion on which this route lost to the recommended one."""
    if round(risk.no_travel_miles, 1) != round(best.no_travel_miles, 1):
        return _miles_comparison("No-Travel", risk.no_travel_miles, best.no_travel_miles)
    if round(risk.severe_miles, 1) != round(best.severe_miles, 1):
        return _miles_comparison("Severe", risk.severe_miles, best.severe_miles)
    if round(risk.high_miles, 1) != round(best.high_miles, 1):
        return _miles_comparison("High", risk.high_miles, best.high_miles)
    if round(risk.average_risk_score, 2) != round(best.average_risk_score, 2):
        return (
            f"Avoided: avg risk {risk.average_risk_score:.2f} vs "
            f"{best.average_risk_score:.2f} on recommended route"
        )
    if round(risk.duration_minutes) != round(best.duration_minutes):
        return (
            f"Slower: {risk.duration_minutes / 60.0:.1f}h transit vs "
            f"{best.duration_minutes / 60.0:.1f}h on recommended route"
        )
    return "Equivalent to the recommended route on every criterion; listed after it by route order"


def _miles_comparison(level_name: str, route_miles: float, best_miles: float) -> str:
    return f"Avoided: {route_miles:.1f} {level_name} miles vs {best_miles:.1f} mi on recommended route"
