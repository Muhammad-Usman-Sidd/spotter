"""HTTP clients tested against scripted responses through httpx.MockTransport (no network)."""
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qs

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase

from routing.services.contracts import HourlySeries
from routing.services.errors import GeocodingError, NoRouteError, RoutingError, WeatherError
from routing.services.providers import GeocodingClient, OpenMeteoClient, OsrmClient, parse_forecast_payload, parse_osrm_routes

UTC = timezone.utc


def forecast_location(snow_unit="cm", snowfall=(5.08, 0.0, None)):
    return {
        "hourly_units": {"snowfall": snow_unit},
        "hourly": {
            "time": ["2026-03-10T00:00", "2026-03-10T01:00", "2026-03-10T02:00"],
            "temperature_2m": [30.0, 31.0, 32.0],
            "wind_speed_10m": [10.0, 20.0, None],
            "rain": [0.05, 0.0, None],
            "showers": [0.05, 0.1, 0.0],
            "snowfall": list(snowfall),
        },
    }


class ForecastParsingTests(SimpleTestCase):
    def test_units_sums_and_nulls(self):
        [series] = parse_forecast_payload([forecast_location()], 1)
        self.assertEqual(series.start, datetime(2026, 3, 10, tzinfo=UTC))
        self.assertEqual(series.wind_mph, (10.0, 20.0, 0.0))
        self.assertEqual(series.rain_in_hr, (0.1, 0.1, 0.0))
        self.assertEqual(series.snow_in_hr, (2.0, 0.0, 0.0))
        self.assertEqual(series.temperature_f, (30.0, 31.0, 32.0))

    def test_snowfall_already_in_inches_is_not_converted(self):
        [series] = parse_forecast_payload([forecast_location(snow_unit="inch", snowfall=(2.0, 1.0, 0.0))], 1)
        self.assertEqual(series.snow_in_hr, (2.0, 1.0, 0.0))

    def test_single_location_arrives_as_an_object(self):
        series = parse_forecast_payload(forecast_location(), 1)
        self.assertEqual(len(series), 1)

    def test_location_count_mismatch_is_rejected(self):
        with self.assertRaises(WeatherError):
            parse_forecast_payload([forecast_location()], 2)

    def test_malformed_payload_is_rejected(self):
        with self.assertRaises(WeatherError):
            parse_forecast_payload([{"hourly": {"time": ["2026-03-10T00:00"]}}], 1)


class HourlySeriesLookupTests(SimpleTestCase):
    series = HourlySeries(
        start=datetime(2026, 3, 10, tzinfo=UTC),
        wind_mph=(1.0, 2.0, 3.0),
        rain_in_hr=(0.0, 0.0, 0.0),
        snow_in_hr=(0.0, 0.0, 0.0),
        temperature_f=(40.0, 40.0, 40.0),
    )

    @staticmethod
    def on_march_10(hour, minute):
        return datetime(2026, 3, 10, hour, minute, tzinfo=UTC)

    def test_eta_reads_the_hour_that_contains_it(self):
        self.assertEqual(self.series.index_for(self.on_march_10(0, 59)), 0)
        self.assertEqual(self.series.index_for(self.on_march_10(1, 0)), 1)
        self.assertEqual(self.series.at(self.on_march_10(1, 30)).wind_mph, 2.0)

    def test_lookups_outside_the_window_are_clamped_and_flagged(self):
        self.assertEqual(self.series.index_for(datetime(2026, 3, 9, 23, 0, tzinfo=UTC)), 0)
        self.assertEqual(self.series.index_for(datetime(2026, 3, 11, 0, 0, tzinfo=UTC)), 2)
        self.assertTrue(self.series.covers(self.on_march_10(2, 59)))
        self.assertFalse(self.series.covers(self.on_march_10(3, 0)))


