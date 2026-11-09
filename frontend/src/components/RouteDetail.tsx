import { formatClock, formatMiles } from '../lib/format';
import { RISK_COLORS, RISK_LABELS, RISK_ORDER, milesAtRisk } from '../lib/risk';
import type { CheckpointFocus, RouteOption } from '../types/routing';
import { RiskBadge } from './RiskBadge';

interface RouteDetailProps {
  route: RouteOption;
  focus: CheckpointFocus | null;
  onFocusCheckpoint: (index: number) => void;
}

const TIME_ZONE_LABEL = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
  .formatToParts(new Date())
  .find((part) => part.type === 'timeZoneName')?.value;

const SEVERITY_DESCENDING = [...RISK_ORDER].reverse();

export function RouteDetail({ route, focus, onFocusCheckpoint }: RouteDetailProps) {
  return (
    <section className="p-4" aria-labelledby="risk-exposure-heading">
      <h2 id="risk-exposure-heading" className="section-heading mb-2">
        Risk exposure: {route.name}
      </h2>
      <table className="mb-4 w-full text-xs tabular-nums">
        <tbody>
          {SEVERITY_DESCENDING.map((key) => {
            const miles = milesAtRisk(route.summary, key);
            const share = route.distance_miles > 0 ? (miles / route.distance_miles) * 100 : 0;
            return (
              <tr key={key} className="border-b border-slate-800 last:border-0">
                <td className="py-1">
                  <span className="inline-flex items-center gap-1.5 text-slate-200">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: RISK_COLORS[key] }} />
                    {RISK_LABELS[key]}
                  </span>
                </td>
                <td className="py-1 text-right text-slate-100">{formatMiles(miles)} mi</td>
                <td className="w-14 py-1 text-right text-slate-500">{share.toFixed(1)}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="section-heading">Checkpoints</h2>
        {TIME_ZONE_LABEL && <span className="text-[11px] text-slate-500">ETA in {TIME_ZONE_LABEL}</span>}
      </div>
      <div className="max-h-80 overflow-auto rounded border border-slate-800">
        <table className="w-full text-xs tabular-nums" aria-label="Checkpoints">
          <thead className="sticky top-0 bg-slate-900 text-left text-[11px] uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-2 py-1.5 font-medium">Mile</th>
              <th className="px-2 py-1.5 font-medium">ETA</th>
              <th className="px-2 py-1.5 text-right font-medium">Wind</th>
              <th className="px-2 py-1.5 text-right font-medium">Rain</th>
              <th className="px-2 py-1.5 text-right font-medium">Snow</th>
              <th className="px-2 py-1.5 font-medium">Risk</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((checkpoint, index) => {
              const active = focus?.index === index;
              return (
                <tr
                  key={checkpoint.mile}
                  onClick={() => onFocusCheckpoint(index)}
                  className={`cursor-pointer border-t border-slate-800 transition-colors ${
                    active ? 'bg-slate-800' : 'hover:bg-slate-800/60'
                  }`}
                >
                  <td className="px-2 py-1 text-slate-100">{formatMiles(checkpoint.mile)}</td>
                  <td className="whitespace-nowrap px-2 py-1 text-slate-300">{formatClock(checkpoint.eta)}</td>
                  <td className="px-2 py-1 text-right text-slate-100">{checkpoint.wind_mph.toFixed(1)}</td>
                  <td className="px-2 py-1 text-right text-slate-100">{checkpoint.rain_in_hr.toFixed(2)}</td>
                  <td className="px-2 py-1 text-right text-slate-100">{checkpoint.snow_in_hr.toFixed(2)}</td>
                  <td className="px-2 py-1">
                    <RiskBadge risk={checkpoint.risk_level} />
                    {checkpoint.load_escalated && (
                      <span
                        className="ml-1.5 text-[10px] uppercase tracking-wide text-amber-400"
                        title={checkpoint.load_rule ?? 'Load weight raised the wind risk'}
                      >
                        load
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Wind in mph, rain and snow in in/hr, read from the forecast hour the truck reaches each checkpoint.
      </p>
    </section>
  );
}
