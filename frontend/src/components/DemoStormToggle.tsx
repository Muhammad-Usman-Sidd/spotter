interface DemoStormToggleProps {
  enabled: boolean;
  busy: boolean;
  onChange: (enabled: boolean) => void;
}

export function DemoStormToggle({ enabled, busy, onChange }: DemoStormToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      disabled={busy}
      onClick={() => onChange(!enabled)}
      title="Overlay a synthetic winter wind and snow front on the recommended route to exercise the risk and load rules"
      className="group flex items-center gap-2 rounded px-2 py-1 text-xs transition-colors hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
    >
      <span
        className={`relative inline-block h-4 w-7 shrink-0 rounded-full border transition-colors ${
          enabled ? 'border-amber-500 bg-amber-500/30' : 'border-slate-600 bg-slate-800'
        }`}
        aria-hidden="true"
      >
        <span
          className={`absolute top-px h-3 w-3 rounded-full transition-all ${
            enabled ? 'left-[13px] bg-amber-400' : 'left-px bg-slate-400'
          }`}
        />
      </span>
      <span className={enabled ? 'text-amber-300' : 'text-slate-300'}>
        <span className="hidden sm:inline">Demo Storm Injection</span>
        <span className="sm:hidden">Demo storm</span>
      </span>
      {enabled && (
        <span className="hidden rounded-sm border border-amber-600 px-1 py-px text-[10px] font-semibold uppercase tracking-wider text-amber-400 md:inline">
          Synthetic
        </span>
      )}
    </button>
  );
}
