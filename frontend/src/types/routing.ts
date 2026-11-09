export type RiskKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel';
export type RiskScore = 1 | 2 | 3 | 4 | 5;
export type IntervalMiles = 10 | 25 | 50;
export type RouteSource = 'osrm' | 'lateral-north' | 'lateral-south';
export type LatLonTuple = [number, number];

export interface TripRequest {
  origin: string;
  destination: string;
  departure_time: string;
  load_weight_lbs: number;
  interval_miles: IntervalMiles;
  demo_storm: boolean;
}

export type TripFormValues = Omit<TripRequest, 'demo_storm'>;

export interface DispatchPreset {
  id: string;
  highway: string;
  origin: string;
  destination: string;
  loadWeightLbs: number;
  loadNote: string;
}

export interface ResolvedPlace {
  query: string;
  label: string;
  lat: number;
  lon: number;
}

export interface Checkpoint {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  wind_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  temperature_f: number | null;
  risk_level: RiskKey;
  risk_score: RiskScore;
  load_escalated: boolean;
  load_rule: string | null;
}

/** A Severe or No Travel checkpoint with the backend's plain-English cause. */
export interface RouteAlert {
  mile: number;
  eta: string;
  risk_level: RiskKey;
  load_escalated: boolean;
  message: string;
}

export interface RiskSummary {
  no_travel_miles: number;
  severe_miles: number;
  high_miles: number;
  moderate_miles: number;
  low_miles: number;
  average_risk_score: number;
}

export interface RouteOption {
  id: string;
  name: string;
  source: RouteSource;
  rank: number;
  recommended: boolean;
  distance_miles: number;
  duration_minutes: number;
  base_duration_minutes: number;
  summary: RiskSummary;
  recommendation_reason: string;
  geometry: LatLonTuple[];
  checkpoints: Checkpoint[];
  alerts: RouteAlert[];
}

export interface HeatmapPoint {
  lat: number;
  lon: number;
  risk: number[];
  wind: number[];
  rain: number[];
  snow: number[];
}

export interface HeatmapData {
  start: string;
  max_offset_hours: number;
  radius_miles: number;
  points: HeatmapPoint[];
}

export interface DemoStormInfo {
  active: boolean;
  route_id: string;
  route_name: string;
  center_lat: number;
  center_lon: number;
  center_mile: number;
  radius_miles: number;
  peak_time: string;
  peak_offset_hours: number;
  peak_wind_mph: number;
  peak_snow_in_hr: number;
  description: string;
}

export interface PlanMeta {
  elapsed_ms: number;
  weather_points: number;
  weather_requests: number;
  cache_hits: number;
  heavy_truck_factor: number;
  warnings: string[];
  demo_storm: DemoStormInfo | null;
}

export interface TripPlan {
  origin: ResolvedPlace;
  destination: ResolvedPlace;
  departure_time: string;
  load_weight_lbs: number;
  interval_miles: IntervalMiles;
  routes: RouteOption[];
  heatmap: HeatmapData;
  meta: PlanMeta;
}

export interface CheckpointFocus {
  index: number;
}
