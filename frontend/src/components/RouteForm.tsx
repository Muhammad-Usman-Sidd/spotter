import { useState } from 'react';
import type { FormEvent } from 'react';
import { nextFullHour, toLocalInputValue } from '../lib/format';
import { DISPATCH_PRESETS } from '../lib/presets';
import type { DispatchPreset, IntervalMiles, TripFormValues } from '../types/routing';
import { QuickDispatchPresets } from './QuickDispatchPresets';

const INTERVALS: readonly IntervalMiles[] = [10, 25, 50];

interface TripFields {
  origin: string;
  destination: string;
  loadWeightLbs: number;
}

interface RouteFormProps {
  loading: boolean;
  onSubmit: (values: TripFormValues) => void;
}

export function RouteForm({ loading, onSubmit }: RouteFormProps) {
  const [origin, setOrigin] = useState('Dallas, TX');
  const [destination, setDestination] = useState('Chicago, IL');
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextFullHour()));
  const [loadWeight, setLoadWeight] = useState('42000');
  const [checkpointInterval, setCheckpointInterval] = useState<IntervalMiles>(25);

  const activePresetId =
    DISPATCH_PRESETS.find(
      (preset) =>
        preset.origin === origin.trim() &&
        preset.destination === destination.trim() &&
        preset.loadWeightLbs === Number(loadWeight),
    )?.id ?? null;

  const submitTrip = ({ origin: from, destination: to, loadWeightLbs }: TripFields) => {
    const departureDate = new Date(departure);
    if (Number.isNaN(departureDate.getTime())) return;
    onSubmit({
      origin: from,
      destination: to,
      departure_time: departureDate.toISOString(),
      load_weight_lbs: loadWeightLbs,
      interval_miles: checkpointInterval,
    });
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitTrip({ origin: origin.trim(), destination: destination.trim(), loadWeightLbs: Number(loadWeight) });
  };

  const handlePreset = (preset: DispatchPreset) => {
    setOrigin(preset.origin);
    setDestination(preset.destination);
    setLoadWeight(String(preset.loadWeightLbs));
    submitTrip({
      origin: preset.origin,
      destination: preset.destination,
      loadWeightLbs: preset.loadWeightLbs,
    });
  };

  return (
    <>
      <QuickDispatchPresets activeId={activePresetId} disabled={loading} onSelect={handlePreset} />

      <form onSubmit={handleSubmit} className="space-y-3 border-b border-slate-800 p-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field-label" htmlFor="origin">
              Origin
            </label>
            <input
              id="origin"
              className="field-input"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              placeholder="City, State or lat,lon"
              required
              maxLength={200}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="destination">
              Destination
            </label>
            <input
              id="destination"
              className="field-input"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              placeholder="City, State or lat,lon"
              required
              maxLength={200}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field-label" htmlFor="departure">
              Departure
            </label>
            <input
              id="departure"
              type="datetime-local"
              className="field-input tabular-nums"
              value={departure}
              onChange={(event) => setDeparture(event.target.value)}
              required
            />
          </div>
          <div>
            <label className="field-label" htmlFor="load">
              Load weight (lb)
            </label>
            <input
              id="load"
              type="number"
              inputMode="numeric"
              className="field-input tabular-nums"
              value={loadWeight}
              onChange={(event) => setLoadWeight(event.target.value)}
              min={0}
              max={150000}
              step={500}
              required
            />
          </div>
        </div>

        <div>
          <span className="field-label" id="interval-label">
            Checkpoint interval
          </span>
          <div
            className="grid grid-cols-3 gap-px overflow-hidden rounded border border-slate-700 bg-slate-700"
            role="radiogroup"
            aria-labelledby="interval-label"
          >
            {INTERVALS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={checkpointInterval === option}
                onClick={() => setCheckpointInterval(option)}
                className={`py-1.5 text-sm tabular-nums transition-colors ${
                  checkpointInterval === option
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-900 text-slate-300 hover:bg-slate-800'
                }`}
              >
                {option} mi
              </button>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-sky-600 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-wait disabled:bg-slate-700 disabled:text-slate-400"
        >
          {loading ? 'Analyzing routes' : 'Analyze routes'}
        </button>
      </form>
    </>
  );
}
