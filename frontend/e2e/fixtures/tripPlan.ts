import type {
  Checkpoint,
  HeatmapData,
  HeatmapPoint,
  LatLonTuple,
  ResolvedPlace,
  RiskKey,
  RiskScore,
  RiskSummary,
  RouteAlert,
  RouteOption,
  RouteSource,
  TripPlan,
  TripRequest,
} from '../../src/types/routing';

/**
 * Scripted POST /api/plan/ responses for the E2E tests.
 *
 * Typed against src/types/routing.ts, so if the API contract changes the fixture stops compiling.
 * Two scenarios share the same weather and differ only by load weight:
 *   - 40,000 lb or less: the 38 mph wind on I-35 is High, and I-35 is recommended.
 *   - over 40,000 lb: the same wind is Severe (load rule), so I-35 drops to last place.
 */

export const SEVERE_LOAD_RULE = '35-44 mph wind with a load over 40,000 lb is Severe';
const SEVERE_LOAD_OVER_LBS = 40_000;
const HEATMAP_HOURS = 48;
const HEATMAP_POINT_COUNT = 6;

const ORIGIN: ResolvedPlace = {
  query: 'Dallas, TX',
  label: 'Dallas, Dallas County, Texas, United States',
  lat: 32.7767,
  lon: -96.797,
};

const DESTINATION: ResolvedPlace = {
  query: 'Chicago, IL',
  label: 'Chicago, Cook County, Illinois, United States',
  lat: 41.8781,
  lon: -87.6298,
};

const RISK_SCORES: Record<RiskKey, RiskScore> = { low: 1, moderate: 2, high: 3, severe: 4, no_travel: 5 };

interface CheckpointSpec {
  mile: number;
  windMph: number;
  rainInHr: number;
  snowInHr: number;
  risk: RiskKey;
  loadRule: string | null;
}

interface RouteSpec {
  id: string;
  name: string;
  source: RouteSource;
  distanceMiles: number;
  durationMinutes: number;
  bendDegrees: number;
  checkpoints: CheckpointSpec[];
  summary: RiskSummary;
}

function calm(mile: number, windMph: number): CheckpointSpec {
  return { mile, windMph, rainInHr: 0, snowInHr: 0, risk: 'low', loadRule: null };
}

/** A point on a gentle arc between origin and destination; bendDegrees pushes the arc sideways. */
function pointAlong(fraction: number, bendDegrees: number): LatLonTuple {
  const bend = Math.sin(Math.PI * fraction) * bendDegrees;
  const lat = ORIGIN.lat + (DESTINATION.lat - ORIGIN.lat) * fraction + bend;
  const lon = ORIGIN.lon + (DESTINATION.lon - ORIGIN.lon) * fraction - bend;
  return [Number(lat.toFixed(5)), Number(lon.toFixed(5))];
}

function routeSpecs(heavyLoad: boolean): RouteSpec[] {
  const i35WindRisk: RiskKey = heavyLoad ? 'severe' : 'high';
  return [
    {
      id: 'route-1',
      name: 'I-35, I-44',
      source: 'osrm',
      distanceMiles: 925,
      durationMinutes: 870,
      bendDegrees: 0,
      checkpoints: [
        calm(0, 12),
        calm(250, 18),
        {
          mile: 500,
          windMph: 38,
          rainInHr: 0,
          snowInHr: 0,
          risk: i35WindRisk,
          loadRule: heavyLoad ? SEVERE_LOAD_RULE : null,
        },
        calm(750, 22),
        calm(925, 10),
      ],
      summary: {
        no_travel_miles: 0,
        severe_miles: heavyLoad ? 250 : 0,
        high_miles: heavyLoad ? 0 : 250,
        moderate_miles: 0,
        low_miles: 675,
        average_risk_score: heavyLoad ? 1.81 : 1.54,
      },
    },
    {
      id: 'route-2',
      name: 'US-75, US-69',
      source: 'lateral-north',
      distanceMiles: 960,
      durationMinutes: 912,
      bendDegrees: 1.2,
      checkpoints: [
        calm(0, 10),
        calm(240, 15),
        { mile: 480, windMph: 20, rainInHr: 0.3, snowInHr: 0, risk: 'high', loadRule: null },
        { mile: 720, windMph: 15, rainInHr: 0.3, snowInHr: 0, risk: 'high', loadRule: null },
        calm(960, 10),
      ],
      summary: {
        no_travel_miles: 0,
        severe_miles: 0,
        high_miles: 480,
        moderate_miles: 0,
        low_miles: 480,
        average_risk_score: 2.0,
      },
    },
    {
      id: 'route-3',
      name: 'I-30, I-55',
      source: 'lateral-south',
      distanceMiles: 1010,
      durationMinutes: 960,
      bendDegrees: -1.2,
      checkpoints: [
        calm(0, 8),
        { mile: 250, windMph: 12, rainInHr: 0, snowInHr: 1.2, risk: 'high', loadRule: null },
        { mile: 500, windMph: 14, rainInHr: 0, snowInHr: 1.2, risk: 'high', loadRule: null },
        { mile: 750, windMph: 10, rainInHr: 0, snowInHr: 0.6, risk: 'moderate', loadRule: null },
        calm(1010, 9),
      ],
      summary: {
        no_travel_miles: 0,
        severe_miles: 0,
        high_miles: 500,
        moderate_miles: 255,
        low_miles: 255,
        average_risk_score: 2.24,
      },
    },
  ];
}

