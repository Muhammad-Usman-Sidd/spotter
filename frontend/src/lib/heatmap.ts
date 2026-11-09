import type { HeatmapPoint, RiskScore } from '../types/routing';
import { RISK_BY_SCORE, RISK_COLORS, hexToRgb } from './risk';

export type Rgba = readonly [number, number, number, number];

const LEVEL_ALPHA: readonly number[] = [0.1, 0.3, 0.42, 0.52, 0.62];

const ANCHORS: readonly Rgba[] = ([1, 2, 3, 4, 5] as const).map((score: RiskScore, index) => {
  const [red, green, blue] = hexToRgb(RISK_COLORS[RISK_BY_SCORE[score]]);
  return [red, green, blue, LEVEL_ALPHA[index]] as const;
});

/** Linear interpolation of an hourly series at a fractional hour offset, clamped to the series. */
export function sampleHourly(series: readonly number[], hour: number): number {
  const last = series.length - 1;
  if (last < 0) return 1;
  const clamped = Math.min(Math.max(hour, 0), last);
  const lower = Math.floor(clamped);
  const upper = Math.min(lower + 1, last);
  return series[lower] + (series[upper] - series[lower]) * (clamped - lower);
}

/** Maps a continuous risk value in [1, 5] onto the piecewise-linear heat palette. */
export function heatColor(value: number): Rgba {
  const clamped = Math.min(Math.max(value, 1), 5);
  const lowerIndex = Math.min(Math.floor(clamped) - 1, ANCHORS.length - 2);
  const blend = clamped - (lowerIndex + 1);
  const from = ANCHORS[lowerIndex];
  const to = ANCHORS[lowerIndex + 1];
  return [
    from[0] + (to[0] - from[0]) * blend,
    from[1] + (to[1] - from[1]) * blend,
    from[2] + (to[2] - from[2]) * blend,
    from[3] + (to[3] - from[3]) * blend,
  ];
}

export interface CorridorStats {
  peakWind: number;
  peakRain: number;
  peakSnow: number;
  elevated: number;
  total: number;
}

/** Corridor-wide readout at a given forecast offset; "elevated" counts points rounding to High or worse. */
export function corridorStats(points: readonly HeatmapPoint[], hour: number): CorridorStats {
  let peakWind = 0;
  let peakRain = 0;
  let peakSnow = 0;
  let elevated = 0;
  for (const point of points) {
    peakWind = Math.max(peakWind, sampleHourly(point.wind, hour));
    peakRain = Math.max(peakRain, sampleHourly(point.rain, hour));
    peakSnow = Math.max(peakSnow, sampleHourly(point.snow, hour));
    if (Math.round(sampleHourly(point.risk, hour)) >= 3) elevated += 1;
  }
  return { peakWind, peakRain, peakSnow, elevated, total: points.length };
}
