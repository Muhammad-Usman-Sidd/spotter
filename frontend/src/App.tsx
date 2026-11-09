import { useCallback, useMemo, useRef, useState } from 'react';
import { DemoStormNotice } from './components/DemoStormNotice';
import { DemoStormToggle } from './components/DemoStormToggle';
import { DispatcherNotes } from './components/DispatcherNotes';
import { RouteDetail } from './components/RouteDetail';
import { RouteForm } from './components/RouteForm';
import { RouteList } from './components/RouteList';
import { RouteMap } from './components/RouteMap';
import { useTripPlan } from './hooks/useTripPlan';
import { formatMiles } from './lib/format';
import type { CheckpointFocus, RouteOption, TripFormValues, TripPlan } from './types/routing';

function EmptyMap() {
  return (
    <div className="flex h-full items-center justify-center bg-slate-950 p-8 text-center">
      <div className="max-w-sm">
        <p className="text-sm font-semibold text-slate-200">No plan loaded</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Enter an origin, destination, departure time and load weight, then analyze to compare three
          routes against the hourly forecast at each checkpoint arrival time.
        </p>
      </div>
    </div>
  );
}

function PlanStatus({ plan }: { plan: TripPlan }) {
  const { meta } = plan;
  return (
    <dl className="hidden gap-5 text-xs tabular-nums md:flex">
      <div>
        <dt className="text-slate-500">Weather points</dt>
        <dd className="text-slate-200">{meta.weather_points}</dd>
      </div>
      <div>
        <dt className="text-slate-500">HTTP batches</dt>
        <dd className="text-slate-200">{meta.weather_requests}</dd>
      </div>
      <div>
        <dt className="text-slate-500">Cache hits</dt>
        <dd className="text-slate-200">{meta.cache_hits}</dd>
      </div>
      <div>
        <dt className="text-slate-500">Compute</dt>
        <dd className="text-slate-200">{(meta.elapsed_ms / 1000).toFixed(1)} s</dd>
      </div>
    </dl>
  );
}

export default function App() {
  const { plan, loading, error, submit } = useTripPlan();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<CheckpointFocus | null>(null);
  const [demoStorm, setDemoStorm] = useState(false);
  const lastValues = useRef<TripFormValues | null>(null);

  const selectedRoute = useMemo<RouteOption | null>(() => {
    if (!plan) return null;
    return plan.routes.find((route) => route.id === selectedId) ?? plan.routes[0] ?? null;
  }, [plan, selectedId]);

  const runPlan = useCallback(
    (values: TripFormValues, withStorm: boolean) => {
      lastValues.current = values;
      setSelectedId(null);
      setFocus(null);
      void submit({ ...values, demo_storm: withStorm });
    },
    [submit],
  );

  const handleSubmit = useCallback((values: TripFormValues) => runPlan(values, demoStorm), [runPlan, demoStorm]);

  const handleToggleStorm = useCallback(
    (enabled: boolean) => {
      setDemoStorm(enabled);
      if (lastValues.current) runPlan(lastValues.current, enabled);
    },
    [runPlan],
  );

  const handleSelectRoute = useCallback((id: string) => {
    setSelectedId(id);
    setFocus(null);
  }, []);

  const handleFocusCheckpoint = useCallback((index: number) => setFocus({ index }), []);

  const handleInspectStorm = useCallback(() => {
    const storm = plan?.meta.demo_storm;
    const route = plan?.routes.find((candidate) => candidate.id === storm?.route_id);
    if (!storm || !route) return;
    setSelectedId(route.id);
    const coreIndex = route.checkpoints.findIndex((checkpoint) => checkpoint.mile === storm.center_mile);
    setFocus(coreIndex >= 0 ? { index: coreIndex } : null);
  }, [plan]);

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 lg:h-screen">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900 px-4">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-semibold tracking-wide text-slate-100">Weather-Aware Truck Routing</h1>
          {plan && (
            <span className="hidden text-xs text-slate-400 sm:inline">
              {plan.origin.query} to {plan.destination.query}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {plan && <PlanStatus plan={plan} />}
          <DemoStormToggle enabled={demoStorm} busy={loading} onChange={handleToggleStorm} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside className="w-full shrink-0 overflow-y-auto border-slate-800 bg-slate-900 lg:w-[440px] lg:border-r">
          <RouteForm loading={loading} onSubmit={handleSubmit} />

          {error && (
            <div role="alert" className="border-b border-red-900 bg-red-950/60 px-4 py-3 text-xs text-red-200">
              {error}
            </div>
          )}

          {plan?.meta.demo_storm && <DemoStormNotice storm={plan.meta.demo_storm} onInspect={handleInspectStorm} />}

          {plan && plan.meta.warnings.length > 0 && (
            <ul className="border-b border-amber-900 bg-amber-950/40 px-4 py-3 text-xs text-amber-200">
              {plan.meta.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}

          {plan && selectedRoute && (
            <>
              <div className="border-b border-slate-800 px-4 py-2 text-xs tabular-nums text-slate-400">
                {formatMiles(selectedRoute.distance_miles)} mi corridor, {plan.load_weight_lbs.toLocaleString('en-US')} lb
                load, checkpoints every {plan.interval_miles} mi
              </div>
              <RouteList routes={plan.routes} selectedId={selectedRoute.id} onSelect={handleSelectRoute} />
              <DispatcherNotes route={selectedRoute} loadWeightLbs={plan.load_weight_lbs} />
              <RouteDetail route={selectedRoute} focus={focus} onFocusCheckpoint={handleFocusCheckpoint} />
            </>
          )}
        </aside>

        <main className="relative h-[75vh] min-h-[420px] lg:h-auto lg:flex-1">
          {plan && selectedRoute ? (
            <RouteMap plan={plan} selectedRoute={selectedRoute} focus={focus} onSelectRoute={handleSelectRoute} />
          ) : (
            <EmptyMap />
          )}
          {loading && (
            <div className="absolute inset-0 z-[1100] flex items-center justify-center bg-slate-950/70">
              <div className="rounded border border-slate-700 bg-slate-900 px-4 py-3 text-xs text-slate-200">
                Resolving routes and fetching batched forecasts
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
