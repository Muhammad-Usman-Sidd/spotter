import type { RiskKey, RiskScore, RiskSummary, RouteAlert } from '../types/routing';

export const RISK_ORDER: readonly RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel'];

export const RISK_COLORS: Record<RiskKey, string> = {
  low: '#22c55e',
  moderate: '#eab308',
  high: '#f97316',
  severe: '#ef4444',
  no_travel: '#a855f7',
};

export const RISK_LABELS: Record<RiskKey, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No Travel',
};

export const RISK_BY_SCORE: Record<RiskScore, RiskKey> = {
  1: 'low',
  2: 'moderate',
  3: 'high',
  4: 'severe',
  5: 'no_travel',
};

export const RISK_MILES_FIELD: Record<RiskKey, keyof RiskSummary> = {
  low: 'low_miles',
  moderate: 'moderate_miles',
  high: 'high_miles',
  severe: 'severe_miles',
  no_travel: 'no_travel_miles',
};

export function milesAtRisk(summary: RiskSummary, key: RiskKey): number {
  return summary[RISK_MILES_FIELD[key]];
}

export function countLoadEscalated(alerts: readonly RouteAlert[]): number {
  let count = 0;
  for (const alert of alerts) {
    if (alert.load_escalated) count += 1;
  }
  return count;
}

export function pluralize(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural;
}

export function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}
