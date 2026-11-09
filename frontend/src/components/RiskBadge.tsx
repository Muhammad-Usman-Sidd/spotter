import { RISK_COLORS, RISK_LABELS } from '../lib/risk';
import type { RiskKey } from '../types/routing';

interface RiskBadgeProps {
  risk: RiskKey;
}

export function RiskBadge({ risk }: RiskBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-slate-100">
      <span
        className="inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: RISK_COLORS[risk] }}
        aria-hidden="true"
      />
      {RISK_LABELS[risk]}
    </span>
  );
}