function buildCheckpoint(spec: CheckpointSpec, route: RouteSpec, departureMs: number): Checkpoint {
  const fraction = spec.mile / route.distanceMiles;
  const [lat, lon] = pointAlong(fraction, route.bendDegrees);
  const etaMs = departureMs + fraction * route.durationMinutes * 60_000;
  return {
    mile: spec.mile,
    lat,
    lon,
    eta: new Date(etaMs).toISOString(),
    wind_mph: spec.windMph,
    rain_in_hr: spec.rainInHr,
    snow_in_hr: spec.snowInHr,
    temperature_f: 41,
    risk_level: spec.risk,
    risk_score: RISK_SCORES[spec.risk],
    load_escalated: spec.loadRule !== null,
    load_rule: spec.loadRule,
  };
}

function buildAlerts(checkpoints: Checkpoint[], loadWeightLbs: number): RouteAlert[] {
  const alerts: RouteAlert[] = [];
  for (const checkpoint of checkpoints) {
    if (checkpoint.risk_score < RISK_SCORES.severe) continue;
    const load = loadWeightLbs.toLocaleString('en-US');
    alerts.push({
      mile: checkpoint.mile,
      eta: checkpoint.eta,
      risk_level: checkpoint.risk_level,
      load_escalated: checkpoint.load_escalated,
      message:
        `Wind ${checkpoint.wind_mph.toFixed(1)} mph with a ${load} lb load (${SEVERE_LOAD_RULE}). ` +
        'At or under 40,000 lb this wind is High.',
    });
  }
  return alerts;
}

function buildGeometry(route: RouteSpec): LatLonTuple[] {
  const geometry: LatLonTuple[] = [];
  for (let step = 0; step <= 20; step += 1) {
    geometry.push(pointAlong(step / 20, route.bendDegrees));
  }
  return geometry;
}

function buildRoute(route: RouteSpec, rank: number, reason: string, request: TripRequest): RouteOption {
  const departureMs = Date.parse(request.departure_time);
  const checkpoints = route.checkpoints.map((spec) => buildCheckpoint(spec, route, departureMs));
  return {
    id: route.id,
    name: route.name,
    source: route.source,
    rank,
    recommended: rank === 1,
    distance_miles: route.distanceMiles,
    duration_minutes: route.durationMinutes,
    base_duration_minutes: Number((route.durationMinutes / 1.12).toFixed(1)),
    summary: route.summary,
    recommendation_reason: reason,
    geometry: buildGeometry(route),
    checkpoints,
    alerts: buildAlerts(checkpoints, request.load_weight_lbs),
  };
}

function windRisk(windMph: number): number {
  if (windMph >= 55) return 5;
  if (windMph >= 45) return 4;
  if (windMph >= 35) return 3;
  if (windMph >= 25) return 2;
  return 1;
}

/** Peak corridor wind is 20 mph at departure and climbs 1 mph per hour, so the slider readout moves. */
function buildHeatmap(request: TripRequest): HeatmapData {
  const points: HeatmapPoint[] = [];
  for (let index = 0; index < HEATMAP_POINT_COUNT; index += 1) {
    const [lat, lon] = pointAlong((index + 0.5) / HEATMAP_POINT_COUNT, 0);
    const wind: number[] = [];
    const risk: number[] = [];
    for (let hour = 0; hour <= HEATMAP_HOURS; hour += 1) {
      const windMph = 20 + hour - index * 2;
      wind.push(windMph);
      risk.push(windRisk(windMph));
    }
    const dry = new Array<number>(HEATMAP_HOURS + 1).fill(0);
    points.push({ lat, lon, risk, wind, rain: dry, snow: [...dry] });
  }
  return { start: request.departure_time, max_offset_hours: HEATMAP_HOURS, radius_miles: 40, points };
}

export function buildTripPlan(request: TripRequest): TripPlan {
  const heavyLoad = request.load_weight_lbs > SEVERE_LOAD_OVER_LBS;
  const [i35, us75, i30] = routeSpecs(heavyLoad);

  const ranked: RouteOption[] = heavyLoad
    ? [
        buildRoute(us75, 1, 'Recommended: Zero Severe or No-Travel miles, lowest avg risk (2.00), 15.2h transit time', request),
        buildRoute(i30, 2, 'Avoided: 500.0 High miles vs 480.0 mi on recommended route', request),
        buildRoute(i35, 3, 'Avoided: 250.0 Severe miles vs 0.0 mi on recommended route', request),
      ]
    : [
        buildRoute(i35, 1, 'Recommended: Zero Severe or No-Travel miles, lowest avg risk (1.54), 14.5h transit time', request),
        buildRoute(us75, 2, 'Avoided: 480.0 High miles vs 250.0 mi on recommended route', request),
        buildRoute(i30, 3, 'Avoided: 500.0 High miles vs 250.0 mi on recommended route', request),
      ];

  return {
    origin: { ...ORIGIN, query: request.origin },
    destination: { ...DESTINATION, query: request.destination },
    departure_time: request.departure_time,
    load_weight_lbs: request.load_weight_lbs,
    interval_miles: request.interval_miles,
    routes: ranked,
    heatmap: buildHeatmap(request),
    meta: {
      elapsed_ms: 840,
      weather_points: 120,
      weather_requests: 3,
      cache_hits: 0,
      heavy_truck_factor: 1.12,
      warnings: [],
      demo_storm: null,
    },
  };
}
