import { useEffect, useMemo, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { formatDateTime, formatOffset } from '../lib/format';
import { corridorStats } from '../lib/heatmap';
import { RISK_COLORS, RISK_LABELS, RISK_ORDER } from '../lib/risk';
import type { HeatmapData } from '../types/routing';

const PLAYBACK_HOURS_PER_SECOND = 3;
const SLIDER_STEP_HOURS = 0.25;
const MS_PER_HOUR = 3_600_000;

interface ForecastSliderProps {
  heatmap: HeatmapData;
  hour: number;
  onHourChange: Dispatch<SetStateAction<number>>;
}

/**
 * 0-48 h forecast scrubber. Every value it needs is already in the plan payload, so moving the
 * slider (or pressing Play) only changes local state; it never calls the API.
 */
export function ForecastSlider({ heatmap, hour, onHourChange }: ForecastSliderProps) {
  const [playing, setPlaying] = useState(false);
  const maxHour = heatmap.max_offset_hours;

  const clockTime = useMemo(
    () => formatDateTime(new Date(Date.parse(heatmap.start) + hour * MS_PER_HOUR)),
    [heatmap.start, hour],
  );
  const stats = useMemo(() => corridorStats(heatmap.points, hour), [heatmap.points, hour]);

  useEffect(() => {
    if (!playing) return undefined;
    let frame = 0;
    let previousTime = performance.now();
    const tick = (now: number) => {
      const elapsedSeconds = (now - previousTime) / 1000;
      previousTime = now;
      onHourChange((previousHour) => {
        const nextHour = previousHour + elapsedSeconds * PLAYBACK_HOURS_PER_SECOND;
        return nextHour > maxHour ? 0 : nextHour;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, maxHour, onHourChange]);

  return (
    <div
      className="absolute inset-x-3 bottom-3 z-[1000] rounded border border-slate-700 bg-slate-900/95 px-4 py-3 shadow-lg"
      role="group"
      aria-label="Forecast slider"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={() => setPlaying((value) => !value)}
          className="w-16 rounded border border-slate-600 bg-slate-800 py-1 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-700"
          aria-pressed={playing}
        >
          {playing ? 'Pause' : 'Play'}
        </button>

        <div className="min-w-[8rem] text-xs tabular-nums">
          <div className="font-semibold text-slate-100" data-testid="forecast-offset">
            {formatOffset(hour)}
          </div>
          <div className="text-slate-400">{clockTime}</div>
        </div>

        <div className="flex min-w-[10rem] flex-1 items-center gap-3">
          <span className="text-[11px] tabular-nums text-slate-500">0h</span>
          <input
            type="range"
            className="forecast-range flex-1"
            min={0}
            max={maxHour}
            step={SLIDER_STEP_HOURS}
            value={hour}
            onChange={(event) => onHourChange(Number(event.target.value))}
            aria-label="Forecast hour offset from departure"
          />
          <span className="text-[11px] tabular-nums text-slate-500">{maxHour}h</span>
        </div>

        <dl className="flex gap-4 text-xs tabular-nums">
          <div>
            <dt className="text-slate-500">Peak wind</dt>
            <dd className="text-slate-100" data-testid="peak-wind">
              {stats.peakWind.toFixed(0)} mph
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Peak rain</dt>
            <dd className="text-slate-100">{stats.peakRain.toFixed(2)} in/hr</dd>
          </div>
          <div>
            <dt className="text-slate-500">Peak snow</dt>
            <dd className="text-slate-100">{stats.peakSnow.toFixed(2)} in/hr</dd>
          </div>
          <div>
            <dt className="text-slate-500">High or worse</dt>
            <dd className="text-slate-100" data-testid="elevated-points">
              {stats.elevated} / {stats.total}
            </dd>
          </div>
        </dl>
      </div>

      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800 pt-2 text-[11px] text-slate-400">
        {RISK_ORDER.map((key) => (
          <li key={key} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: RISK_COLORS[key] }} />
            {RISK_LABELS[key]}
          </li>
        ))}
      </ul>
    </div>
  );
}