def weather_client(calls, status=200, error_body=None):
    def handler(request):
        params = parse_qs(request.url.query.decode())
        calls.append(params)
        if status >= 400:
            return httpx.Response(status, json=error_body)
        latitudes = params["latitude"][0].split(",")
        start = date.fromisoformat(params["start_date"][0])
        origin = datetime.combine(start, time.min)
        location = {
            "hourly_units": {"snowfall": "cm"},
            "hourly": {
                "time": [(origin + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(120)],
                "temperature_2m": [40.0] * 120,
                "wind_speed_10m": [10.0] * 120,
                "rain": [0.05] * 120,
                "showers": [0.05] * 120,
                "snowfall": [5.08] * 120,
            },
        }
        payload = [location for _ in latitudes] if len(latitudes) > 1 else location
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


class OpenMeteoClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_misses_are_batched_in_groups_of_45_with_documented_parameters(self):
        calls = []
        client = OpenMeteoClient(weather_client(calls))
        keys = [(3000 + i, -9000) for i in range(100)]
        result = client.fetch(keys, date(2026, 3, 10))

        self.assertEqual(result.http_requests, 3)
        self.assertEqual(result.cache_hits, 0)
        self.assertEqual(sorted(len(c["latitude"][0].split(",")) for c in calls), [10, 45, 45])
        for params in calls:
            self.assertEqual(params["hourly"], ["temperature_2m,wind_speed_10m,rain,showers,snowfall"])
            self.assertEqual(params["wind_speed_unit"], ["mph"])
            self.assertEqual(params["precipitation_unit"], ["inch"])
            self.assertEqual(params["temperature_unit"], ["fahrenheit"])
            self.assertEqual(params["start_date"], ["2026-03-10"])
        series = result.series[(3000, -9000)]
        self.assertEqual(series.wind_mph[0], 10.0)
        self.assertEqual(series.rain_in_hr[0], 0.1)
        self.assertEqual(series.snow_in_hr[0], 2.0)

    def test_second_fetch_is_served_entirely_from_cache(self):
        calls = []
        client = OpenMeteoClient(weather_client(calls))
        keys = [(3000 + i, -9000) for i in range(50)]
        client.fetch(keys, date(2026, 3, 10))
        issued = len(calls)

        again = client.fetch(keys, date(2026, 3, 10))
        self.assertEqual(again.http_requests, 0)
        self.assertEqual(again.cache_hits, 50)
        self.assertEqual(len(calls), issued)

    def test_cache_is_scoped_to_the_forecast_window(self):
        calls = []
        client = OpenMeteoClient(weather_client(calls))
        client.fetch([(3000, -9000)], date(2026, 3, 10))
        later = client.fetch([(3000, -9000)], date(2026, 3, 11))
        self.assertEqual(later.http_requests, 1)

    def test_duplicate_keys_are_requested_once(self):
        calls = []
        client = OpenMeteoClient(weather_client(calls))
        result = client.fetch([(3000, -9000), (3000, -9000)], date(2026, 3, 10))
        self.assertEqual(calls[0]["latitude"], ["30.00"])
        self.assertEqual(len(result.series), 1)

    def test_upstream_rejection_surfaces_the_reason(self):
        calls = []
        error_body = {"error": True, "reason": "Date out of range"}
        client = OpenMeteoClient(weather_client(calls, status=400, error_body=error_body))
        with self.assertRaisesMessage(WeatherError, "Date out of range"):
            client.fetch([(3000, -9000)], date(2026, 3, 10))


OSRM_PAYLOAD = {
    "code": "Ok",
    "routes": [
        {
            "duration": 3600.0,
            "distance": 160934.4,
            "geometry": {"type": "LineString", "coordinates": [[-100.0, 35.0], [-99.0, 35.1]]},
            "legs": [{"summary": "I-40, I-27"}, {"summary": "I-27, US-87"}],
        }
    ],
}


def osrm_client(seen):
    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=OSRM_PAYLOAD)

    return OsrmClient(httpx.Client(transport=httpx.MockTransport(handler)))


