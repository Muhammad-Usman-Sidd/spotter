import { formatDateTime } from '../lib/format';
import type { DemoStormInfo } from '../types/routing';

interface DemoStormNoticeProps {
  storm: DemoStormInfo;
  onInspect: () => void;
}

export function DemoStormNotice({ storm, onInspect }: DemoStormNoticeProps) {
  return (
    <aside className="border-b border-amber-900 bg-amber-950/40 px-4 py-3 text-xs leading-relaxed text-amber-100">
      <div className="mb-1 flex items-center justify-between gap-3">
        <p className="font-semibold uppercase tracking-wider text-amber-300">Synthetic weather active</p>
        <button
          type="button"
          onClick={onInspect}
          className="shrink-0 rounded border border-amber-700 px-2 py-0.5 text-[11px] font-medium text-amber-200 transition-colors hover:bg-amber-900/60"
        >
          Inspect stormed route
        </button>
      </div>
      <p>
        A demo winter front is centered at mile {storm.center_mile.toFixed(0)} of {storm.route_name}, peaking{' '}
        {formatDateTime(new Date(storm.peak_time))} with {storm.peak_wind_mph.toFixed(0)} mph wind and{' '}
        {storm.peak_snow_in_hr.toFixed(1)} in/hr snow. Weather away from the front is the live forecast.
      </p>
      <p className="mt-1 text-amber-200/80">
        Compare a 28,000 lb load with a 42,000 lb or 45,000 lb load: wind of 45 to 54 mph is Severe at 30,000 lb
        or less and No Travel over it, and wind of 35 to 44 mph is High at 40,000 lb or less and Severe over it.
      </p>
    </aside>
  );
}
