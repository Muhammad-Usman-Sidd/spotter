import { useMemo } from 'react';
import { formatClock, formatMiles } from '../lib/format';
import { countLoadEscalated, pluralize } from '../lib/risk';
import type { RouteOption } from '../types/routing';
import { RiskBadge } from './RiskBadge';

interface DispatcherNotesProps {
  route: RouteOption;
  loadWeightLbs: number;
}

/**
 * Lists every Severe or No Travel checkpoint on the selected route with the backend's reason,
 * including when the load weight is what pushed it there. Nothing flagged is summarised away.
 */
export function DispatcherNotes({ route, loadWeightLbs }: DispatcherNotesProps) {
  const loadEscalatedCount = useMemo(() => countLoadEscalated(route.alerts), [route.alerts]);
  const load = loadWeightLbs.toLocaleString('en-US');
  const alertCount = route.alerts.length;

  return (
    <section className="border-b border-slate-800 p-4" aria-labelledby="dispatcher-notes-heading">
      <h2 id="dispatcher-notes-heading" className="section-heading mb-2">
        Dispatcher notes
      </h2>

      {alertCount === 0 ? (
        <p className="text-xs text-slate-400">
          No Severe or No Travel checkpoints on this route for a {load} lb load.
        </p>
      ) : (
        <>
          <p className="mb-2 text-xs text-slate-300">
            {alertCount} {pluralize(alertCount, 'checkpoint', 'checkpoints')} at Severe or No Travel.
            {loadEscalatedCount > 0 && (
              <span className="text-amber-300">
                {' '}
                {loadEscalatedCount} {pluralize(loadEscalatedCount, 'is', 'are')} raised by the {load} lb load.
              </span>
            )}
          </p>
          <ul className="max-h-64 space-y-2 overflow-auto pr-1">
            {route.alerts.map((alert) => (
              <li key={alert.mile} className="rounded border border-slate-800 bg-slate-950/60 px-2.5 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums">
                  <RiskBadge risk={alert.risk_level} />
                  <span className="text-slate-200">Mile {formatMiles(alert.mile)}</span>
                  <span className="text-slate-400">ETA {formatClock(alert.eta)}</span>
                  {alert.load_escalated && (
                    <span className="rounded-sm border border-amber-700 px-1 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                      Load rule
                    </span>
                  )}
                </div>
                <p className="mt-1 leading-snug text-slate-400">{alert.message}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
