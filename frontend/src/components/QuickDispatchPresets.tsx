import { DISPATCH_PRESETS } from '../lib/presets';
import type { DispatchPreset } from '../types/routing';

interface QuickDispatchPresetsProps {
  activeId: string | null;
  disabled: boolean;
  onSelect: (preset: DispatchPreset) => void;
}

export function QuickDispatchPresets({ activeId, disabled, onSelect }: QuickDispatchPresetsProps) {
  return (
    <section className="border-b border-slate-800 px-4 py-3" aria-labelledby="presets-heading">
      <h2 id="presets-heading" className="section-heading mb-2">
        Quick dispatch presets
      </h2>
      <ul className="space-y-1">
        {DISPATCH_PRESETS.map((preset) => {
          const active = preset.id === activeId;
          return (
            <li key={preset.id}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onSelect(preset)}
                title={preset.loadNote}
                aria-pressed={active}
                className={`flex w-full items-center gap-3 rounded border px-2.5 py-1.5 text-left text-xs transition-colors disabled:cursor-wait disabled:opacity-60 ${
                  active
                    ? 'border-sky-600 bg-slate-800'
                    : 'border-slate-800 bg-slate-900 hover:border-slate-600 hover:bg-slate-800/60'
                }`}
              >
                <span className="w-9 shrink-0 font-mono font-semibold text-slate-300">{preset.highway}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-slate-200">
                    {preset.origin} to {preset.destination}
                  </span>
                  <span className="block truncate text-[11px] text-slate-500">{preset.loadNote}</span>
                </span>
                <span className="shrink-0 tabular-nums text-slate-300">
                  {preset.loadWeightLbs.toLocaleString('en-US')} lb
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
