# Weather-Aware Truck Routing

A dispatch tool that compares three drivable routes for a truck and recommends the safest one. Weather is
read from the forecast for the hour the truck actually reaches each checkpoint, not the departure hour,
and wind risk is adjusted for load weight.

- Backend: Python 3.10+, Django 5, Django REST Framework, httpx
- Frontend: React 18, TypeScript (strict, no `any`), Vite, Tailwind CSS, Leaflet (react-leaflet)
- Tests: Django/pytest unit and API tests, Playwright end-to-end tests
- External services, no API keys: OSRM (routing), Open-Meteo (hourly forecast), Nominatim and Open-Meteo (geocoding)

## Architecture

The backend is layered the way I would structure an ASP.NET Core service: a thin controller, typed
request/response DTOs, an application service, pure domain logic, and infrastructure clients behind
interfaces.

```
backend/routing/
  views.py                 Controller. Validates the body, calls TripPlanner, maps errors to HTTP codes.
  serializers.py           Request validation (DRF). Produces a typed TripRequest.
  services/
    dtos.py                Request and response contracts. Field names = JSON keys the frontend reads.
    planner.py             Application service (TripPlanner). Orchestrates the steps below.
    route_discovery.py     Three distinct routes: OSRM alternatives, then lateral-waypoint fallback.
    risk_engine.py         Domain: risk thresholds, load-weight rules, dispatcher explanations.
    ranking.py             Domain: miles per risk level, recommendation order, reason per route.
    geometry.py            Domain: Haversine, checkpoint sampling, ETA, weather grid, waypoint math.
    contracts.py           Interfaces (Protocols) for geocoder, router and weather, plus value objects.
    providers.py           Infrastructure: Nominatim, OSRM and Open-Meteo clients, batching, caching.
    demo_storm.py          Synthetic storm overlay for demonstrating the rules on a calm day.
    errors.py              Typed service errors, each with an HTTP status and a stable code.
  tests/                   Unit, API and planner tests with in-memory fakes. No network.

frontend/
  src/types/routing.ts     The API contract in TypeScript.
  src/hooks/useTripPlan.ts Request state (loading, error, plan) with request cancellation.
  src/components/          Form, route list, dispatcher notes, route detail, map, heatmap layer, slider.
  src/lib/                 API client, risk palette, heatmap colour maths, formatting.
  e2e/                     Playwright tests against a scripted API response.
```

`TripPlanner` receives its three providers through its constructor (`Providers` in `contracts.py`).
Production wiring happens in `build_default_providers()`; the tests pass fakes with the same methods.

### Request flow for `POST /api/plan/`

1. Geocode origin and destination. Coordinate input such as `35.5,-97.2` skips the network.
2. Ask OSRM for alternatives. Keep a route only if it is distinct (less than 92 percent of it runs along a
   route already kept) and reasonable (no longer than 1.75x the shortest route).
3. If fewer than three remain, route through a waypoint pushed sideways off the straight line between
   origin and destination, alternating north and south and widening the push (15, 25, then 8 percent of
   the straight-line distance, clamped to 5-150 miles). If three distinct routes still cannot be found,
   the response says so in `meta.warnings` instead of padding the list with a duplicate.
4. Stretch every OSRM duration by 1.12. The public OSRM server only has a car profile.
5. Sample each route every 10, 25 or 50 miles and compute each checkpoint ETA as
   `departure + (mile / total_miles) * duration`.
6. Snap every checkpoint and heatmap point to a 0.01 degree grid, deduplicate, and fetch hourly forecasts
   for all of them in a few batched requests.
7. For each checkpoint, read the forecast hour that contains its ETA, score it, aggregate miles per risk
   level, rank the routes and explain the ranking.
8. Return routes, checkpoints, dispatcher alerts and a 0-48 hour heatmap series in one payload.

## Risk and load logic

A checkpoint's level is the worst of wind (after load rules), rain and snow.

| Level | Score | Wind (mph) | Rain (in/hr) | Snow (in/hr) |
| :--- | :--- | :--- | :--- | :--- |
| Low | 1 | < 25 | < 0.10 | < 0.5 |
| Moderate | 2 | 25 to < 35 | 0.10 to < 0.25 | 0.5 to < 1.0 |
| High | 3 | 35 to < 45 | 0.25 to < 0.50 | 1.0 to < 2.0 |
| Severe | 4 | 45 to < 55 | 0.50 to 1.00 | 2.0 to 3.0 |
| No Travel | 5 | >= 55 | > 1.00 | > 3.0 |

