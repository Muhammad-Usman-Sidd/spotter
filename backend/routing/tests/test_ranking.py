"""Route aggregation, the recommendation order and the per-route reason strings."""
from django.test import SimpleTestCase

from routing.services.ranking import RouteRisk, explain_ranking, rank_routes, segment_lengths, summarize_route
from routing.services.risk_engine import RiskLevel

LOW = RiskLevel.LOW
MODERATE = RiskLevel.MODERATE
HIGH = RiskLevel.HIGH
SEVERE = RiskLevel.SEVERE
NO_TRAVEL = RiskLevel.NO_TRAVEL


def risk(no_travel=0.0, severe=0.0, high=0.0, average=1.0, minutes=600.0) -> RouteRisk:
    return RouteRisk(no_travel, severe, high, 0.0, 0.0, average, minutes)


class RouteAggregationTests(SimpleTestCase):
    def test_segment_lengths_split_at_midpoints(self):
        self.assertEqual(segment_lengths([0, 25, 50, 75, 100], 100), [12.5, 25, 25, 25, 12.5])

    def test_segment_lengths_cover_uneven_spacing(self):
        lengths = segment_lengths([0, 10, 20, 25], 25)
        self.assertEqual(lengths, [5.0, 10.0, 7.5, 2.5])
        self.assertAlmostEqual(sum(lengths), 25.0)

    def test_summary_is_distance_weighted(self):
        levels = [LOW, LOW, HIGH, SEVERE, NO_TRAVEL]
        result = summarize_route([0, 25, 50, 75, 100], levels, 100, 600)
        self.assertEqual(result.low_miles, 37.5)
        self.assertEqual(result.moderate_miles, 0.0)
        self.assertEqual(result.high_miles, 25.0)
        self.assertEqual(result.severe_miles, 25.0)
        self.assertEqual(result.no_travel_miles, 12.5)
        self.assertAlmostEqual(result.average_risk_score, 2.75)
        self.assertEqual(result.duration_minutes, 600)

    def test_category_miles_sum_to_route_length(self):
        levels = [LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL, LOW]
        result = summarize_route([0, 10, 20, 30, 40, 47.3], levels, 47.3, 100)
        total = (
            result.no_travel_miles + result.severe_miles + result.high_miles + result.moderate_miles + result.low_miles
        )
        self.assertAlmostEqual(total, 47.3)

    def test_mismatched_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize_route([0, 10], [LOW], 10, 60)


class TieBreakerOrderTests(SimpleTestCase):
    """Each criterion only matters when every criterion before it is tied."""

    def test_no_travel_miles_outrank_every_other_criterion(self):
        clear_but_severe = risk(no_travel=0, severe=500, high=500, average=4.0, minutes=2000)
        blocked_briefly = risk(no_travel=10, severe=0, high=0, average=1.0, minutes=100)
        self.assertEqual(rank_routes([clear_but_severe, blocked_briefly]), [0, 1])
        self.assertEqual(rank_routes([blocked_briefly, clear_but_severe]), [1, 0])

    def test_severe_miles_break_a_no_travel_tie(self):
        a = risk(severe=10, high=0, average=1.0, minutes=500)
        b = risk(severe=0, high=300, average=3.9, minutes=900)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_high_miles_break_a_severe_tie(self):
        a = risk(high=20, average=1.0, minutes=500)
        b = risk(high=10, average=2.5, minutes=900)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_average_score_breaks_a_high_tie(self):
        a = risk(average=1.5, minutes=600)
        b = risk(average=1.2, minutes=900)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_duration_is_the_last_resort(self):
        a = risk(minutes=700)
        b = risk(minutes=650)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_full_tie_keeps_input_order(self):
        self.assertEqual(rank_routes([risk(), risk(), risk()]), [0, 1, 2])

    def test_one_tenth_of_a_mile_is_enough_to_decide(self):
        slightly_severe = risk(severe=0.1, minutes=100)
        clean_but_slow = risk(severe=0.0, minutes=5000)
        self.assertEqual(rank_routes([slightly_severe, clean_but_slow]), [1, 0])

    def test_differences_below_display_precision_are_ties(self):
        slightly_more = risk(no_travel=10.04, minutes=590)
        slightly_less = risk(no_travel=10.0, minutes=600)
        self.assertEqual(rank_routes([slightly_less, slightly_more]), [1, 0])

    def test_five_routes_each_decided_by_a_different_criterion(self):
        routes = [
            risk(no_travel=1.0),
            risk(severe=1.0),
            risk(high=1.0),
            risk(average=1.5),
            risk(minutes=601),
            risk(),
        ]
        self.assertEqual(rank_routes(routes), [5, 4, 3, 2, 1, 0])

    def test_three_route_mix(self):
        routes = [
            risk(no_travel=5, minutes=500),
            risk(severe=40, minutes=450),
            risk(severe=0, high=60, minutes=800),
        ]
        self.assertEqual(rank_routes(routes), [2, 1, 0])


class RecommendationReasonTests(SimpleTestCase):
    def test_recommended_and_avoided_phrasing(self):
        routes = [
            RouteRisk(0, 0, 0, 100, 900, 1.18, 912),
            RouteRisk(0, 75, 0, 100, 800, 1.40, 900),
            RouteRisk(0, 0, 0, 100, 900, 1.30, 950),
        ]
        order = rank_routes(routes)
        self.assertEqual(order, [0, 2, 1])
        reasons = explain_ranking(routes, order)
        self.assertEqual(
            reasons[0],
            "Recommended: Zero Severe or No-Travel miles, lowest avg risk (1.18), 15.2h transit time",
        )
        self.assertEqual(reasons[1], "Avoided: 75.0 Severe miles vs 0.0 mi on recommended route")
        self.assertEqual(reasons[2], "Avoided: avg risk 1.30 vs 1.18 on recommended route")

    def test_no_travel_and_high_loser_reasons(self):
        routes = [risk(), risk(no_travel=12.5), risk(high=30.0, minutes=600)]
        reasons = explain_ranking(routes, rank_routes(routes))
        self.assertEqual(reasons[1], "Avoided: 12.5 No-Travel miles vs 0.0 mi on recommended route")
        self.assertEqual(reasons[2], "Avoided: 30.0 High miles vs 0.0 mi on recommended route")

    def test_slower_route_reason(self):
        routes = [risk(minutes=600), risk(minutes=660)]
        reasons = explain_ranking(routes, rank_routes(routes))
        self.assertEqual(reasons[1], "Slower: 11.0h transit vs 10.0h on recommended route")

    def test_tied_route_reason(self):
        routes = [risk(), risk()]
        reasons = explain_ranking(routes, rank_routes(routes))
        self.assertTrue(reasons[1].startswith("Equivalent to the recommended route"))

    def test_winner_with_no_travel_miles_is_labelled_fewest(self):
        routes = [risk(no_travel=5.0), risk(no_travel=20.0)]
        reason = explain_ranking(routes, rank_routes(routes))[0]
        self.assertIn("5.0 No-Travel miles (fewest)", reason)

    def test_winner_with_severe_miles_is_labelled_fewest(self):
        routes = [risk(severe=5.0), risk(severe=20.0)]
        reason = explain_ranking(routes, rank_routes(routes))[0]
        self.assertIn("Zero No-Travel miles, 5.0 Severe miles (fewest)", reason)

    def test_single_route_is_recommended_without_superlatives(self):
        reason = explain_ranking([risk(average=1.4, minutes=540)], [0])[0]
        self.assertEqual(reason, "Recommended: Zero Severe or No-Travel miles, avg risk 1.40, 9.0h transit time")
