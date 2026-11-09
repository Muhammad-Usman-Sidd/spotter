import { RISK_COLORS, RISK_LABELS, RISK_ORDER, milesAtRisk } from '../lib/risk';
import type { RiskSummary } from '../types/routing';

interface RiskBarProps {
  summary: RiskSummary;
  totalMiles: number;
}

export function RiskBar({ summary, totalMiles }: RiskBarProps) {
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-sm bg-slate-800" role="img" aria-label="Miles by risk level">
      {RISK_ORDER.map((key) => {
        const miles = milesAtRisk(summary, key);
        if (miles <= 0 || totalMiles <= 0) return null;
        return (
          <div
            key={key}
            style={{ width: `${(miles / totalMiles) * 100}%`, backgroundColor: RISK_COLORS[key] }}
            title={`${RISK_LABELS[key]}: ${miles.toFixed(1)} mi`}
          />
        );
      })}
    </div>
  );
}