Boundary convention: every band starts at its lower number, the same way the wind bands read, so a reading
exactly on a boundary goes to the higher-risk band (0.25 in/hr rain is High). The only exception is the one
the assessment writes explicitly: No Travel is "> 1.00" rain and "> 3.0" snow, so exactly 1.00 and 3.0 stay
Severe. For a safety tool, rounding a tie toward the higher risk is the conservative choice.

Load rules, applied to the wind level only, with the load limits read strictly as "over":

| Wind | Load | Result |
| :--- | :--- | :--- |
| >= 55 mph | any | No Travel (already the base level, so not counted as a load escalation) |
| 45-54 mph | over 30,000 lb | No Travel (30,000 lb exactly stays Severe) |
| 35-44 mph | over 40,000 lb | Severe (40,000 lb exactly stays High) |

Each checkpoint reports `load_escalated` and the `load_rule` that fired. Every Severe or No Travel
checkpoint also appears in the route's `alerts` list with a plain-English cause, for example:
"Wind 51.6 mph with a 42,000 lb load (45-54 mph wind with a load over 30,000 lb is No Travel). At or under
30,000 lb this wind is Severe." The UI lists every alert under Dispatcher notes; none are summarised away.

### Recommendation order

Routes are compared field by field, left to right:

1. Fewest No Travel miles (a No Travel mile is worse than any number of Severe miles)
2. Fewest Severe miles
3. Fewest High miles
4. Lowest distance-weighted average risk score (1 to 5)
5. Shortest travel time

A checkpoint stands for the stretch between the midpoints to its neighbours, so the miles per level always
add up to the route length. Comparisons use the precision the UI shows (0.1 mile, 0.01 score, whole minutes),
so two routes that look identical on screen are never separated by floating-point noise. Full ties keep
route discovery order. Each route gets a reason naming the first criterion it won or lost on.

### Forecast hour selection

The ETA is floored to its UTC hour: a truck arriving at 14:40 reads the 14:00 forecast. Rain is
`rain + showers`. Snowfall is converted from cm to inches when Open-Meteo reports it in cm. ETAs beyond
the 5-day fetch window use the last available hour and add a warning.

## Map and 0-48 h heatmap performance

- One payload, no slider round trips: each corridor point ships with 49 hourly values (hour 0 to 48 after
  departure) of risk, wind, rain and snow. Moving the slider or pressing Play only changes React state.
- Canvas heatmap: `WeatherHeatmapLayer` draws one radial gradient per corridor point on a single canvas.
  Points are projected to screen pixels only when the map moves. A slider change updates a ref and
  schedules one `requestAnimationFrame` redraw; several changes in the same frame collapse into one draw.
  Values are interpolated between hours, so playback is smooth at a 15-minute slider step.
- Map layers: Leaflet's canvas renderer (`preferCanvas`) draws routes and checkpoint markers. The selected
  route gets full-size markers with popups; the other routes get small markers that select their route.
- Payload size: route geometries are simplified with Douglas-Peucker (about 40 m tolerance) and coordinates
  are rounded to 5 decimals.
- Batched forecasts: grid cells are deduplicated and sent to Open-Meteo as multi-coordinate requests of up
  to 45 locations, 4 in flight at once. Three 1,000 mile routes at 10 mile spacing cost a handful of HTTP
  calls instead of 300.
- Caching: each grid cell and forecast window is cached for 30 minutes, so re-running a corridor with a
  different load weight costs zero forecast requests. Geocoding results are cached for 24 hours.

The map shows all three routes, a pinned summary table (miles, transit, arrival, No Travel and Severe miles,
average risk), a hover summary on each route line, checkpoint markers coloured by risk with ETA popups, and
the heatmap with its slider.

## Demo Storm Injection

The header toggle overlays a synthetic winter front so the risk rules, load escalation and ranking can be
shown on any day, including when the real forecast is calm. It is off by default, labelled "Synthetic"
when on, and never written to the forecast cache.