class OsrmClientTests(SimpleTestCase):
    def test_request_shape_and_parsing(self):
        seen = []
        routes = osrm_client(seen).routes([(35.0, -100.0), (36.0, -90.0)], alternatives=3)

        url = seen[0]
        self.assertEqual(url.path, "/route/v1/driving/-100.000000,35.000000;-90.000000,36.000000")
        query = parse_qs(url.query.decode())
        self.assertEqual(query["alternatives"], ["3"])
        self.assertEqual(query["overview"], ["full"])
        self.assertEqual(query["geometries"], ["geojson"])
        self.assertEqual(query["steps"], ["true"])
        self.assertEqual(routes[0].coordinates, [(35.0, -100.0), (35.1, -99.0)])
        self.assertEqual(routes[0].summary, "I-40, I-27, US-87")
        self.assertEqual(routes[0].duration_seconds, 3600.0)

    def test_route_name_splits_semicolon_separated_leg_summaries(self):
        payload = {
            "code": "Ok",
            "routes": [{**OSRM_PAYLOAD["routes"][0], "legs": [{"summary": "US 69; I 49"}, {"summary": "US 71, I 49"}]}],
        }
        self.assertEqual(parse_osrm_routes(payload)[0].summary, "US 69, I 49, US 71")

    def test_via_requests_disable_alternatives(self):
        seen = []
        osrm_client(seen).routes([(35.0, -100.0), (36.0, -95.0), (35.0, -90.0)])
        self.assertEqual(parse_qs(seen[0].query.decode())["alternatives"], ["false"])

    def test_no_route_and_error_codes(self):
        with self.assertRaises(NoRouteError):
            parse_osrm_routes({"code": "NoRoute"})
        with self.assertRaisesMessage(RoutingError, "bad coordinates"):
            parse_osrm_routes({"code": "InvalidQuery", "message": "bad coordinates"})
        with self.assertRaises(RoutingError):
            parse_osrm_routes({"code": "Ok", "routes": [{"duration": 1}]})


def geocoding_client(handler):
    return GeocodingClient(httpx.Client(transport=httpx.MockTransport(handler)))


class GeocodingClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_coordinate_pairs_skip_the_network(self):
        def handler(request):
            raise AssertionError("no request expected")

        place = geocoding_client(handler).geocode("35.5, -97.25")
        self.assertEqual((place.lat, place.lon), (35.5, -97.25))

    def test_nominatim_result_is_used_and_cached(self):
        hits = []

        def handler(request):
            hits.append(request.url.host)
            body = [{"lat": "32.7767", "lon": "-96.7970", "display_name": "Dallas, Texas, United States"}]
            return httpx.Response(200, json=body)

        client = geocoding_client(handler)
        first = client.geocode("Dallas, TX")
        second = client.geocode("dallas,  tx")
        self.assertEqual((first.lat, first.lon), (32.7767, -96.797))
        self.assertEqual(first.label, "Dallas, Texas, United States")
        self.assertEqual(second, first)
        self.assertEqual(len(hits), 1)

    def test_falls_back_to_open_meteo_geocoding(self):
        def handler(request):
            if request.url.host == "nominatim.openstreetmap.org":
                return httpx.Response(200, json=[])
            result = {"name": "Tulsa", "admin1": "Oklahoma", "country": "United States", "latitude": 36.15, "longitude": -95.99}
            return httpx.Response(200, json={"results": [result]})

        place = geocoding_client(handler).geocode("Tulsa, OK")
        self.assertEqual((place.lat, place.lon), (36.15, -95.99))
        self.assertEqual(place.label, "Tulsa, Oklahoma, United States")

    def test_unknown_place_raises(self):
        def handler(request):
            if request.url.host == "nominatim.openstreetmap.org":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json={})

        with self.assertRaises(GeocodingError):
            geocoding_client(handler).geocode("Nowhereville")
