"""Boundary value analysis for the assessment's risk table and load-weight rules.

Every threshold is tested just below it and exactly on it, and the load limits also just above,
because "over 30,000 lb" and "30,000 lb or more" only differ at exactly 30,000.
"""
from django.test import SimpleTestCase

from routing.services.risk_engine import (
    NO_TRAVEL_LOAD_RULE,
    SEVERE_LOAD_RULE,
    RiskLevel,
    WeatherConditions,
    assess_conditions,
    classify_rain,
    classify_snow,
    classify_wind,
    describe_assessment,
)

LOW = RiskLevel.LOW
MODERATE = RiskLevel.MODERATE
HIGH = RiskLevel.HIGH
SEVERE = RiskLevel.SEVERE
NO_TRAVEL = RiskLevel.NO_TRAVEL


def assess(wind: float, load: int, rain: float = 0.0, snow: float = 0.0):
    return assess_conditions(WeatherConditions(wind, rain, snow), load)


class RiskLevelTests(SimpleTestCase):
    def test_scores_keys_and_labels(self):
        self.assertEqual([int(level) for level in RiskLevel], [1, 2, 3, 4, 5])
        self.assertEqual(NO_TRAVEL.key, "no_travel")
        self.assertEqual(NO_TRAVEL.label, "No Travel")
        self.assertEqual(MODERATE.label, "Moderate")


class WindBoundaryTests(SimpleTestCase):
    def test_low_to_moderate_at_25_mph(self):
        self.assertEqual(classify_wind(24.9), LOW)
        self.assertEqual(classify_wind(25.0), MODERATE)

    def test_moderate_to_high_at_35_mph(self):
        self.assertEqual(classify_wind(34.9), MODERATE)
        self.assertEqual(classify_wind(35.0), HIGH)

    def test_high_to_severe_at_45_mph(self):
        self.assertEqual(classify_wind(44.9), HIGH)
        self.assertEqual(classify_wind(45.0), SEVERE)

    def test_severe_to_no_travel_at_55_mph(self):
        self.assertEqual(classify_wind(54.9), SEVERE)
        self.assertEqual(classify_wind(55.0), NO_TRAVEL)

    def test_extremes(self):
        self.assertEqual(classify_wind(0.0), LOW)
        self.assertEqual(classify_wind(90.0), NO_TRAVEL)


class RainBoundaryTests(SimpleTestCase):
    """Low < 0.10, Moderate 0.10-0.25, High 0.25-0.50, Severe 0.50-1.00, No Travel > 1.00."""

    def test_band_boundaries(self):
        cases = [
            (0.0, LOW),
            (0.09, LOW),
            (0.10, MODERATE),
            (0.24, MODERATE),
            (0.25, HIGH),
            (0.49, HIGH),
            (0.50, SEVERE),
            (0.99, SEVERE),
            (1.00, SEVERE),
            (1.01, NO_TRAVEL),
        ]
        for rate, expected in cases:
            with self.subTest(rain_in_hr=rate):
                self.assertEqual(classify_rain(rate), expected)


class SnowBoundaryTests(SimpleTestCase):
    """Low < 0.5, Moderate 0.5-1.0, High 1.0-2.0, Severe 2.0-3.0, No Travel > 3.0."""

    def test_band_boundaries(self):
        cases = [
            (0.0, LOW),
            (0.49, LOW),
            (0.5, MODERATE),
            (0.99, MODERATE),
            (1.0, HIGH),
            (1.99, HIGH),
            (2.0, SEVERE),
            (2.99, SEVERE),
            (3.0, SEVERE),
            (3.01, NO_TRAVEL),
        ]
        for rate, expected in cases:
            with self.subTest(snow_in_hr=rate):
                self.assertEqual(classify_snow(rate), expected)


class NoTravelWindForAnyLoadTests(SimpleTestCase):
    """Rule 1: wind of 55 mph or more is No Travel for any load."""

    def test_55_mph_is_no_travel_at_every_load(self):
        for load in (0, 10_000, 30_000, 30_001, 80_000):
            with self.subTest(load_lbs=load):
                result = assess(55.0, load)
                self.assertEqual(result.level, NO_TRAVEL)
                self.assertFalse(result.load_escalated, "55 mph is No Travel without any load rule")

    def test_54_9_mph_depends_on_load(self):
        self.assertEqual(assess(54.9, 30_000).level, SEVERE)
        self.assertEqual(assess(54.9, 30_001).level, NO_TRAVEL)