The planner first scores the routes on the real forecast, then stalls the front over the middle of the route
that would have been recommended, centred on a checkpoint and peaking at the hour the truck gets there. Wind
peaks at 57 mph (No Travel for any load) and the first checkpoint either side lands at 45-54 mph, so a load
over 30,000 lb is No Travel there while a lighter load is Severe. Further out, 35-44 mph wind is Severe only
over 40,000 lb. Snow peaks at 2.6 in/hr (Severe). The front never weakens existing weather.

## API

`POST /api/plan/`

```json
{
  "origin": "Dallas, TX",
  "destination": "Chicago, IL",
  "departure_time": "2026-03-10T14:00:00Z",
  "load_weight_lbs": 42000,
  "interval_miles": 25,
  "demo_storm": false
}
```

`interval_miles` must be 10, 25 or 50. `load_weight_lbs` is 0 to 150,000. Departure may be up to 14 days
ahead and 7 days in the past. Validation failures return 400 with per-field messages, unknown places or no
drivable route return 422, and upstream failures return 502 with `detail` and `code`.

The response contains `routes` (sorted by rank, each with `summary`, `recommendation_reason`, `geometry`,
`checkpoints` and `alerts`), `heatmap` (49 hourly values per corridor point) and `meta` (batch counts,
cache hits, warnings, demo storm details).

## Running locally

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

Frontend (Node 18 or newer):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to `http://127.0.0.1:8000`. To call a backend elsewhere,
set `VITE_API_BASE_URL` and add the frontend origin to `CORS_ALLOWED_ORIGINS` on the backend.

Backend environment variables: `DJANGO_DEBUG` (default `1`), `DJANGO_SECRET_KEY` (required when
`DJANGO_DEBUG=0`), `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` (comma separated).

## Tests

Backend, 147 tests, no network:

```bash
cd backend
pytest              # or: python manage.py test
```

| File | Covers |
| :--- | :--- |
| `test_risk_engine.py` | Boundary value analysis for every threshold: 24.9/25.0, 34.9/35.0, 44.9/45.0, 54.9/55.0 mph; 29,999/30,000/30,001 lb at 45 mph; 39,999/40,000/40,001 lb at 35 mph; rain and snow band edges; dispatcher explanations |
| `test_ranking.py` | Miles per level, each tie-breaker in order, display-precision ties, reason strings |
| `test_geometry.py` | Haversine, 10/25/50 mile sampling, ETA, grid snapping, lateral waypoints, simplification, corridor overlap |
| `test_planner.py` | End-to-end planner with fakes: three-route fallback, arrival-hour weather, load escalation, alerts |
| `test_providers.py` | OSRM, Open-Meteo and geocoding clients against scripted HTTP responses |
| `test_demo_storm.py` | Storm model and its effect on ranking and load rules |
| `test_api.py` | Validation, error codes, and the JSON keys the frontend depends on |

Frontend type check and build:

```bash
cd frontend
npm run typecheck
npm run build
```

End-to-end, Playwright. The Django API is replaced by a scripted response (`e2e/fixtures/tripPlan.ts`,
typed against `src/types/routing.ts`), so no backend or network is needed. Playwright starts the Vite dev
server itself.

```bash
cd frontend
npx playwright install chromium   # first run only
npm run test:e2e
```

The E2E tests cover form submission and the exact request body, three ranked routes in the list and on
the map, a heavy load escalating a checkpoint and changing the recommendation, the dispatcher notes, the
0-48 h slider updating the readout with no further API calls, and backend errors shown as reported.

## Known limits

- The public OSRM server and Nominatim are rate limited and meant for light use. Point `OsrmClient.BASE_URL`
  and `GeocodingClient.NOMINATIM_URL` at your own instances for production. OSRM has no truck profile, so
  low bridges, weight limits and hazmat restrictions are not modelled; the 1.12 factor only adjusts time.
- ETAs assume a constant average speed and do not model hours-of-service breaks.
- The forecast cache is in-process (`LocMemCache`). With more than one worker it should move to Redis.
- A lateral waypoint can land on a poor road in sparse regions. Candidates that duplicate a kept corridor or
  exceed 1.75x the shortest distance are rejected and retried with a different push.
- The basemap is the public OpenStreetMap tile server, darkened with a CSS filter.
