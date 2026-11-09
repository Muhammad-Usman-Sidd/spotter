import { formatDuration, formatMiles } from '../lib/format';
import { countLoadEscalated, pluralize } from '../lib/risk';
import type { RouteOption, RouteSource } from '../types/routing';
import { RiskBar } from './RiskBar';

const SOURCE_LABELS: Record<RouteSource, string> = {
  osrm: 'OSRM',
  'lateral-north': 'North corridor',
  'lateral-south': 'South corridor',
};

interface RouteListProps {
  routes: RouteOption[];
  selectedId: string;
  onSelect: (id: string) => void;
}

export function RouteList({ routes, selectedId, onSelect }: RouteListProps) {
  return (
    <section className="border-b border-slate-800 p-4" aria-labelledby="route-options-heading">
      <h2 id="route-options-heading" className="section-heading mb-2">
        Route options
      </h2>
      <ul className="space-y-2">
        {routes.map((route) => {
          const selected = route.id === selectedId;
          const alertCount = route.alerts.length;
          const loadEscalatedCount = countLoadEscalated(route.alerts);
          return (
            <li key={route.id}>
              <button
                type="button"
                onClick={() => onSelect(route.id)}
                aria-pressed={selected}
                className={`w-full rounded border p-3 text-left transition-colors ${
                  selected
                    ? 'border-sky-500 bg-slate-800'
                    : 'border-slate-800 bg-slate-900 hover:border-slate-600 hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm bg-slate-700 text-[11px] font-semibold tabular-nums text-slate-100">
                        {route.rank}
                      </span>
                      <span className="truncate text-sm font-semibold text-slate-100">{route.name}</span>
                    </div>
                    <div className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">
                      {SOURCE_LABELS[route.source]}
                    </div>
                  </div>
                  {route.recommended && (
                    <span className="shrink-0 rounded-sm border border-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                      Recommended
                    </span>
                  )}
                </div>

                <dl className="mt-2 grid grid-cols-3 gap-2 text-xs tabular-nums">
                  <div>
                    <dt className="text-slate-500">Distance</dt>
                    <dd className="text-slate-100">{formatMiles(route.distance_miles)} mi</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Transit</dt>
                    <dd className="text-slate-100">{formatDuration(route.duration_minutes)}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Avg risk</dt>
                    <dd className="text-slate-100">{route.summary.average_risk_score.toFixed(2)}</dd>
                  </div>
                </dl>

                <div className="mt-2">
                  <RiskBar summary={route.summary} totalMiles={route.distance_miles} />
                </div>
                <p className="mt-2 text-xs leading-snug text-slate-400">{route.recommendation_reason}</p>
                {alertCount > 0 && (
                  <p className="mt-1 text-[11px] leading-snug text-red-300">
                    {alertCount} Severe or No Travel {pluralize(alertCount, 'checkpoint', 'checkpoints')}
                    {loadEscalatedCount > 0 && `, ${loadEscalatedCount} raised by load weight`}
                  </p>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