class HeavyLoadNoTravelRuleTests(SimpleTestCase):
    """Rule 2: 45-54 mph wind with a load over 30,000 lb is No Travel."""

    def test_load_boundary_at_45_mph(self):
        cases = [
            (29_999, SEVERE, False),
            (30_000, SEVERE, False),
            (30_001, NO_TRAVEL, True),
        ]
        for load, expected_level, expected_escalated in cases:
            with self.subTest(load_lbs=load):
                result = assess(45.0, load)
                self.assertEqual(result.level, expected_level)
                self.assertEqual(result.load_escalated, expected_escalated)

    def test_wind_boundary_at_30001_lb(self):
        self.assertEqual(assess(44.9, 30_001).level, HIGH)
        self.assertEqual(assess(45.0, 30_001).level, NO_TRAVEL)
        self.assertEqual(assess(54.9, 30_001).level, NO_TRAVEL)

    def test_reports_the_rule_and_the_unloaded_level(self):
        result = assess(48.0, 42_000)
        self.assertIs(result.load_rule, NO_TRAVEL_LOAD_RULE)
        self.assertEqual(result.unloaded_wind_level, SEVERE)
        self.assertEqual(result.wind_level, NO_TRAVEL)


class HeavyLoadSevereRuleTests(SimpleTestCase):
    """Rule 3: 35-44 mph wind with a load over 40,000 lb is Severe."""

    def test_load_boundary_at_35_mph(self):
        cases = [
            (39_999, HIGH, False),
            (40_000, HIGH, False),
            (40_001, SEVERE, True),
        ]
        for load, expected_level, expected_escalated in cases:
            with self.subTest(load_lbs=load):
                result = assess(35.0, load)
                self.assertEqual(result.level, expected_level)
                self.assertEqual(result.load_escalated, expected_escalated)

    def test_wind_boundary_at_40001_lb(self):
        self.assertEqual(assess(34.9, 40_001).level, MODERATE)
        self.assertEqual(assess(35.0, 40_001).level, SEVERE)
        self.assertEqual(assess(44.9, 40_001).level, SEVERE)

    def test_rule_reported(self):
        result = assess(40.0, 45_000)
        self.assertIs(result.load_rule, SEVERE_LOAD_RULE)
        self.assertEqual(result.unloaded_wind_level, HIGH)

    def test_load_between_30000_and_40000_only_affects_the_45_54_band(self):
        self.assertEqual(assess(44.9, 35_000).level, HIGH)
        self.assertEqual(assess(45.0, 35_000).level, NO_TRAVEL)

    def test_wind_below_35_is_never_escalated(self):
        for wind, expected in ((24.9, LOW), (34.9, MODERATE)):
            with self.subTest(wind_mph=wind):
                result = assess(wind, 80_000)
                self.assertEqual(result.level, expected)
                self.assertFalse(result.load_escalated)


class CombinedFactorTests(SimpleTestCase):
    def test_highest_factor_wins(self):
        self.assertEqual(assess(10, 10_000, rain=0.3, snow=0.6).level, HIGH)
        self.assertEqual(assess(10, 10_000, rain=0.0, snow=3.5).level, NO_TRAVEL)
        self.assertEqual(assess(30, 10_000, rain=0.05, snow=0.1).level, MODERATE)

    def test_escalation_is_reported_even_when_another_factor_dominates(self):
        result = assess(40.0, 45_000, rain=1.5)
        self.assertEqual(result.level, NO_TRAVEL)
        self.assertEqual(result.wind_level, SEVERE)
        self.assertTrue(result.load_escalated)

    def test_per_factor_levels_are_reported(self):
        result = assess(26.0, 10_000, rain=0.3, snow=0.0)
        self.assertEqual((result.wind_level, result.rain_level, result.snow_level), (MODERATE, HIGH, LOW))


class DispatcherExplanationTests(SimpleTestCase):
    def explain(self, wind: float, load: int, rain: float = 0.0, snow: float = 0.0) -> str:
        conditions = WeatherConditions(wind, rain, snow)
        return describe_assessment(conditions, assess_conditions(conditions, load), load)

    def test_load_escalation_names_the_rule_and_what_a_lighter_load_would_get(self):
        message = self.explain(48.0, 42_000)
        self.assertEqual(
            message,
            "Wind 48.0 mph with a 42,000 lb load (45-54 mph wind with a load over 30,000 lb is No Travel). "
            "At or under 30,000 lb this wind is Severe.",
        )

    def test_severe_escalation(self):
        message = self.explain(38.0, 45_000)
        self.assertIn("35-44 mph wind with a load over 40,000 lb is Severe", message)
        self.assertIn("At or under 40,000 lb this wind is High", message)

    def test_55_mph_says_any_load(self):
        self.assertEqual(self.explain(57.0, 10_000), "Wind 57.0 mph (55 mph or more is No Travel for any load).")

    def test_every_factor_at_the_final_level_is_listed(self):
        self.assertEqual(self.explain(50.0, 20_000, snow=2.5), "Wind 50.0 mph. Snow 2.50 in/hr.")

    def test_precipitation_only(self):
        self.assertEqual(self.explain(10.0, 20_000, rain=1.2), "Rain 1.20 in/hr.")
